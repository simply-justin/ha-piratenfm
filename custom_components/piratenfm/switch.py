"""Switches for Piraten.FM; they edit the config entry options."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_AUTO_REMOVE, CONF_AUTO_SYNC
from .coordinator import PiratenFmConfigEntry
from .entity import PiratenFmEntity

PARALLEL_UPDATES = 0

SWITCHES = (
    SwitchEntityDescription(
        key=CONF_AUTO_SYNC, translation_key=CONF_AUTO_SYNC, entity_category=EntityCategory.CONFIG
    ),
    SwitchEntityDescription(
        key=CONF_AUTO_REMOVE,
        translation_key=CONF_AUTO_REMOVE,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PiratenFmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switches."""
    async_add_entities(PiratenFmOptionSwitch(entry.runtime_data, d) for d in SWITCHES)


class PiratenFmOptionSwitch(PiratenFmEntity, SwitchEntity):
    """A boolean option exposed as switch."""

    @property
    def is_on(self) -> bool:
        """Return the option value."""
        return bool(self.coordinator.options[self.entity_description.key])

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the option."""
        self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the option."""
        self._set(False)

    def _set(self, value: bool) -> None:
        entry = self.coordinator.config_entry
        # Updating options reloads the entry, which applies the new behaviour.
        self.hass.config_entries.async_update_entry(
            entry, options={**self.coordinator.options, self.entity_description.key: value}
        )
