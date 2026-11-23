"""Music Assistant adapter: identity resolution and error mapping."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from music_assistant_client.exceptions import CannotConnect, ConnectionClosed
from music_assistant_models.enums import ImageType, MediaType
from music_assistant_models.errors import AuthenticationFailed, InvalidDataError
from music_assistant_models.media_items import ProviderMapping, Radio
import pytest

from custom_components.piratenfm.music_assistant import (
    PAGE_SIZE,
    MusicAssistantAuthError,
    MusicAssistantCommandError,
    MusicAssistantLibrary,
    MusicAssistantUnavailable,
    async_connect,
)
from custom_components.piratenfm.piratenfm import stream_url


def radio(item_id: str, name: str, url: str, domain: str = "builtin") -> Radio:
    return Radio(
        item_id=item_id,
        provider="library",
        name=name,
        provider_mappings={
            ProviderMapping(item_id=url, provider_domain=domain, provider_instance=domain)
        },
    )


def library(
    radios_pages: list[list[Radio]] | None = None,
) -> tuple[MusicAssistantLibrary, MagicMock]:
    client = MagicMock()
    client.music.get_library_radios = AsyncMock(side_effect=radios_pages or [[]])
    client.music.add_item_to_library = AsyncMock()
    client.music.remove_item_from_library = AsyncMock()
    return MusicAssistantLibrary(client), client


async def test_lists_only_exact_piratenfm_builtin_streams() -> None:
    lib, _ = library(
        [
            [
                radio("1", "Ours", stream_url("ABC123")),
                radio("2", "Name lookalike", "https://example.com/ABC123"),
                radio("3", "Other provider", stream_url("XYZ999"), domain="tunein"),
                radio("4", "Odd path", "https://piraten.fm/stations/ABC123/listen/mp3?x=1"),
            ]
        ]
    )
    found = await lib.async_piratenfm_radios()
    assert list(found) == ["ABC123"]
    assert found["ABC123"][0].library_id == "1"


async def test_paginates() -> None:
    first = [radio(str(i), "r", "https://example.com/x") for i in range(PAGE_SIZE)]
    lib, client = library([first, [radio("x", "Ours", stream_url("ABC123"))]])
    assert "ABC123" in await lib.async_piratenfm_radios()
    assert client.music.get_library_radios.await_count == 2


async def test_upsert_sends_builtin_radio_and_parses_dict() -> None:
    lib, client = library()
    client.music.add_item_to_library.return_value = {"item_id": 42, "name": "N"}
    result = await lib.async_upsert_radio(stream_url("ABC123"), "N")
    assert result.library_id == "42"
    sent, kwargs = client.music.add_item_to_library.call_args
    item = sent[0]
    assert item.provider == "builtin" and item.item_id == stream_url("ABC123")
    assert kwargs == {"overwrite_existing": True}
    assert not item.metadata.images


async def test_upsert_sends_cover_as_remote_thumb() -> None:
    lib, client = library()
    client.music.add_item_to_library.return_value = {"item_id": 42, "name": "N"}
    await lib.async_upsert_radio(stream_url("ABC123"), "N", "https://piraten.fm/icons/Icon-512.png")
    [image] = client.music.add_item_to_library.call_args.args[0].metadata.images
    assert image.type is ImageType.THUMB
    assert image.path == "https://piraten.fm/icons/Icon-512.png"
    assert image.provider == "builtin" and image.remotely_accessible


async def test_upsert_unexpected_response() -> None:
    lib, client = library()
    client.music.add_item_to_library.return_value = None
    with pytest.raises(MusicAssistantCommandError):
        await lib.async_upsert_radio(stream_url("ABC123"), "N")


async def test_remove_uses_library_id() -> None:
    lib, client = library()
    await lib.async_remove_radio("7")
    client.music.remove_item_from_library.assert_awaited_once_with(
        MediaType.RADIO, "7", recursive=False
    )


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (InvalidDataError("x"), MusicAssistantCommandError),
        (AuthenticationFailed("x"), MusicAssistantAuthError),
        (ConnectionClosed("x"), MusicAssistantUnavailable),
        (TimeoutError(), MusicAssistantUnavailable),
    ],
)
async def test_error_mapping(raised: Exception, expected: type[Exception]) -> None:
    lib, client = library()
    client.music.remove_item_from_library.side_effect = raised
    with pytest.raises(expected):
        await lib.async_remove_radio("7")


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (CannotConnect("x"), MusicAssistantUnavailable),
        (AuthenticationFailed("x"), MusicAssistantAuthError),
    ],
)
async def test_connect_errors(raised: Exception, expected: type[Exception]) -> None:
    with patch("custom_components.piratenfm.music_assistant.MusicAssistantClient") as cls:
        cls.return_value.connect = AsyncMock(side_effect=raised)
        cls.return_value.disconnect = AsyncMock()
        with pytest.raises(expected):
            async with async_connect(MagicMock(), "http://ma:8095", "secret"):
                pass
        cls.return_value.disconnect.assert_awaited()


async def test_connect_disconnects_after_use() -> None:
    with patch("custom_components.piratenfm.music_assistant.MusicAssistantClient") as cls:
        cls.return_value.connect = AsyncMock()
        cls.return_value.disconnect = AsyncMock()
        cls.return_value.server_info.server_id = "srv"
        async with async_connect(MagicMock(), "http://ma:8095", "secret") as lib:
            assert lib.server_id == "srv"
        cls.return_value.disconnect.assert_awaited_once()
        assert cls.call_args.kwargs == {"token": "secret"}
