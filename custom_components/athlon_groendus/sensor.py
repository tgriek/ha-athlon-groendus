from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CURRENCY_EURO, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_CHARGEPOINT_ID,
    CONF_MAX_PAGES,
    CONF_UPDATE_INTERVAL,
    DEFAULT_MAX_PAGES,
    DEFAULT_UPDATE_INTERVAL_SECONDS,
    DOMAIN,
)
from .coordinator import AthlonGroendusCoordinator


@dataclass(frozen=True)
class AthlonGroendusEntityDescription:
    key: str
    name: str


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AthlonGroendusCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        [
            AthlonGroendusTotalEnergySensor(coordinator, entry),
            AthlonGroendusLastSessionEnergySensor(coordinator, entry),
            AthlonGroendusLastSessionCostSensor(coordinator, entry),
        ]
    )


class AthlonGroendusBaseEntity(CoordinatorEntity[AthlonGroendusCoordinator]):
    def __init__(self, coordinator: AthlonGroendusCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        chargepoint_id = entry.data.get(CONF_CHARGEPOINT_ID)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, str(chargepoint_id))},
            "name": f"Athlon Groendus ({chargepoint_id})",
            "manufacturer": "Athlon / Groendus",
        }


class AthlonGroendusTotalEnergySensor(AthlonGroendusBaseEntity, SensorEntity):
    """Energy Dashboard compatible total energy sensor."""

    _attr_name = "Athlon charging energy total"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_total_energy"

    @property
    def native_value(self) -> float | None:
        return float(self.coordinator.data.get("total_energy_kwh") or 0.0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "chargepoint_id": self._entry.data.get(CONF_CHARGEPOINT_ID),
            "seen_transactions": len(self.coordinator.accumulator.seen_transaction_ids),
        }


class _LastSessionBase(AthlonGroendusBaseEntity, SensorEntity):
    def _latest(self) -> dict[str, Any] | None:
        sessions = self.coordinator.data.get("latest_sessions") or []
        return sessions[0] if sessions else None


class AthlonGroendusLastSessionEnergySensor(_LastSessionBase):
    _attr_name = "Athlon last session energy"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_last_session_energy"

    @property
    def native_value(self) -> float | None:
        tx = self._latest()
        if not tx:
            return None
        try:
            return float(tx.get("totalEnergy") or 0.0)
        except (TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        tx = self._latest() or {}
        return {
            "start": tx.get("startDateTime"),
            "end": tx.get("endDateTime"),
            "transaction_id": tx.get("id"),
            "charge_card_id": tx.get("visualNumber"),
            "status": tx.get("status"),
        }


class AthlonGroendusLastSessionCostSensor(_LastSessionBase):
    _attr_name = "Athlon last session cost"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = CURRENCY_EURO

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_last_session_cost"

    @property
    def native_value(self) -> float | None:
        tx = self._latest()
        if not tx:
            return None
        try:
            return float(tx.get("totalCost") or 0.0)
        except (TypeError, ValueError):
            return None


