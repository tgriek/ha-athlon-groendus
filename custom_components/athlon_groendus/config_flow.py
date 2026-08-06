from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AthlonGroendusAuthError, AthlonGroendusClient, AthlonGroendusLabelError
from .const import (
    CONF_CHARGEPOINT_ID,
    CONF_EMAIL,
    CONF_LABEL,
    CONF_MAX_PAGES,
    CONF_PASSWORD,
    CONF_PORTAL_URL,
    CONF_UPDATE_INTERVAL,
    DEFAULT_MAX_PAGES,
    DEFAULT_PORTAL_URL,
    DEFAULT_UPDATE_INTERVAL_SECONDS,
    DOMAIN,
    derive_label,
)


def _normalize_portal_url(portal_url: str) -> str:
    portal_url = (portal_url or DEFAULT_PORTAL_URL).strip()
    if not portal_url.startswith(("http://", "https://")):
        portal_url = f"https://{portal_url}"
    return portal_url if portal_url.endswith("/") else f"{portal_url}/"


async def _validate_credentials(
    hass: HomeAssistant, email: str, password: str, portal_url: str, label: str
) -> dict:
    session = async_get_clientsession(hass)
    client = AthlonGroendusClient(
        session, email=email, password=password, portal_url=portal_url, label=label
    )
    driver = await client.get_driver_and_chargepoints()
    return driver


class AthlonGroendusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]
            portal_url = _normalize_portal_url(user_input.get(CONF_PORTAL_URL, DEFAULT_PORTAL_URL))
            # An empty label means "figure it out from the portal URL", the same
            # way the portal frontend does.
            label = (user_input.get(CONF_LABEL) or "").strip() or derive_label(portal_url)

            try:
                driver = await _validate_credentials(self.hass, email, password, portal_url, label)
            except AthlonGroendusLabelError:
                errors["base"] = "wrong_label"
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
                    self.context["portal_url"] = portal_url
                    self.context["label"] = label
                    return await self.async_step_select_chargepoint()

        schema = vol.Schema(
            {
                vol.Required(CONF_EMAIL): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_PORTAL_URL, default=DEFAULT_PORTAL_URL): str,
                vol.Optional(CONF_LABEL, default=""): str,
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
                    CONF_PORTAL_URL: self.context["portal_url"],
                    CONF_LABEL: self.context["label"],
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

    def _current(self, key: str, default):
        """Options win over the values stored when the entry was created."""
        value = self._entry.options.get(key, self._entry.data.get(key, default))
        return default if value in (None, "") else value

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            portal_url = _normalize_portal_url(user_input.get(CONF_PORTAL_URL, DEFAULT_PORTAL_URL))
            label = (user_input.get(CONF_LABEL) or "").strip() or derive_label(portal_url)

            try:
                await _validate_credentials(
                    self.hass,
                    self._entry.data[CONF_EMAIL],
                    self._entry.data[CONF_PASSWORD],
                    portal_url,
                    label,
                )
            except AthlonGroendusLabelError:
                errors["base"] = "wrong_label"
            except AthlonGroendusAuthError:
                errors["base"] = "auth"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title="",
                    data={
                        **user_input,
                        CONF_PORTAL_URL: portal_url,
                        CONF_LABEL: label,
                    },
                )

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_UPDATE_INTERVAL,
                    default=self._current(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_SECONDS),
                ): vol.Coerce(int),
                vol.Optional(
                    CONF_MAX_PAGES,
                    default=self._current(CONF_MAX_PAGES, DEFAULT_MAX_PAGES),
                ): vol.Coerce(int),
                vol.Required(
                    CONF_PORTAL_URL,
                    default=self._current(CONF_PORTAL_URL, DEFAULT_PORTAL_URL),
                ): str,
                vol.Optional(
                    CONF_LABEL,
                    default=self._current(CONF_LABEL, derive_label(DEFAULT_PORTAL_URL)),
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
