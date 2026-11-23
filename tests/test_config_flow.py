"""Config, reauth, reconfigure and options flows."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import asynccontextmanager
from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.piratenfm.const import (
    CONF_MA_TOKEN,
    CONF_MA_URL,
    CONF_MISSING_THRESHOLD,
    CONF_SCAN_INTERVAL,
    DEFAULT_OPTIONS,
    DOMAIN,
)
from custom_components.piratenfm.music_assistant import (
    MusicAssistantAuthError,
    MusicAssistantUnavailable,
)

USER_INPUT = {CONF_MA_URL: "http://ma.local:8095", CONF_MA_TOKEN: "secret"}


class _Lib:
    def __init__(self, server_id: str) -> None:
        self.server_id = server_id


@pytest.fixture
def connect() -> Iterator[dict[str, object]]:
    """Control what connecting to MA does: {'error': exc | None, 'server_id': str}."""
    behaviour: dict[str, object] = {"error": None, "server_id": "server-1"}

    @asynccontextmanager
    async def fake(_session, _url, _token):
        if behaviour["error"]:
            raise behaviour["error"]  # type: ignore[misc]
        yield _Lib(behaviour["server_id"])  # type: ignore[arg-type]

    with (
        patch("custom_components.piratenfm.config_flow.async_connect", fake),
        patch("custom_components.piratenfm.async_setup_entry", return_value=True),
    ):
        yield behaviour


async def test_user_flow_creates_entry_with_defaults(hass: HomeAssistant, connect) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == USER_INPUT
    assert result["options"] == DEFAULT_OPTIONS
    assert result["result"].unique_id == "server-1"


async def test_user_flow_prefills_url_from_music_assistant(hass: HomeAssistant, connect) -> None:
    MockConfigEntry(domain="music_assistant", data={"url": "http://mass:8095"}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    schema = result["data_schema"].schema
    default = next(k for k in schema if k == CONF_MA_URL).default()
    assert default == "http://mass:8095"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (MusicAssistantUnavailable("x"), {"base": "cannot_connect"}),
        (MusicAssistantAuthError("x"), {"base": "invalid_auth"}),
    ],
)
async def test_user_flow_errors_then_recovers(hass, connect, error, expected) -> None:
    connect["error"] = error
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["errors"] == expected
    connect["error"] = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_invalid_url(hass: HomeAssistant, connect) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MA_URL: "file:///etc/passwd"}
    )
    assert result["errors"] == {CONF_MA_URL: "invalid_url"}


async def test_duplicate_server_aborts(hass: HomeAssistant, connect) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id="server-1", data=USER_INPUT).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_token(hass: HomeAssistant, connect) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="server-1", data=USER_INPUT)
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    connect["error"] = MusicAssistantAuthError("x")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MA_TOKEN: "bad"}
    )
    assert result["errors"] == {"base": "invalid_auth"}
    connect["error"] = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MA_TOKEN: "new"}
    )
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_MA_TOKEN] == "new"


async def test_reconfigure(hass: HomeAssistant, connect) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="server-1", data=USER_INPUT)
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    new = {CONF_MA_URL: "http://other:8095", CONF_MA_TOKEN: "t"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], new)
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == new


async def test_reconfigure_rejects_other_server(hass: HomeAssistant, connect) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="server-1", data=USER_INPUT)
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    connect["server_id"] = "server-2"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["reason"] == "wrong_server"


async def test_options_flow(hass: HomeAssistant, connect) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT, options=DEFAULT_OPTIONS)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    new = {**DEFAULT_OPTIONS, CONF_SCAN_INTERVAL: 600.0, CONF_MISSING_THRESHOLD: 5.0}
    result = await hass.config_entries.options.async_configure(result["flow_id"], new)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SCAN_INTERVAL] == 600
    assert isinstance(entry.options[CONF_MISSING_THRESHOLD], int)
