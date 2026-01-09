from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AthlonGroendusAuthError, AthlonGroendusClient
from .const import (
    CONF_CHARGEPOINT_ID,
    CONF_EMAIL,
    CONF_MAX_PAGES,
    CONF_PASSWORD,
    CONF_UPDATE_INTERVAL,
    DEFAULT_MAX_PAGES,
    DEFAULT_UPDATE_INTERVAL_SECONDS,
    DOMAIN,
)


async def _validate_credentials(hass: HomeAssistant, email: str, password: str) -> dict:
    session = async_get_clientsession(hass)
    client = AthlonGroendusClient(session, email=email, password=password)
    driver = await client.get_driver_and_chargepoints()
    return driver


class AthlonGroendusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]

            try:
                driver = await _validate_credentials(self.hass, email, password)
            except AthlonGroendusAuthError:
                errors["base"] = "auth"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                chargepoints = driver.get("chargepoints") or []
                if not chargepoints:
                    errors["base"] = "no_chargepoints"
                else:
                    self.context["driver"] = driver
                    self.context["email"] = email
                    self.context["password"] = password
                    return await self.async_step_select_chargepoint()

        schema = vol.Schema(
            {
                vol.Required(CONF_EMAIL): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_select_chargepoint(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        driver = self.context.get("driver") or {}
        chargepoints = driver.get("chargepoints") or []

        options = {cp.get("chargepointId"): cp.get("chargepointId") for cp in chargepoints if cp.get("chargepointId")}

        if user_input is not None:
            cp_id = user_input[CONF_CHARGEPOINT_ID]
            title = f"Athlon Groendus ({cp_id})"
            await self.async_set_unique_id(f"{DOMAIN}_{cp_id}")
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=title,
                data={
                    CONF_EMAIL: self.context["email"],
                    CONF_PASSWORD: self.context["password"],
                    CONF_CHARGEPOINT_ID: cp_id,
                },
                options={
                    CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL_SECONDS,
                    CONF_MAX_PAGES: DEFAULT_MAX_PAGES,
                },
            )

        schema = vol.Schema({vol.Required(CONF_CHARGEPOINT_ID): vol.In(options)})
        return self.async_show_form(step_id="select_chargepoint", data_schema=schema, errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return AthlonGroendusOptionsFlow(config_entry)


class AthlonGroendusOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_UPDATE_INTERVAL,
                    default=self._entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_SECONDS),
                ): vol.Coerce(int),
                vol.Optional(
                    CONF_MAX_PAGES,
                    default=self._entry.options.get(CONF_MAX_PAGES, DEFAULT_MAX_PAGES),
                ): vol.Coerce(int),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


