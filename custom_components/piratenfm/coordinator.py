"""DataUpdateCoordinator that drives the station synchronizer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_AUTO_REMOVE,
    CONF_AUTO_SYNC,
    CONF_INCLUDE_FREQUENCY,
    CONF_INCLUDE_LOCATION,
    CONF_MISSING_THRESHOLD,
    CONF_SCAN_INTERVAL,
    DEFAULT_OPTIONS,
    DOMAIN,
    LOGGER,
)
from .piratenfm import Station
from .sync import StationSynchronizer, SyncOptions, SyncResult, SyncStatus

type PiratenFmConfigEntry = ConfigEntry[PiratenFmCoordinator]


@dataclass(frozen=True, slots=True)
class PiratenFmData:
    """Snapshot exposed to entities."""

    stations: list[Station]
    managed_count: int
    unmanaged_count: int
    last_successful_sync: datetime | None
    last_result: SyncResult | None


def entry_options(entry: ConfigEntry) -> dict[str, Any]:
    """Return the entry options with defaults filled in."""
    return {**DEFAULT_OPTIONS, **entry.options}


class PiratenFmCoordinator(DataUpdateCoordinator[PiratenFmData]):
    """Run the synchronizer on a schedule and publish its results."""

    config_entry: PiratenFmConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: PiratenFmConfigEntry,
        synchronizer: StationSynchronizer,
    ) -> None:
        """Initialize."""
        options = entry_options(entry)
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=(
                timedelta(seconds=options[CONF_SCAN_INTERVAL]) if options[CONF_AUTO_SYNC] else None
            ),
        )
        self.synchronizer = synchronizer

    @property
    def options(self) -> dict[str, Any]:
        """Return current options."""
        return entry_options(self.config_entry)

    @property
    def sync_options(self) -> SyncOptions:
        """Return the options relevant for a sync."""
        options = self.options
        return SyncOptions(
            auto_remove=options[CONF_AUTO_REMOVE],
            missing_threshold=options[CONF_MISSING_THRESHOLD],
            include_frequency=options[CONF_INCLUDE_FREQUENCY],
            include_location=options[CONF_INCLUDE_LOCATION],
        )

    async def _async_update_data(self) -> PiratenFmData:
        result = await self.synchronizer.async_sync(self.sync_options)
        if result is None and self.data is not None:
            return self.data  # overlapping request; the running cycle will publish
        if result is not None and result.status is SyncStatus.AUTH_FAILED:
            raise ConfigEntryAuthFailed(translation_domain=DOMAIN, translation_key="auth_failed")
        return await self.async_snapshot(result)

    async def async_snapshot(self, result: SyncResult | None) -> PiratenFmData:
        """Build entity data from persisted state plus the latest result."""
        state = await self.synchronizer.async_get_state()
        managed = len(state.managed)
        stations = (
            result.stations
            if result is not None and result.stations is not None
            else (self.data.stations if self.data else [])
        )
        return PiratenFmData(
            stations=stations,
            managed_count=managed,
            unmanaged_count=len(state.stations) - managed,
            last_successful_sync=state.last_successful_sync_dt(),
            last_result=result
            if result is not None
            else (self.data.last_result if self.data else None),
        )

    async def async_remove_managed_stations(self) -> SyncResult:
        """Remove every radio this integration created and publish the new state."""
        result = await self.synchronizer.async_remove_all_managed()
        if result.status is SyncStatus.AUTH_FAILED:
            raise ConfigEntryAuthFailed(translation_domain=DOMAIN, translation_key="auth_failed")
        self.async_set_updated_data(await self.async_snapshot(None))
        return result
