"""Reconciliation behaviour of StationSynchronizer."""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.core import HomeAssistant
import pytest

from custom_components.piratenfm.music_assistant import MusicAssistantAuthError
from custom_components.piratenfm.piratenfm import COVER_URL, PiratenFmInvalidResponse
from custom_components.piratenfm.storage import PENDING_ADD, PENDING_REMOVE, SyncStore
from custom_components.piratenfm.sync import (
    StationSynchronizer,
    SyncOptions,
    SyncStatus,
    display_name,
)

from .fakes import FakeLibrary, FakePiratenFm, station, url

OPTS = SyncOptions()


@pytest.fixture
def lib() -> FakeLibrary:
    return FakeLibrary()


@pytest.fixture
def pfm() -> FakePiratenFm:
    return FakePiratenFm([station("AAA111", "Radio Dop 2 Dop", "97.00 MHz", "Gelselaar")])


def make(hass: HomeAssistant, pfm: FakePiratenFm, lib: FakeLibrary) -> StationSynchronizer:
    """A fresh synchronizer on the same store, i.e. what you get after an HA restart."""
    return StationSynchronizer(SyncStore(hass, "entry"), pfm, lib.connect)  # type: ignore[arg-type]


async def run(sync: StationSynchronizer, options: SyncOptions = OPTS) -> Any:
    result = await sync.async_sync(options)
    assert result is not None
    return result


async def test_adds_new_station_with_display_name(hass, pfm, lib) -> None:
    result = await run(make(hass, pfm, lib))
    assert result.status is SyncStatus.SUCCESS
    assert result.added == 1
    assert list(lib.radios.values()) == [(url("AAA111"), "Radio Dop 2 Dop • 97.00 MHz • Gelselaar")]


async def test_display_name_options() -> None:
    opts = SyncOptions(include_frequency=False, include_location=False)
    assert display_name("X", "Name", "97 MHz", "Leek", opts) == "Name"
    assert display_name("X", None, None, None, OPTS) == "Piraten.FM X"


async def test_no_duplicates_on_repeated_sync(hass, pfm, lib) -> None:
    sync = make(hass, pfm, lib)
    await run(sync)
    result = await run(sync)
    assert result.added == 0 and result.updated == 0
    assert len(lib.radios) == 1
    assert len(lib.upserts) == 1


async def test_metadata_change_renames_radio(hass, pfm, lib) -> None:
    sync = make(hass, pfm, lib)
    await run(sync)
    pfm.stations = [station("AAA111", "Radio Dop 2 Dop", "98.10 MHz", "Gelselaar")]
    result = await run(sync)
    assert result.updated == 1
    assert next(iter(lib.radios.values()))[1] == "Radio Dop 2 Dop • 98.10 MHz • Gelselaar"


async def test_removed_after_threshold_successful_misses(hass, pfm, lib) -> None:
    sync = make(hass, pfm, lib)
    await run(sync)
    pfm.stations = [station("BBB222")]
    for _ in range(2):
        await run(sync)
        assert lib.by_url(url("AAA111"))
    result = await run(sync)
    assert result.removed == 1
    assert not lib.by_url(url("AAA111"))
    assert "AAA111" not in (await sync.async_get_state()).stations


async def test_station_returning_resets_counter_and_is_readded(hass, pfm, lib) -> None:
    sync = make(hass, pfm, lib)
    await run(sync)
    original = pfm.stations
    pfm.stations = [station("BBB222")]
    await run(sync)
    await run(sync)
    pfm.stations = [*original, station("BBB222")]
    await run(sync)
    state = await sync.async_get_state()
    assert state.stations["AAA111"].missing_count == 0
    # Gone for good, then back again: it must be re-added.
    pfm.stations = [station("BBB222")]
    for _ in range(3):
        await run(sync)
    assert not lib.by_url(url("AAA111"))
    pfm.stations = original
    result = await run(sync)
    assert result.added == 1
    assert lib.by_url(url("AAA111"))


async def test_auto_remove_disabled_keeps_station(hass, pfm, lib) -> None:
    sync = make(hass, pfm, lib)
    await run(sync)
    pfm.stations = [station("BBB222")]
    for _ in range(5):
        await run(sync, SyncOptions(auto_remove=False))
    assert lib.by_url(url("AAA111"))


async def test_api_failure_changes_nothing(hass, pfm, lib) -> None:
    sync = make(hass, pfm, lib)
    await run(sync)
    pfm.fail()
    for _ in range(5):
        result = await run(sync)
        assert result.status is SyncStatus.PIRATENFM_UNAVAILABLE
    state = await sync.async_get_state()
    assert state.stations["AAA111"].missing_count == 0
    assert lib.by_url(url("AAA111"))


async def test_invalid_response_changes_nothing(hass, pfm, lib) -> None:
    sync = make(hass, pfm, lib)
    await run(sync)
    pfm.stations = PiratenFmInvalidResponse("garbage")
    result = await run(sync)
    assert result.status is SyncStatus.PIRATENFM_UNAVAILABLE
    assert (await sync.async_get_state()).stations["AAA111"].missing_count == 0


async def test_empty_response_never_counts_as_absence(hass, pfm, lib) -> None:
    sync = make(hass, pfm, lib)
    await run(sync)
    pfm.stations = []
    for _ in range(5):
        result = await run(sync)
        assert result.status is SyncStatus.EMPTY_RESPONSE
    assert (await sync.async_get_state()).stations["AAA111"].missing_count == 0
    assert lib.by_url(url("AAA111"))


async def test_music_assistant_unavailable_changes_nothing(hass, pfm, lib) -> None:
    sync = make(hass, pfm, lib)
    await run(sync)
    pfm.stations = [station("BBB222")]
    lib.available = False
    for _ in range(5):
        result = await run(sync)
        assert result.status is SyncStatus.MUSIC_ASSISTANT_UNAVAILABLE
    lib.available = True
    state = await sync.async_get_state()
    assert state.stations["AAA111"].missing_count == 0
    assert "BBB222" not in state.stations


async def test_auth_error_is_reported(hass, pfm, lib) -> None:
    async def boom(*_: Any) -> None:
        raise MusicAssistantAuthError("nope")

    lib.hook = boom
    result = await run(make(hass, pfm, lib))
    assert result.status is SyncStatus.AUTH_FAILED


async def test_failed_add_is_retried_next_sync(hass, pfm, lib) -> None:
    sync = make(hass, pfm, lib)
    lib.fail_upsert.add(url("AAA111"))
    result = await run(sync)
    assert result.status is SyncStatus.PARTIAL and result.failed == 1
    assert not lib.radios
    entry = (await sync.async_get_state()).stations["AAA111"]
    assert not entry.managed_by_integration
    lib.fail_upsert.clear()
    result = await run(sync)
    assert result.added == 1
    assert (await sync.async_get_state()).stations["AAA111"].managed_by_integration


async def test_failed_remove_is_retried_next_sync(hass, pfm, lib) -> None:
    sync = make(hass, pfm, lib)
    await run(sync)
    lid = lib.by_url(url("AAA111"))[0]
    lib.fail_remove.add(lid)
    pfm.stations = [station("BBB222")]
    for _ in range(3):
        await run(sync)
    assert lib.by_url(url("AAA111"))
    entry = (await sync.async_get_state()).stations["AAA111"]
    assert entry.managed_by_integration and entry.pending == PENDING_REMOVE
    lib.fail_remove.clear()
    result = await run(sync)
    assert result.removed == 1
    assert not lib.by_url(url("AAA111"))


async def test_unrelated_and_foreign_radios_untouched(hass, pfm, lib) -> None:
    other = lib.add_foreign("https://example.com/stream.mp3", "My Radio")
    # Same name as a Piraten.FM station but a different stream: never ours.
    same_name = lib.add_foreign(
        "https://example.com/dop.mp3", "Radio Dop 2 Dop • 97.00 MHz • Gelselaar"
    )
    # A user-added radio with exactly our stream URL: tracked but never managed.
    foreign = lib.add_foreign(url("AAA111"), "User's own entry")
    sync = make(hass, pfm, lib)
    await run(sync)
    pfm.stations = [station("BBB222")]
    for _ in range(5):
        await run(sync)
    assert lib.radios[other][1] == "My Radio"
    assert same_name in lib.radios
    assert lib.radios[foreign] == (url("AAA111"), "User's own entry")
    assert lib.removes == []
    assert all(u != url("AAA111") for u, _ in lib.upserts)
    entry = (await sync.async_get_state()).stations["AAA111"]
    assert not entry.managed_by_integration


async def test_stale_stored_library_id_is_not_trusted(hass, pfm, lib) -> None:
    sync = make(hass, pfm, lib)
    await run(sync)
    lid = lib.by_url(url("AAA111"))[0]
    # The user deleted the radio in MA and an unrelated radio now has that id.
    del lib.radios[lid]
    lib.radios[lid] = ("https://example.com/other.mp3", "Unrelated")
    pfm.stations = [station("BBB222")]
    for _ in range(4):
        await run(sync)
    assert lib.radios[lid] == ("https://example.com/other.mp3", "Unrelated")
    assert lid not in lib.removes


async def test_state_survives_restart(hass, pfm, lib) -> None:
    await run(make(hass, pfm, lib))
    pfm.stations = [station("BBB222")]
    await run(make(hass, pfm, lib))
    await run(make(hass, pfm, lib))
    restarted = make(hass, pfm, lib)
    state = await restarted.async_get_state()
    assert state.stations["AAA111"].missing_count == 2
    assert state.stations["AAA111"].managed_by_integration
    assert state.last_successful_sync is not None
    result = await run(restarted)
    assert result.removed == 1


async def test_interrupted_add_is_claimed_after_restart(hass, pfm, lib) -> None:
    """MA added the radio but HA stopped before the result was recorded."""

    async def add_then_die(op: str, _: str) -> None:
        if op == "upsert":
            lib.hook = None
            await lib.async_upsert_radio(url("AAA111"), "Radio Dop 2 Dop")
            raise asyncio.CancelledError

    lib.hook = add_then_die
    with pytest.raises(asyncio.CancelledError):
        await make(hass, pfm, lib).async_sync(OPTS)
    restarted = make(hass, pfm, lib)
    assert (await restarted.async_get_state()).stations["AAA111"].pending == PENDING_ADD
    result = await run(restarted)
    assert result.added == 0
    assert len(lib.by_url(url("AAA111"))) == 1
    entry = (await restarted.async_get_state()).stations["AAA111"]
    assert entry.managed_by_integration and entry.pending is None


async def test_interrupted_remove_completes_after_restart(hass, pfm, lib) -> None:
    sync = make(hass, pfm, lib)
    await run(sync)
    pfm.stations = [station("BBB222")]
    await run(sync)
    await run(sync)

    async def remove_then_die(op: str, lid: str) -> None:
        if op == "remove":
            del lib.radios[lid]
            raise asyncio.CancelledError

    lib.hook = remove_then_die
    with pytest.raises(asyncio.CancelledError):
        await sync.async_sync(OPTS)
    lib.hook = None
    restarted = make(hass, pfm, lib)
    await run(restarted)
    assert "AAA111" not in (await restarted.async_get_state()).stations


async def test_cancelled_add_that_never_reached_ma_is_retried(hass, pfm, lib) -> None:
    sync = make(hass, pfm, lib)
    await run(sync)
    pfm.stations = [*pfm.stations, station("BBB222")]

    async def die(*_: Any) -> None:
        raise asyncio.CancelledError

    lib.hook = die
    with pytest.raises(asyncio.CancelledError):
        await sync.async_sync(OPTS)
    lib.hook = None
    # In-memory state was discarded; the persisted write-ahead marker survives.
    state = await sync.async_get_state()
    assert state.stations["BBB222"].pending == PENDING_ADD
    assert state.stations["AAA111"].missing_count == 0
    result = await run(sync)
    assert result.added == 1
    assert len(lib.by_url(url("BBB222"))) == 1


async def test_concurrent_sync_is_skipped(hass, pfm, lib) -> None:
    sync = make(hass, pfm, lib)
    gate = asyncio.Event()

    async def wait(*_: Any) -> None:
        await gate.wait()

    lib.hook = wait
    first = asyncio.create_task(sync.async_sync(OPTS))
    await asyncio.sleep(0)
    while not sync.is_running:
        await asyncio.sleep(0)
    assert await sync.async_sync(OPTS) is None
    lib.hook = None
    gate.set()
    result = await first
    assert result is not None and result.added == 1
    assert len(lib.upserts) == 1


async def test_unplayable_stream_is_deferred_not_marked_offline(hass, pfm, lib) -> None:
    sync = make(hass, pfm, lib)
    pfm.probe_ok = False
    result = await run(sync)
    assert result.deferred == 1 and result.status is SyncStatus.SUCCESS
    assert not lib.radios
    assert (await sync.async_get_state()).stations["AAA111"].missing_count == 0
    pfm.probe_ok = True
    assert (await run(sync)).added == 1


async def test_remove_all_managed_only_removes_ours(hass, pfm, lib) -> None:
    foreign = lib.add_foreign(url("BBB222"), "User radio")
    other = lib.add_foreign("https://example.com/x.mp3", "Other")
    pfm.stations = [station("AAA111"), station("BBB222")]
    sync = make(hass, pfm, lib)
    await run(sync)
    result = await sync.async_remove_all_managed()
    assert result.removed == 1
    assert set(lib.radios) == {foreign, other}


async def test_new_station_gets_cover(hass, pfm, lib) -> None:
    await run(make(hass, pfm, lib))
    assert lib.covers[url("AAA111")] == COVER_URL


async def test_existing_station_without_cover_is_updated_once(hass, pfm, lib, hass_storage) -> None:
    sync = make(hass, pfm, lib)
    await run(sync)
    # Simulate a station synced by a version without covers.
    (await sync.async_get_state()).stations["AAA111"].cover_url = None
    lib.covers.clear()
    result = await run(sync)
    assert result.updated == 1
    assert lib.covers[url("AAA111")] == COVER_URL
    assert (await run(sync)).updated == 0


async def test_unmanaged_radio_gets_no_cover(hass, pfm, lib) -> None:
    lib.add_foreign(url("AAA111"), "User's own entry")
    await run(make(hass, pfm, lib))
    assert url("AAA111") not in lib.covers


async def test_loads_state_from_minor_version_1(hass, pfm, lib, hass_storage) -> None:
    hass_storage["piratenfm.entry"] = {
        "version": 1,
        "minor_version": 1,
        "key": "piratenfm.entry",
        "data": {
            "stations": {
                "AAA111": {
                    "stream_url": url("AAA111"),
                    "music_assistant_library_id": None,
                    "display_name": "Radio Dop 2 Dop • 97.00 MHz • Gelselaar",
                    "managed_by_integration": True,
                }
            },
            "last_successful_sync": None,
        },
    }
    lib.radios["7"] = (url("AAA111"), "Radio Dop 2 Dop • 97.00 MHz • Gelselaar")
    sync = make(hass, pfm, lib)
    assert (await sync.async_get_state()).stations["AAA111"].cover_url is None
    result = await run(sync)
    assert result.updated == 1 and result.added == 0
    assert lib.covers[url("AAA111")] == COVER_URL
    await hass.async_block_till_done()
    assert hass_storage["piratenfm.entry"]["minor_version"] == 2
