"""Client for the public Piraten.FM station API.

Everything returned by Piraten.FM is treated as untrusted input: station IDs are
validated before they are ever embedded in a URL, and text fields are normalized.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import re
from typing import Any

import aiohttp

from .const import LOGGER

BASE_URL = "https://piraten.fm"
STATIONS_URL = f"{BASE_URL}/stations/"
STREAM_URL_TEMPLATE = BASE_URL + "/stations/{station_id}/listen/mp3"

# Observed IDs are 6 upper-case alphanumerics (e.g. "F9O5Z8"); allow a little slack
# but never anything that could alter the URL path.
STATION_ID_RE = re.compile(r"^[A-Za-z0-9]{1,32}$")
STREAM_URL_RE = re.compile(r"^https://piraten\.fm/stations/([A-Za-z0-9]{1,32})/listen/mp3$")

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)
PROBE_TIMEOUT = aiohttp.ClientTimeout(total=10)
PROBE_BYTES = 4096
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 2.0
MAX_TEXT_LENGTH = 200


class PiratenFmError(Exception):
    """Piraten.FM could not be queried successfully."""


class PiratenFmInvalidResponse(PiratenFmError):
    """Piraten.FM answered with something that is not a valid station list."""


@dataclass(frozen=True, slots=True)
class Station:
    """A validated, normalized Piraten.FM station."""

    station_id: str
    name: str | None
    frequency: str | None
    location: str | None
    listeners: int | None
    now_playing: str | None

    @property
    def stream_url(self) -> str:
        """Return the direct MP3 stream URL."""
        return stream_url(self.station_id)


def is_valid_station_id(value: object) -> bool:
    """Return True if value is a station ID that is safe to put in a URL."""
    return isinstance(value, str) and STATION_ID_RE.fullmatch(value) is not None


def stream_url(station_id: str) -> str:
    """Build the stream URL for a station, refusing unsafe IDs."""
    if not is_valid_station_id(station_id):
        raise ValueError(f"Invalid Piraten.FM station id: {station_id!r}")
    return STREAM_URL_TEMPLATE.format(station_id=station_id)


def station_id_from_stream_url(url: str) -> str | None:
    """Return the station ID if url is exactly a Piraten.FM MP3 stream URL."""
    match = STREAM_URL_RE.fullmatch(url)
    return match.group(1) if match else None


def _clean_text(value: object) -> str | None:
    # The live API returns e.g. "Gelselaar\r", so strip and collapse whitespace.
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())[:MAX_TEXT_LENGTH]
    return cleaned or None


def _clean_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _clean_now_playing(value: object) -> str | None:
    if isinstance(value, dict):
        # Schema of a non-null nowPlaying has not been observed; accept common shapes.
        artist = _clean_text(value.get("artist"))
        title = _clean_text(value.get("title"))
        return " - ".join(part for part in (artist, title) if part) or None
    return _clean_text(value)


def parse_stations(payload: Any) -> list[Station]:
    """Validate a /stations/ payload.

    Raises PiratenFmInvalidResponse when the payload as a whole cannot be trusted.
    Entries without a valid ID are dropped (they can never map to a stream URL).
    """
    if not isinstance(payload, list):
        raise PiratenFmInvalidResponse("Station list is not a JSON array")

    stations: dict[str, Station] = {}
    invalid = 0
    for raw in payload:
        if not isinstance(raw, dict) or not is_valid_station_id(raw.get("id")):
            invalid += 1
            continue
        station = Station(
            station_id=raw["id"],
            name=_clean_text(raw.get("name")),
            frequency=_clean_text(raw.get("frequency")),
            location=_clean_text(raw.get("location")),
            listeners=_clean_int(raw.get("listeners")),
            now_playing=_clean_now_playing(raw.get("nowPlaying")),
        )
        stations.setdefault(station.station_id, station)

    # If most entries are garbage, the dropped ones may be live stations we'd
    # otherwise count as missing; refuse the whole response instead.
    if invalid and invalid * 2 >= len(payload):
        raise PiratenFmInvalidResponse(f"{invalid} of {len(payload)} stations are invalid")
    if invalid:
        LOGGER.warning("Ignored %s invalid station entries from Piraten.FM", invalid)
    return list(stations.values())


class PiratenFmClient:
    """Fetch stations from Piraten.FM using Home Assistant's shared HTTP session."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialize the client."""
        self._session = session

    async def async_get_stations(self) -> list[Station]:
        """Return all currently broadcasting stations, retrying transient errors.

        Invalid payloads are not retried: a broken response is not a network blip.
        """
        attempt = 1
        while True:
            try:
                return parse_stations(await self._fetch_json())
            except PiratenFmInvalidResponse:
                raise
            except (aiohttp.ClientError, TimeoutError, PiratenFmError) as err:
                if attempt >= MAX_ATTEMPTS:
                    raise PiratenFmError(f"Piraten.FM unavailable: {err}") from err
                delay = BACKOFF_BASE_SECONDS * 2 ** (attempt - 1)
                LOGGER.debug("Piraten.FM attempt %s failed (%s), retry in %ss", attempt, err, delay)
                await asyncio.sleep(delay)
                attempt += 1

    async def _fetch_json(self) -> Any:
        async with self._session.get(
            STATIONS_URL,
            timeout=REQUEST_TIMEOUT,
            headers={"Accept": "application/json"},
            allow_redirects=False,
        ) as resp:
            if resp.status != 200:
                raise PiratenFmError(f"HTTP {resp.status}")
            try:
                return await resp.json(content_type=None)
            except ValueError as err:
                raise PiratenFmInvalidResponse("Response is not valid JSON") from err

    async def async_probe_stream(self, station_id: str) -> bool:
        """Cheaply check that a stream answers with audio, reading at most 4 KiB."""
        try:
            async with self._session.get(
                stream_url(station_id),
                timeout=PROBE_TIMEOUT,
                headers={"Range": f"bytes=0-{PROBE_BYTES - 1}"},
                allow_redirects=False,
            ) as resp:
                if resp.status not in (200, 206):
                    return False
                if not resp.content_type.startswith("audio/"):
                    return False
                return bool(await resp.content.read(PROBE_BYTES))
        except (aiohttp.ClientError, TimeoutError) as err:
            LOGGER.debug("Stream probe for %s failed: %s", station_id, err)
            return False
