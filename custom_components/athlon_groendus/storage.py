from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORE_KEY_FMT, STORE_VERSION


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


