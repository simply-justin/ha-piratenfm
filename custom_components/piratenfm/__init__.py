"""Piraten.FM → Music Assistant radio synchronization."""

from __future__ import annotations

from functools import partial

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

from .const import (
    ATTR_CONFIG_ENTRY_ID,
    CONF_AUTO_SYNC,
    CONF_MA_TOKEN,
    CONF_MA_URL,
    DOMAIN,
    SERVICE_REMOVE_MANAGED_STATIONS,
)
from .coordinator import PiratenFmConfigEntry, PiratenFmCoordinator
from .music_assistant import async_connect
from .piratenfm import PiratenFmClient
from .storage import SyncStore
from .sync import StationSynchronizer

PLATFORMS = [Platform.BUTTON, Platform.SENSOR, Platform.SWITCH]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register integration-wide services."""

    async def remove_managed_stations(call: ServiceCall) -> ServiceResponse:
        entry = hass.config_entries.async_get_entry(call.data[ATTR_CONFIG_ENTRY_ID])
        if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="entry_not_loaded"
            )
        coordinator: PiratenFmCoordinator = entry.runtime_data
        result = await coordinator.async_remove_managed_stations()
        return {"status": result.status.value, "removed": result.removed, "failed": result.failed}

    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE_MANAGED_STATIONS,
        remove_managed_stations,
        schema=vol.Schema({vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string}),
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: PiratenFmConfigEntry) -> bool:
    """Set up Piraten.FM from a config entry."""
    session = async_get_clientsession(hass)
    synchronizer = StationSynchronizer(
        SyncStore(hass, entry.entry_id),
        PiratenFmClient(session),
        partial(async_connect, session, entry.data[CONF_MA_URL], entry.data.get(CONF_MA_TOKEN)),
    )
    coordinator = PiratenFmCoordinator(hass, entry, synchronizer)
    # Publish persisted state immediately; the network sync runs in the background so
    # a slow Piraten.FM or Music Assistant never delays Home Assistant startup.
    coordinator.async_set_updated_data(await coordinator.async_snapshot(None))
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    if coordinator.options[CONF_AUTO_SYNC]:
        entry.async_create_background_task(
            hass, coordinator.async_refresh(), f"{DOMAIN}_initial_sync"
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PiratenFmConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: PiratenFmConfigEntry) -> None:
    """Delete stored state. Radios in Music Assistant are intentionally left alone."""
    await SyncStore(hass, entry.entry_id).async_remove()


async def _async_reload(hass: HomeAssistant, entry: PiratenFmConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
