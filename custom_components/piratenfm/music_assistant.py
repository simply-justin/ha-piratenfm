"""Adapter around the official Music Assistant client.

Only the commands verified against the Music Assistant server source are used:

* ``music/radios/library_items`` - list library radios (paginated)
* ``music/library/add_item``     - add, or with ``overwrite_existing`` update, a radio
* ``music/library/remove_item``  - remove a library radio

Radios are added through MA's ``builtin`` provider, whose item ID *is* the stream URL.
That gives an identity that does not depend on names: a library radio belongs to a
Piraten.FM station only if its builtin provider mapping is exactly that station's URL.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import aiohttp
from music_assistant_client import MusicAssistantClient
from music_assistant_client.exceptions import MusicAssistantClientException
from music_assistant_models.enums import ImageType, MediaType
from music_assistant_models.errors import (
    AuthenticationFailed,
    AuthenticationRequired,
    InsufficientPermissions,
    InvalidToken,
    MusicAssistantError,
)
from music_assistant_models.media_items import MediaItemImage, ProviderMapping, Radio
from music_assistant_models.unique_list import UniqueList

from .piratenfm import station_id_from_stream_url

BUILTIN_PROVIDER = "builtin"
CONNECT_TIMEOUT = 20
COMMAND_TIMEOUT = 60
PAGE_SIZE = 500

_AUTH_ERRORS = (AuthenticationFailed, AuthenticationRequired, InvalidToken, InsufficientPermissions)


class MusicAssistantUnavailable(Exception):
    """Music Assistant is not reachable (or the connection dropped)."""


class MusicAssistantAuthError(Exception):
    """The configured token was rejected or lacks permissions."""


class MusicAssistantCommandError(Exception):
    """A single library command failed; the connection itself is still usable."""


@dataclass(frozen=True, slots=True)
class LibraryRadio:
    """A Music Assistant library radio that points at a Piraten.FM stream."""

    library_id: str
    name: str
    stream_url: str


class MusicAssistantLibrary:
    """Radio library operations on a connected client."""

    def __init__(self, client: MusicAssistantClient) -> None:
        """Wrap a connected client."""
        self._client = client

    @property
    def server_id(self) -> str | None:
        """Return the stable ID of the connected server."""
        info = self._client.server_info
        return info.server_id if info else None

    async def async_piratenfm_radios(self) -> dict[str, list[LibraryRadio]]:
        """Return library radios with a Piraten.FM builtin stream, keyed by station ID."""
        found: dict[str, list[LibraryRadio]] = {}
        offset = 0
        while True:
            page = await self._call(
                self._client.music.get_library_radios(limit=PAGE_SIZE, offset=offset)
            )
            for radio in page:
                for mapping in radio.provider_mappings:
                    if mapping.provider_domain != BUILTIN_PROVIDER:
                        continue
                    if station_id := station_id_from_stream_url(mapping.item_id):
                        found.setdefault(station_id, []).append(
                            LibraryRadio(str(radio.item_id), radio.name, mapping.item_id)
                        )
            if len(page) < PAGE_SIZE:
                return found
            offset += PAGE_SIZE

    async def async_upsert_radio(
        self, stream_url: str, name: str, cover_url: str | None = None
    ) -> LibraryRadio:
        """Add the stream as a radio, or update the name and cover of the existing one.

        MA matches the item on its provider mapping, so this never creates a
        duplicate for the same stream URL.
        """
        radio = Radio(
            item_id=stream_url,
            provider=BUILTIN_PROVIDER,
            name=name,
            provider_mappings={
                ProviderMapping(
                    item_id=stream_url,
                    provider_domain=BUILTIN_PROVIDER,
                    provider_instance=BUILTIN_PROVIDER,
                )
            },
        )
        if cover_url:
            # The builtin provider stores a remote THUMB with the radio itself.
            radio.metadata.images = UniqueList(
                [
                    MediaItemImage(
                        type=ImageType.THUMB,
                        path=cover_url,
                        provider=BUILTIN_PROVIDER,
                        remotely_accessible=True,
                    )
                ]
            )
        result: Any = await self._call(
            self._client.music.add_item_to_library(radio, overwrite_existing=True)
        )
        # The client returns the raw JSON dict despite its type hint.
        if isinstance(result, Mapping) and result.get("item_id") is not None:
            return LibraryRadio(str(result["item_id"]), str(result.get("name", name)), stream_url)
        if isinstance(result, Radio):
            return LibraryRadio(str(result.item_id), result.name, stream_url)
        raise MusicAssistantCommandError("Unexpected add_item response")

    async def async_remove_radio(self, library_id: str) -> None:
        """Remove a library radio by its library ID."""
        await self._call(
            self._client.music.remove_item_from_library(
                MediaType.RADIO, library_id, recursive=False
            )
        )

    async def _call[T](self, awaitable: Awaitable[T]) -> T:
        try:
            async with asyncio.timeout(COMMAND_TIMEOUT):
                return await awaitable
        except _AUTH_ERRORS as err:
            raise MusicAssistantAuthError(str(err)) from err
        except MusicAssistantError as err:
            raise MusicAssistantCommandError(str(err)) from err
        except (MusicAssistantClientException, aiohttp.ClientError, TimeoutError) as err:
            raise MusicAssistantUnavailable(str(err) or type(err).__name__) from err


@asynccontextmanager
async def async_connect(
    session: aiohttp.ClientSession, url: str, token: str | None
) -> AsyncIterator[MusicAssistantLibrary]:
    """Open a short-lived authenticated connection to Music Assistant.

    A connection per sync keeps the integration naturally resilient to MA
    restarts: there is no long-lived socket to babysit.
    """
    client = MusicAssistantClient(url, session, token=token or None)
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT):
            await client.connect()
    except _AUTH_ERRORS as err:
        await client.disconnect()
        raise MusicAssistantAuthError(str(err)) from err
    except (
        MusicAssistantError,
        MusicAssistantClientException,
        aiohttp.ClientError,
        TimeoutError,
    ) as err:
        await client.disconnect()
        raise MusicAssistantUnavailable(str(err) or type(err).__name__) from err
    try:
        yield MusicAssistantLibrary(client)
    finally:
        await client.disconnect()
