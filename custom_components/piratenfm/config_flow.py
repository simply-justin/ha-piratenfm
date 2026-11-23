"""Config flow for Piraten.FM."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol
from yarl import URL

from .const import (
    CONF_AUTO_REMOVE,
    CONF_AUTO_SYNC,
    CONF_INCLUDE_FREQUENCY,
    CONF_INCLUDE_LOCATION,
    CONF_MA_TOKEN,
    CONF_MA_URL,
    CONF_MISSING_THRESHOLD,
    CONF_SCAN_INTERVAL,
    DEFAULT_MA_URL,
    DEFAULT_OPTIONS,
    DOMAIN,
    LOGGER,
    MAX_MISSING_THRESHOLD,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .music_assistant import MusicAssistantAuthError, MusicAssistantUnavailable, async_connect

MA_DOMAIN = "music_assistant"
_PASSWORD = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)
_URL = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.URL))


class PiratenFmConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Piraten.FM."""

    VERSION = 1

    async def _async_validate(
        self, url: str, token: str | None
    ) -> tuple[str | None, dict[str, str]]:
        """Connect to MA; return (server_id, errors)."""
        if URL(url).scheme not in ("http", "https", "ws", "wss"):
            return None, {CONF_MA_URL: "invalid_url"}
        try:
            async with async_connect(async_get_clientsession(self.hass), url, token) as library:
                return library.server_id or url, {}
        except MusicAssistantAuthError:
            return None, {"base": "invalid_auth"}
        except MusicAssistantUnavailable as err:
            LOGGER.debug("Cannot connect to Music Assistant: %s", err)
            return None, {"base": "cannot_connect"}

    def _suggested_url(self) -> str:
        # Discover the URL of an already configured official Music Assistant integration.
        for entry in self.hass.config_entries.async_entries(MA_DOMAIN):
            if url := entry.data.get("url"):
                return str(url)
        return DEFAULT_MA_URL

    @staticmethod
    def _schema(url: str) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_MA_URL, default=url): _URL,
                vol.Optional(CONF_MA_TOKEN): _PASSWORD,
            }
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the Music Assistant URL and token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            server_id, errors = await self._async_validate(
                user_input[CONF_MA_URL], user_input.get(CONF_MA_TOKEN)
            )
            if not errors:
                await self.async_set_unique_id(server_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Piraten.FM", data=user_input, options=dict(DEFAULT_OPTIONS)
                )
        url = user_input[CONF_MA_URL] if user_input else self._suggested_url()
        return self.async_show_form(step_id="user", data_schema=self._schema(url), errors=errors)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the Music Assistant connection."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            server_id, errors = await self._async_validate(
                user_input[CONF_MA_URL], user_input.get(CONF_MA_TOKEN)
            )
            if not errors:
                await self.async_set_unique_id(server_id)
                self._abort_if_unique_id_mismatch(reason="wrong_server")
                return self.async_update_reload_and_abort(entry, data=user_input)
        return self.async_show_form(
            step_id="reconfigure", data_schema=self._schema(entry.data[CONF_MA_URL]), errors=errors
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauthentication after the token was rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new token."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            _, errors = await self._async_validate(
                entry.data[CONF_MA_URL], user_input[CONF_MA_TOKEN]
            )
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_MA_TOKEN: user_input[CONF_MA_TOKEN]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_MA_TOKEN): _PASSWORD}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> PiratenFmOptionsFlow:
        """Return the options flow."""
        return PiratenFmOptionsFlow()


class PiratenFmOptionsFlow(OptionsFlow):
    """Sync behaviour options."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show and save options."""
        if user_input is not None:
            # NumberSelector yields floats; store whole numbers.
            for key in (CONF_SCAN_INTERVAL, CONF_MISSING_THRESHOLD):
                user_input[key] = int(user_input[key])
            return self.async_create_entry(data=user_input)
        current = {**DEFAULT_OPTIONS, **self.config_entry.options}

        def number(lo: int, hi: int) -> selector.NumberSelector:
            return selector.NumberSelector(
                selector.NumberSelectorConfig(min=lo, max=hi, mode=selector.NumberSelectorMode.BOX)
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_AUTO_SYNC): bool,
                vol.Required(CONF_SCAN_INTERVAL): number(MIN_SCAN_INTERVAL, MAX_SCAN_INTERVAL),
                vol.Required(CONF_AUTO_REMOVE): bool,
                vol.Required(CONF_MISSING_THRESHOLD): number(1, MAX_MISSING_THRESHOLD),
                vol.Required(CONF_INCLUDE_FREQUENCY): bool,
                vol.Required(CONF_INCLUDE_LOCATION): bool,
            }
        )
        return self.async_show_form(
            step_id="init", data_schema=self.add_suggested_values_to_schema(schema, current)
        )
