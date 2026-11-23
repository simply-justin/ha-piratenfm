"""End-to-end setup: entities, button, switches, cleanup service, diagnostics."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.piratenfm.const import (
    CONF_AUTO_REMOVE,
    CONF_AUTO_SYNC,
    CONF_MA_TOKEN,
    CONF_MA_URL,
    DEFAULT_OPTIONS,
    DOMAIN,
)
from custom_components.piratenfm.diagnostics import async_get_config_entry_diagnostics
from custom_components.piratenfm.music_assistant import MusicAssistantAuthError

from .fakes import FakeLibrary, FakePiratenFm, station, url


@pytest.fixture
def lib() -> FakeLibrary:
    return FakeLibrary()


@pytest.fixture
def pfm() -> FakePiratenFm:
    return FakePiratenFm([station("AAA111", "Verzet Radio", "94.30 MHz", "Vriezenveen")])


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="server-1",
        data={CONF_MA_URL: "http://ma:8095", CONF_MA_TOKEN: "super-secret"},
        options=DEFAULT_OPTIONS,
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture(autouse=True)
def patched(lib: FakeLibrary, pfm: FakePiratenFm) -> Iterator[None]:
    with (
        patch("custom_components.piratenfm.async_connect", lambda *_: lib.connect()),
        patch("custom_components.piratenfm.PiratenFmClient", return_value=pfm),
    ):
        yield


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def eid(hass: HomeAssistant, platform: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{key}")
    assert entity_id, key
    return entity_id


async def test_setup_syncs_and_creates_entities(hass, entry, lib) -> None:
    await setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert lib.radios[lib.by_url(url("AAA111"))[0]][1] == "Verzet Radio • 94.30 MHz • Vriezenveen"

    uid = entry.entry_id
    active = hass.states.get(eid(hass, "sensor", f"{uid}_active_stations"))
    assert active.state == "1"
    assert active.attributes["stations"][0]["id"] == "AAA111"
    assert hass.states.get(eid(hass, "sensor", f"{uid}_managed_stations")).state == "1"
    assert hass.states.get(eid(hass, "sensor", f"{uid}_last_sync_status")).state == "success"
    assert hass.states.get(eid(hass, "sensor", f"{uid}_last_successful_sync")).state != "unknown"
    assert hass.states.get(eid(hass, "switch", f"{uid}_{CONF_AUTO_SYNC}")).state == "on"


async def test_ma_down_at_startup_still_loads(hass, entry, lib) -> None:
    lib.available = False
    await setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    status = hass.states.get(eid(hass, "sensor", f"{entry.entry_id}_last_sync_status"))
    assert status.state == "music_assistant_unavailable"


async def test_sync_button(hass, entry, lib, pfm) -> None:
    await setup(hass, entry)
    pfm.stations = [*pfm.stations, station("BBB222")]
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": eid(hass, "button", f"{entry.entry_id}_sync_now")},
        blocking=True,
    )
    assert lib.by_url(url("BBB222"))


async def test_auto_sync_off_skips_startup_sync(hass, entry, lib) -> None:
    hass.config_entries.async_update_entry(
        entry, options={**DEFAULT_OPTIONS, CONF_AUTO_SYNC: False}
    )
    await setup(hass, entry)
    assert not lib.radios


async def test_switch_updates_options(hass, entry) -> None:
    await setup(hass, entry)
    switch = eid(hass, "switch", f"{entry.entry_id}_{CONF_AUTO_REMOVE}")
    await hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
    await hass.async_block_till_done()
    assert entry.options[CONF_AUTO_REMOVE] is False
    assert hass.states.get(switch).state == "off"


async def test_remove_managed_stations_service(hass, entry, lib) -> None:
    other = lib.add_foreign("https://example.com/x.mp3", "Other")
    await setup(hass, entry)
    response = await hass.services.async_call(
        DOMAIN,
        "remove_managed_stations",
        {"config_entry_id": entry.entry_id},
        blocking=True,
        return_response=True,
    )
    assert response == {"status": "success", "removed": 1, "failed": 0}
    assert set(lib.radios) == {other}


async def test_service_rejects_unknown_entry(hass, entry) -> None:
    await setup(hass, entry)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "remove_managed_stations", {"config_entry_id": "nope"}, blocking=True
        )


async def test_auth_failure_starts_reauth(hass, entry, lib) -> None:
    async def reject(*_):
        raise MusicAssistantAuthError("expired")

    lib.hook = reject
    await setup(hass, entry)
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_diagnostics_redact_connection(hass, entry) -> None:
    await setup(hass, entry)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = str(diag)
    assert "super-secret" not in text and "http://ma:8095" not in text
    assert "AAA111" in diag["state"]["stations"]


async def test_unload_and_remove_deletes_state(hass, entry, hass_storage) -> None:
    await setup(hass, entry)
    await hass.async_block_till_done()
    assert f"{DOMAIN}.{entry.entry_id}" in hass_storage
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert f"{DOMAIN}.{entry.entry_id}" not in hass_storage
