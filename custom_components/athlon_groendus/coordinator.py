from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AthlonGroendusClient
from .const import DEFAULT_MAX_PAGES, DEFAULT_UPDATE_INTERVAL_SECONDS, STORE_KEY_FMT, STORE_VERSION

_LOGGER = logging.getLogger(__name__)

@dataclass
class EnergyAccumulatorState:
    """Persistent state to keep a monotonic total energy."""

    total_energy_kwh: float = 0.0
    seen_transaction_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EnergyAccumulatorState":
        return cls(
            total_energy_kwh=float(data.get("total_energy_kwh") or 0.0),
            seen_transaction_ids=list(data.get("seen_transaction_ids") or []),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_energy_kwh": self.total_energy_kwh,
            "seen_transaction_ids": self.seen_transaction_ids,
        }


class EntryStore:
    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = Store(hass, STORE_VERSION, STORE_KEY_FMT.format(entry_id=entry_id))

    async def async_load(self) -> EnergyAccumulatorState:
        data = await self._store.async_load()
        if not data:
            return EnergyAccumulatorState()
        return EnergyAccumulatorState.from_dict(data)

    async def async_save(self, state: EnergyAccumulatorState) -> None:
        await self._store.async_save(state.to_dict())


class AthlonGroendusCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass: HomeAssistant,
        *,
        client: AthlonGroendusClient,
        entry_id: str,
        chargepoint_id: str,
        update_interval_seconds: int = DEFAULT_UPDATE_INTERVAL_SECONDS,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> None:
        super().__init__(
            hass,
            name="athlon_groendus",
            update_interval=timedelta(seconds=update_interval_seconds),
        )
        self._client = client
        self._entry_id = entry_id
        self._chargepoint_id = chargepoint_id
        self._max_pages = max_pages
        self._store = EntryStore(hass, entry_id)
        self._acc_state: EnergyAccumulatorState | None = None

    @property
    def accumulator(self) -> EnergyAccumulatorState:
        if self._acc_state is None:
            return EnergyAccumulatorState()
        return self._acc_state

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            if self._acc_state is None:
                self._acc_state = await self._store.async_load()

            driver = await self._client.get_driver_and_chargepoints()

            # Fetch newest sessions first, accumulate only unseen transaction ids.
            new_txs: list[dict[str, Any]] = []
            seen = set(self._acc_state.seen_transaction_ids)
            fetched_txs: list[dict[str, Any]] = []

            for page in range(1, self._max_pages + 1):
                result = await self._client.list_transactions(page=page, size=50, sort="startDateTime:DESC")
                items = result.get("items") or []
                if not items:
                    break

                fetched_txs.extend(items)
                stop = False
                for tx in items:
                    # Only count sessions for selected chargepoint and that are completed (have endDateTime)
                    if tx.get("chargepointId") != self._chargepoint_id:
                        continue
                    if not tx.get("endDateTime"):
                        continue
                    tx_id = str(tx.get("id") or "")
                    if not tx_id:
                        continue
                    if tx_id in seen:
                        stop = True
                        continue
                    new_txs.append(tx)

                # If we hit an already-seen transaction in this page, older pages will be seen too.
                if stop:
                    break

            # Update monotonic total
            added_energy = 0.0
            for tx in new_txs:
                try:
                    added_energy += float(tx.get("totalEnergy") or 0.0)
                except (TypeError, ValueError):
                    continue

            if added_energy:
                new_total = float(self._acc_state.total_energy_kwh) + added_energy
                # Never decrease a TOTAL_INCREASING sensor (Energy Dashboard requirement)
                if new_total < float(self._acc_state.total_energy_kwh):
                    _LOGGER.warning(
                        "Computed total energy decreased (old=%s new=%s); keeping old to preserve monotonicity",
                        self._acc_state.total_energy_kwh,
                        new_total,
                    )
                else:
                    self._acc_state.total_energy_kwh = new_total

            # Track ids (keep last 500 to avoid unbounded growth)
            if new_txs:
                for tx in new_txs:
                    tx_id = str(tx.get("id") or "")
                    if tx_id:
                        self._acc_state.seen_transaction_ids.insert(0, tx_id)
                self._acc_state.seen_transaction_ids = self._acc_state.seen_transaction_ids[:500]
                await self._store.async_save(self._acc_state)

            # Provide some latest sessions for attributes (most recent first).
            # Use fetched transactions so "last session" works even when no new sessions appear.
            latest_sessions = sorted(
                [
                    tx
                    for tx in fetched_txs
                    if tx.get("chargepointId") == self._chargepoint_id and tx.get("endDateTime")
                ],
                key=lambda t: t.get("startDateTime") or "",
                reverse=True,
            )

            return {
                "driver": driver,
                "chargepoint_id": self._chargepoint_id,
                "total_energy_kwh": self._acc_state.total_energy_kwh,
                "latest_sessions": latest_sessions[:10],
            }
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(str(err)) from err


