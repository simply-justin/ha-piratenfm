"""Base entity for Piraten.FM."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PiratenFmCoordinator


class PiratenFmEntity(CoordinatorEntity[PiratenFmCoordinator]):
    """Entity attached to the per-entry Piraten.FM service device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PiratenFmCoordinator, description: EntityDescription) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.entity_description = description
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Piraten.FM",
            manufacturer="Piraten.FM (unofficial integration)",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://piraten.fm",
        )
