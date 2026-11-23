"""Deterministic fakes for Piraten.FM and Music Assistant."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from custom_components.piratenfm.music_assistant import (
    LibraryRadio,
    MusicAssistantCommandError,
    MusicAssistantUnavailable,
)
from custom_components.piratenfm.piratenfm import PiratenFmError, Station, stream_url


def station(sid: str, name: str = "", freq: str = "97.00 MHz", loc: str = "Twente") -> Station:
    return Station(sid, name or f"Radio {sid}", freq, loc, 10, None)


class FakePiratenFm:
    def __init__(self, stations: list[Station] | None = None) -> None:
        self.stations: list[Station] | Exception = stations or []
        self.probe_ok = True
        self.probed: list[str] = []

    async def async_get_stations(self) -> list[Station]:
        if isinstance(self.stations, Exception):
            raise self.stations
        return list(self.stations)

    def fail(self) -> None:
        self.stations = PiratenFmError("down")

    async def async_probe_stream(self, station_id: str) -> bool:
        self.probed.append(station_id)
        return self.probe_ok


class FakeLibrary:
    """In-memory MA radio library keyed by library id, matching on stream URL."""

    server_id = "server-1"

    def __init__(self) -> None:
        self.radios: dict[str, tuple[str, str]] = {}  # library_id -> (url, name)
        self._next = 100
        self.available = True
        self.fail_upsert: set[str] = set()  # urls
        self.fail_remove: set[str] = set()  # library ids
        self.upserts: list[tuple[str, str]] = []
        self.covers: dict[str, str | None] = {}  # url -> cover last written
        self.removes: list[str] = []
        self.hook: Any = None  # awaited before each write, for interruption tests

    def add_foreign(self, url: str, name: str) -> str:
        self._next += 1
        self.radios[str(self._next)] = (url, name)
        return str(self._next)

    def by_url(self, url: str) -> list[str]:
        return [lid for lid, (u, _) in self.radios.items() if u == url]

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[FakeLibrary]:
        if not self.available:
            raise MusicAssistantUnavailable("offline")
        yield self

    async def async_piratenfm_radios(self) -> dict[str, list[LibraryRadio]]:
        from custom_components.piratenfm.piratenfm import station_id_from_stream_url

        out: dict[str, list[LibraryRadio]] = {}
        for lid, (url, name) in self.radios.items():
            if sid := station_id_from_stream_url(url):
                out.setdefault(sid, []).append(LibraryRadio(lid, name, url))
        return out

    async def async_upsert_radio(
        self, url: str, name: str, cover_url: str | None = None
    ) -> LibraryRadio:
        if self.hook:
            await self.hook("upsert", url)
        if url in self.fail_upsert:
            raise MusicAssistantCommandError("add failed")
        self.upserts.append((url, name))
        self.covers[url] = cover_url
        if existing := self.by_url(url):
            lid = existing[0]
        else:
            self._next += 1
            lid = str(self._next)
        self.radios[lid] = (url, name)
        return LibraryRadio(lid, name, url)

    async def async_remove_radio(self, library_id: str) -> None:
        if self.hook:
            await self.hook("remove", library_id)
        if library_id in self.fail_remove:
            raise MusicAssistantCommandError("remove failed")
        self.removes.append(library_id)
        del self.radios[library_id]


def url(sid: str) -> str:
    return stream_url(sid)
