"""Persistent synchronization state, stored with Home Assistant's Store helper.

Store writes are atomic (temp file + rename). Concurrent modification is prevented
by the synchronizer, which owns the single SyncState instance and holds a lock
for every read-modify-write cycle.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

STORAGE_VERSION = 1
STORAGE_MINOR_VERSION = 1

PENDING_ADD = "add"
PENDING_REMOVE = "remove"


@dataclass(slots=True)
class TrackedStation:
    """Everything we know about one Piraten.FM station."""

    stream_url: str
    music_assistant_library_id: str | None = None
    name: str | None = None
    frequency: str | None = None
    location: str | None = None
    # Name we last wrote to MA; a user rename in MA is left alone until this changes.
    display_name: str | None = None
    last_seen: str | None = None
    missing_count: int = 0
    managed_by_integration: bool = False
    # Write-ahead marker for an MA operation that may not have completed.
    pending: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrackedStation:
        """Build from stored data, ignoring unknown keys."""
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass(slots=True)
class SyncState:
    """All persisted state of one config entry."""

    stations: dict[str, TrackedStation] = field(default_factory=dict)
    last_successful_sync: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize for storage."""
        return {
            "stations": {sid: asdict(s) for sid, s in self.stations.items()},
            "last_successful_sync": self.last_successful_sync,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SyncState:
        """Deserialize stored data."""
        if not data:
            return cls()
        return cls(
            stations={
                sid: TrackedStation.from_dict(s) for sid, s in data.get("stations", {}).items()
            },
            last_successful_sync=data.get("last_successful_sync"),
        )

    @property
    def managed(self) -> dict[str, TrackedStation]:
        """Stations this integration owns."""
        return {sid: s for sid, s in self.stations.items() if s.managed_by_integration}

    def last_successful_sync_dt(self) -> datetime | None:
        """Return the last successful sync as datetime."""
        return dt_util.parse_datetime(self.last_successful_sync or "")


class _MigratingStore(Store[dict[str, Any]]):
    async def _async_migrate_func(
        self, old_major_version: int, old_minor_version: int, old_data: dict[str, Any]
    ) -> dict[str, Any]:
        # Version 1 is the first schema; future migrations go here.
        return old_data


class SyncStore:
    """Load and save SyncState for a config entry."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the store."""
        self._store = _MigratingStore(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{entry_id}",
            minor_version=STORAGE_MINOR_VERSION,
            atomic_writes=True,
        )

    async def async_load(self) -> SyncState:
        """Load persisted state (empty state on first run)."""
        return SyncState.from_dict(await self._store.async_load())

    async def async_save(self, state: SyncState) -> None:
        """Persist state atomically."""
        await self._store.async_save(state.as_dict())

    async def async_remove(self) -> None:
        """Delete the stored state."""
        await self._store.async_remove()
