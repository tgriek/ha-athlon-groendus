from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_LABEL,
    CONF_PORTAL_URL,
    DEFAULT_LABEL,
    DEFAULT_PORTAL_URL,
    DOMAIN,
)
from .api import AthlonGroendusClient
from .coordinator import AthlonGroendusCoordinator

PLATFORMS: list[str] = ["sensor"]

SERVICE_IMPORT_HISTORY = "import_history"
ATTR_ENTRY_ID = "entry_id"

SERVICE_IMPORT_HISTORY_SCHEMA = vol.Schema({vol.Optional(ATTR_ENTRY_ID): cv.string})


def _setting(entry: ConfigEntry, key: str, default: str) -> str:
    """Read a setting, preferring options (editable) over the original entry data."""
    value = entry.options.get(key, entry.data.get(key, default))
    return default if value in (None, "") else str(value)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Athlon Groendus integration (YAML not supported)."""
    hass.data.setdefault(DOMAIN, {})

    async def _handle_import_history(call: ServiceCall) -> ServiceResponse:
        """Re-import the full portal history as long-term statistics."""
        entry_id = call.data.get(ATTR_ENTRY_ID)
        coordinators = hass.data.get(DOMAIN, {})

        if entry_id:
            coordinator = coordinators.get(entry_id)
            if coordinator is None:
                raise HomeAssistantError(f"No loaded Athlon Groendus entry with id {entry_id}")
            targets = {entry_id: coordinator}
        else:
            targets = {k: v for k, v in coordinators.items() if hasattr(v, "async_import_history")}

        if not targets:
            raise HomeAssistantError("No loaded Athlon Groendus config entries")

        results: dict[str, Any] = {}
        for target_id, coordinator in targets.items():
            results[target_id] = await coordinator.async_import_history()
        return {"imported": results}

    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_HISTORY,
        _handle_import_history,
        schema=SERVICE_IMPORT_HISTORY_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Athlon Groendus from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Create coordinator and do the first refresh here. If the API is temporarily
    # unavailable we should raise ConfigEntryNotReady before forwarding platforms.
    session = async_get_clientsession(hass)
    client = AthlonGroendusClient(
        session,
        email=entry.data["email"],
        password=entry.data["password"],
        portal_url=_setting(entry, CONF_PORTAL_URL, DEFAULT_PORTAL_URL),
        label=_setting(entry, CONF_LABEL, DEFAULT_LABEL),
    )

    coordinator = AthlonGroendusCoordinator(
        hass,
        client=client,
        entry_id=entry.entry_id,
        chargepoint_id=entry.data["chargepoint_id"],
        update_interval_seconds=int(entry.options.get("update_interval_seconds", 300)),
        max_pages=int(entry.options.get("max_pages", 5)),
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:  # noqa: BLE001
        raise ConfigEntryNotReady(str(err)) from err

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Reload when the options (portal URL, label, interval) change so edits in
    # the UI take effect without restarting Home Assistant.
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry after its options were updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an Athlon Groendus config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


