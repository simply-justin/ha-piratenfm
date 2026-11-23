"""Diagnostics for Piraten.FM (connection details are redacted)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_MA_TOKEN, CONF_MA_URL
from .coordinator import PiratenFmConfigEntry

TO_REDACT = {CONF_MA_TOKEN, CONF_MA_URL}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PiratenFmConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    state = await coordinator.synchronizer.async_get_state()
    result = coordinator.data.last_result if coordinator.data else None
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "sync_running": coordinator.synchronizer.is_running,
        "last_result": None if result is None else {**asdict(result), "stations": None},
        "state": state.as_dict(),
    }
