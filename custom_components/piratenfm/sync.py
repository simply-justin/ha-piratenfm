"""Reconciliation of Piraten.FM stations into the Music Assistant library.

Safety rules enforced here:

* Nothing is added, changed or counted as missing unless the Piraten.FM fetch
  succeeded, returned a non-empty list, and the MA library could be listed.
* Library IDs are re-resolved from MA on every cycle; stored IDs are never trusted.
* Only radios this integration created (managed_by_integration) are ever renamed
  or removed. Identity is the exact stream URL, never the name.
* Every MA write is preceded by a persisted write-ahead marker (``pending``) so an
  interrupted cycle is resolved from the library listing on the next run.
* An aborted cycle discards its in-memory changes and reloads persisted state.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from enum import StrEnum
from functools import partial
import time

from homeassistant.util import dt as dt_util

from .const import LOGGER, NAME_SEPARATOR
from .music_assistant import (
    LibraryRadio,
    MusicAssistantAuthError,
    MusicAssistantCommandError,
    MusicAssistantLibrary,
    MusicAssistantUnavailable,
)
from .piratenfm import COVER_URL, PiratenFmClient, PiratenFmError, Station
from .storage import PENDING_ADD, PENDING_REMOVE, SyncState, SyncStore, TrackedStation

type LibraryConnector = Callable[[], AbstractAsyncContextManager[MusicAssistantLibrary]]


class SyncStatus(StrEnum):
    """Outcome of a synchronization cycle."""

    SUCCESS = "success"
    PARTIAL = "partial"
    EMPTY_RESPONSE = "empty_response"
    PIRATENFM_UNAVAILABLE = "piratenfm_unavailable"
    MUSIC_ASSISTANT_UNAVAILABLE = "music_assistant_unavailable"
    AUTH_FAILED = "auth_failed"


@dataclass(frozen=True, slots=True)
class SyncOptions:
    """User options that influence a sync."""

    auto_remove: bool = True
    missing_threshold: int = 3
    include_frequency: bool = True
    include_location: bool = True


@dataclass(slots=True)
class SyncResult:
    """Summary of one cycle."""

    status: SyncStatus
    duration: float = 0.0
    stations: list[Station] | None = None
    added: int = 0
    updated: int = 0
    removed: int = 0
    deferred: int = 0
    failed: int = 0
    error: str | None = None
    failures: list[str] = field(default_factory=list)


def display_name(
    station_id: str,
    name: str | None,
    frequency: str | None,
    location: str | None,
    options: SyncOptions,
) -> str:
    """Return e.g. 'Radio Dop 2 Dop • 97.00 MHz • Gelselaar'."""
    parts = [name or f"Piraten.FM {station_id}"]
    if options.include_frequency and frequency:
        parts.append(frequency)
    if options.include_location and location:
        parts.append(location)
    return NAME_SEPARATOR.join(parts)


class StationSynchronizer:
    """Owns the sync state and serializes every operation on it."""

    def __init__(
        self, store: SyncStore, piratenfm: PiratenFmClient, connect: LibraryConnector
    ) -> None:
        """Initialize."""
        self._store = store
        self._piratenfm = piratenfm
        self._connect = connect
        self._lock = asyncio.Lock()
        self._state: SyncState | None = None

    @property
    def is_running(self) -> bool:
        """Return True while a cycle or cleanup is in progress."""
        return self._lock.locked()

    async def async_get_state(self) -> SyncState:
        """Return the current state, loading it on first use."""
        if self._state is None:
            self._state = await self._store.async_load()
        return self._state

    async def async_sync(self, options: SyncOptions) -> SyncResult | None:
        """Run one cycle. Returns None if another cycle is already running."""
        if self._lock.locked():
            LOGGER.debug("Sync already in progress, skipping overlapping request")
            return None
        async with self._lock:
            started = time.monotonic()
            result = await self._guarded(partial(self._sync, options=options))
            result.duration = round(time.monotonic() - started, 3)
            LOGGER.info(
                "Piraten.FM sync %s: added=%s updated=%s removed=%s deferred=%s failed=%s",
                result.status,
                result.added,
                result.updated,
                result.removed,
                result.deferred,
                result.failed,
            )
            return result

    async def async_remove_all_managed(self) -> SyncResult:
        """Remove every radio this integration created from MA (cleanup)."""
        async with self._lock:
            return await self._guarded(self._remove_all)

    async def _guarded(self, work: Callable[[SyncState], Awaitable[SyncResult]]) -> SyncResult:
        state = await self.async_get_state()
        try:
            return await work(state)
        except MusicAssistantAuthError as err:
            self._state = None
            return SyncResult(SyncStatus.AUTH_FAILED, error=str(err))
        except MusicAssistantUnavailable as err:
            LOGGER.warning("Music Assistant unavailable, nothing changed: %s", err)
            self._state = None
            return SyncResult(SyncStatus.MUSIC_ASSISTANT_UNAVAILABLE, error=str(err))
        except BaseException:
            # Cancellation (e.g. HA shutdown) or a bug: drop unsaved in-memory changes.
            self._state = None
            raise

    async def _sync(self, state: SyncState, options: SyncOptions) -> SyncResult:
        try:
            stations = await self._piratenfm.async_get_stations()
        except PiratenFmError as err:
            LOGGER.warning("Piraten.FM unavailable, nothing changed: %s", err)
            return SyncResult(SyncStatus.PIRATENFM_UNAVAILABLE, error=str(err))
        if not stations:
            # An empty list is indistinguishable from an API glitch: never treat it as
            # proof that every station went offline.
            LOGGER.warning("Piraten.FM returned no stations; skipping reconciliation")
            return SyncResult(SyncStatus.EMPTY_RESPONSE, stations=[])

        result = SyncResult(SyncStatus.SUCCESS, stations=stations)
        async with self._connect() as library:
            run = _Run(state, library, self._store, self._piratenfm, result)
            await run.reconcile_with_library()
            await run.apply_active(stations, options)
            await run.apply_absent({s.station_id for s in stations}, options)
        if result.failed:
            result.status = SyncStatus.PARTIAL
        state.last_successful_sync = dt_util.utcnow().isoformat()
        await self._store.async_save(state)
        return result

    async def _remove_all(self, state: SyncState) -> SyncResult:
        result = SyncResult(SyncStatus.SUCCESS)
        async with self._connect() as library:
            run = _Run(state, library, self._store, self._piratenfm, result)
            await run.reconcile_with_library()
            for station_id, entry in list(state.managed.items()):
                await run.remove(station_id, entry)
        if result.failed:
            result.status = SyncStatus.PARTIAL
        await self._store.async_save(state)
        return result


class _Run:
    """One reconciliation pass against a connected Music Assistant library.

    The steps run in this order:
    1. ``reconcile_with_library`` - learn what is really in MA right now.
    2. ``apply_active``           - add or rename stations that are on air.
    3. ``apply_absent``           - count missing stations, remove expired ones.
    """

    def __init__(
        self,
        state: SyncState,
        library: MusicAssistantLibrary,
        store: SyncStore,
        piratenfm: PiratenFmClient,
        result: SyncResult,
    ) -> None:
        self.state = state
        self.library = library
        self.store = store
        self.piratenfm = piratenfm
        self.result = result

    # Step 1 ---------------------------------------------------------------

    async def reconcile_with_library(self) -> None:
        """Re-resolve library IDs from MA and finish interrupted operations."""
        radios = await self.library.async_piratenfm_radios()
        stations = self.state.stations

        for station_id, entry in list(stations.items()):
            found = _first(station_id, radios.get(station_id, []))
            entry.music_assistant_library_id = found.library_id if found else None

            if found and entry.pending == PENDING_ADD:
                # Our add reached MA but HA stopped before we recorded it: claim it.
                entry.managed_by_integration = True
                entry.display_name = found.name
            if not found and entry.pending == PENDING_REMOVE:
                # Our removal completed but HA stopped before we recorded it.
                del stations[station_id]
                continue
            entry.pending = None

        for station_id, found_list in radios.items():
            if station_id not in stations and (found := _first(station_id, found_list)):
                # Someone else added this stream: remember it so we never add a
                # duplicate, but never rename or remove it (unmanaged).
                stations[station_id] = TrackedStation(
                    stream_url=found.stream_url,
                    music_assistant_library_id=found.library_id,
                    display_name=found.name,
                )

    # Step 2 ---------------------------------------------------------------

    async def apply_active(self, stations: list[Station], options: SyncOptions) -> None:
        """Add new stations and rename known ones whose metadata changed."""
        now = dt_util.utcnow().isoformat()
        for station in stations:
            entry = self.state.stations.setdefault(
                station.station_id, TrackedStation(stream_url=station.stream_url)
            )
            _mark_seen(entry, station, now)

            in_library = entry.music_assistant_library_id is not None
            if in_library and not entry.managed_by_integration:
                continue  # unmanaged: hands off

            name = display_name(
                station.station_id, entry.name, entry.frequency, entry.location, options
            )
            if not in_library:
                await self._add(station.station_id, entry, name)
            elif _needs_update(entry, name) and await self._upsert(station.station_id, entry, name):
                self.result.updated += 1

    async def _add(self, station_id: str, entry: TrackedStation, name: str) -> None:
        if not await self.piratenfm.async_probe_stream(station_id):
            # Not an absence: the station is listed, its stream just isn't ready.
            LOGGER.info("Stream of %s not answering yet; retry next sync", station_id)
            self.result.deferred += 1
            return
        entry.pending = PENDING_ADD
        await self.store.async_save(self.state)  # write-ahead
        if await self._upsert(station_id, entry, name):
            entry.managed_by_integration = True
            entry.pending = None
            self.result.added += 1

    async def _upsert(self, station_id: str, entry: TrackedStation, name: str) -> bool:
        try:
            radio = await self.library.async_upsert_radio(entry.stream_url, name, COVER_URL)
        except MusicAssistantCommandError as err:
            self._fail(station_id, "add/update", err)
            return False
        entry.music_assistant_library_id = radio.library_id
        entry.display_name = name
        entry.cover_url = COVER_URL
        return True

    # Step 3 ---------------------------------------------------------------

    async def apply_absent(self, active_ids: set[str], options: SyncOptions) -> None:
        """Count absences and remove managed stations past the threshold."""
        for station_id, entry in list(self.state.stations.items()):
            if station_id in active_ids:
                continue
            entry.missing_count += 1
            if entry.missing_count < options.missing_threshold:
                continue
            if entry.music_assistant_library_id is None:
                del self.state.stations[station_id]  # nothing in MA; just forget it
            elif entry.managed_by_integration and options.auto_remove:
                await self.remove(station_id, entry)

    async def remove(self, station_id: str, entry: TrackedStation) -> None:
        """Remove a managed radio from MA (write-ahead logged) and forget it."""
        library_id = entry.music_assistant_library_id
        if library_id is None:
            del self.state.stations[station_id]
            return
        entry.pending = PENDING_REMOVE
        await self.store.async_save(self.state)  # write-ahead
        try:
            await self.library.async_remove_radio(library_id)
        except MusicAssistantCommandError as err:
            self._fail(station_id, "remove", err)
            return
        del self.state.stations[station_id]
        self.result.removed += 1

    def _fail(self, station_id: str, operation: str, err: Exception) -> None:
        LOGGER.warning("Music Assistant %s of station %s failed: %s", operation, station_id, err)
        self.result.failed += 1
        self.result.failures.append(f"{station_id}: {operation} failed")


def _needs_update(entry: TrackedStation, name: str) -> bool:
    """Return True if the name we want, or the cover, differs from what we last wrote."""
    return entry.display_name != name or entry.cover_url != COVER_URL


def _mark_seen(entry: TrackedStation, station: Station, now: str) -> None:
    """Record that a station is on air, keeping old metadata for missing fields."""
    entry.name = station.name or entry.name
    entry.frequency = station.frequency or entry.frequency
    entry.location = station.location or entry.location
    entry.last_seen = now
    entry.missing_count = 0


def _first(station_id: str, radios: list[LibraryRadio]) -> LibraryRadio | None:
    """Pick the oldest (lowest numeric ID) radio when MA holds duplicates."""
    if len(radios) > 1:
        LOGGER.warning(
            "Multiple library radios use the stream of station %s (ids %s); using the oldest",
            station_id,
            ", ".join(r.library_id for r in radios),
        )
    return min(radios, key=lambda r: (len(r.library_id), r.library_id), default=None)
