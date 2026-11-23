"""Sensors for Piraten.FM."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import PiratenFmConfigEntry, PiratenFmData
from .entity import PiratenFmEntity
from .sync import SyncStatus

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class PiratenFmSensorDescription(SensorEntityDescription):
    """Describes a Piraten.FM sensor."""

    value_fn: Callable[[PiratenFmData], str | int | float | datetime | None]
    attrs_fn: Callable[[PiratenFmData], dict[str, Any]] | None = None


def _station_attrs(data: PiratenFmData) -> dict[str, Any]:
    return {
        "stations": [
            {
                "id": s.station_id,
                "name": s.name,
                "frequency": s.frequency,
                "location": s.location,
                "listeners": s.listeners,
                "now_playing": s.now_playing,
                "stream_url": s.stream_url,
            }
            for s in data.stations
        ]
    }


def _result_attrs(data: PiratenFmData) -> dict[str, Any]:
    r = data.last_result
    if r is None:
        return {}
    return {
        "added": r.added,
        "updated": r.updated,
        "removed": r.removed,
        "deferred": r.deferred,
        "failed": r.failed,
        "error": r.error,
        "failures": r.failures,
    }


SENSORS: tuple[PiratenFmSensorDescription, ...] = (
    PiratenFmSensorDescription(
        key="active_stations",
        translation_key="active_stations",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: len(d.stations),
        attrs_fn=_station_attrs,
    ),
    PiratenFmSensorDescription(
        key="managed_stations",
        translation_key="managed_stations",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.managed_count,
        attrs_fn=lambda d: {"unmanaged_matching_stations": d.unmanaged_count},
    ),
    PiratenFmSensorDescription(
        key="last_successful_sync",
        translation_key="last_successful_sync",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.last_successful_sync,
    ),
    PiratenFmSensorDescription(
        key="last_sync_status",
        translation_key="last_sync_status",
        device_class=SensorDeviceClass.ENUM,
        options=[s.value for s in SyncStatus],
        value_fn=lambda d: d.last_result.status.value if d.last_result else None,
        attrs_fn=_result_attrs,
    ),
    PiratenFmSensorDescription(
        key="last_sync_duration",
        translation_key="last_sync_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.last_result.duration if d.last_result else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PiratenFmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    async_add_entities(PiratenFmSensor(entry.runtime_data, d) for d in SENSORS)


class PiratenFmSensor(PiratenFmEntity, SensorEntity):
    """A Piraten.FM sensor."""

    entity_description: PiratenFmSensorDescription
    # Station lists change constantly; keep them out of the recorder.
    _unrecorded_attributes = frozenset({"stations", "failures"})

    @property
    def native_value(self) -> str | int | float | datetime | None:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)
