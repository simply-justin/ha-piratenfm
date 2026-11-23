"""Piraten.FM client: parsing, validation, retries and stream probing."""

from __future__ import annotations

from unittest.mock import patch

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.piratenfm.piratenfm import (
    STATIONS_URL,
    PiratenFmClient,
    PiratenFmError,
    PiratenFmInvalidResponse,
    parse_stations,
    station_id_from_stream_url,
    stream_url,
)

# Shape captured from the live API on 2026-11-23 (phone numbers replaced).
LIVE_SAMPLE = [
    {
        "id": "J4A2X9",
        "frequency": "97.00 MHz",
        "name": "Radio Dop 2 Dop",
        "location": "Gelselaar\r",
        "phoneNumber": "+31600000000",
        "listeners": 216,
        "nowPlaying": None,
    },
    {
        "id": "F9O5Z8",
        "frequency": "94.30 MHz",
        "name": "Verzet Radio",
        "location": "Vriezenveen\r",
        "phoneNumber": "+31600000001",
        "listeners": 126,
        "nowPlaying": None,
    },
]


def test_parse_live_sample() -> None:
    stations = parse_stations(LIVE_SAMPLE)
    assert [s.station_id for s in stations] == ["J4A2X9", "F9O5Z8"]
    first = stations[0]
    assert first.location == "Gelselaar"  # trailing \r stripped
    assert first.listeners == 216
    assert first.stream_url == "https://piraten.fm/stations/J4A2X9/listen/mp3"
    assert not hasattr(first, "phone_number")  # not collected


def test_missing_and_invalid_fields_are_normalized() -> None:
    [s] = parse_stations(
        [{"id": "ABC123", "name": 5, "listeners": -1, "nowPlaying": {"artist": "A", "title": "T"}}]
    )
    assert s.name is None and s.frequency is None and s.location is None
    assert s.listeners is None
    assert s.now_playing == "A - T"


@pytest.mark.parametrize(
    "bad_id", ["../admin", "ABC/123", "", None, 42, "a" * 33, "ABC?x=1", "http://x"]
)
def test_unsafe_ids_are_dropped(bad_id: object) -> None:
    payload = [{"id": bad_id, "name": "x"}, *LIVE_SAMPLE, {"id": "ZZZ999", "name": "ok"}]
    assert {s.station_id for s in parse_stations(payload)} == {"J4A2X9", "F9O5Z8", "ZZZ999"}


def test_mostly_invalid_payload_is_rejected() -> None:
    with pytest.raises(PiratenFmInvalidResponse):
        parse_stations([{"id": "../x"}, {"nope": 1}, LIVE_SAMPLE[0]])


@pytest.mark.parametrize("payload", [{}, "x", None, {"stations": []}])
def test_non_list_payload_is_rejected(payload: object) -> None:
    with pytest.raises(PiratenFmInvalidResponse):
        parse_stations(payload)


def test_duplicate_ids_are_collapsed() -> None:
    assert len(parse_stations([LIVE_SAMPLE[0], LIVE_SAMPLE[0]])) == 1


def test_stream_url_round_trip_and_guard() -> None:
    assert station_id_from_stream_url(stream_url("F9O5Z8")) == "F9O5Z8"
    assert station_id_from_stream_url("https://piraten.fm/stations/F9O5Z8/listen/aac") is None
    assert station_id_from_stream_url("http://piraten.fm/stations/F9O5Z8/listen/mp3") is None
    with pytest.raises(ValueError):
        stream_url("../../etc")


async def test_fetch_success(hass, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(STATIONS_URL, json=LIVE_SAMPLE)
    client = PiratenFmClient(async_get_clientsession(hass))
    assert len(await client.async_get_stations()) == 2


async def test_fetch_retries_then_fails(hass, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(STATIONS_URL, status=503)
    client = PiratenFmClient(async_get_clientsession(hass))
    with (
        patch("custom_components.piratenfm.piratenfm.asyncio.sleep") as sleep,
        pytest.raises(PiratenFmError),
    ):
        await client.async_get_stations()
    assert aioclient_mock.call_count == 3
    assert [c.args[0] for c in sleep.call_args_list] == [2.0, 4.0]


async def test_fetch_timeout_is_retried(hass, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(STATIONS_URL, exc=TimeoutError)
    client = PiratenFmClient(async_get_clientsession(hass))
    with (
        patch("custom_components.piratenfm.piratenfm.asyncio.sleep"),
        pytest.raises(PiratenFmError),
    ):
        await client.async_get_stations()
    assert aioclient_mock.call_count == 3


async def test_malformed_json_is_not_retried(hass, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(STATIONS_URL, text="<html>oops</html>")
    client = PiratenFmClient(async_get_clientsession(hass))
    with pytest.raises(PiratenFmInvalidResponse):
        await client.async_get_stations()
    assert aioclient_mock.call_count == 1


@pytest.mark.parametrize(
    ("status", "content_type", "body", "expected"),
    [
        (206, "audio/mpeg", b"\xff\xfb" * 10, True),
        (200, "audio/mpeg", b"\xff\xfb", True),
        (404, "text/html", b"nope", False),
        (200, "text/html", b"<html>", False),
        (206, "audio/mpeg", b"", False),
    ],
)
async def test_probe_stream(
    hass, aioclient_mock: AiohttpClientMocker, status, content_type, body, expected
) -> None:
    aioclient_mock.get(
        stream_url("J4A2X9"), status=status, content=body, headers={"Content-Type": content_type}
    )
    client = PiratenFmClient(async_get_clientsession(hass))
    assert await client.async_probe_stream("J4A2X9") is expected
    assert aioclient_mock.mock_calls[0][3]["Range"] == "bytes=0-4095"


async def test_probe_network_error_is_false(hass, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(stream_url("J4A2X9"), exc=aiohttp.ClientError)
    assert not await PiratenFmClient(async_get_clientsession(hass)).async_probe_stream("J4A2X9")
