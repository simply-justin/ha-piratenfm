"""Button for Piraten.FM."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import PiratenFmConfigEntry
from .entity import PiratenFmEntity

PARALLEL_UPDATES = 0

SYNC_NOW = ButtonEntityDescription(key="sync_now", translation_key="sync_now")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PiratenFmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the button."""
    async_add_entities([PiratenFmSyncButton(entry.runtime_data, SYNC_NOW)])


class PiratenFmSyncButton(PiratenFmEntity, ButtonEntity):
    """Run a synchronization right now."""

    async def async_press(self) -> None:
        """Synchronize now (overlapping presses are ignored by the synchronizer)."""
        await self.coordinator.async_refresh()
