from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

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


def _setting(entry: ConfigEntry, key: str, default: str) -> str:
    """Read a setting, preferring options (editable) over the original entry data."""
    value = entry.options.get(key, entry.data.get(key, default))
    return default if value in (None, "") else str(value)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Athlon Groendus integration (YAML not supported)."""
    hass.data.setdefault(DOMAIN, {})
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


