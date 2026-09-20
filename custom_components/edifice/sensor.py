"""Sensor platform for the Edifice ENT integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_HOMEWORK, ATTR_NEXT_DUE, DOMAIN
from .coordinator import EdificeConfigEntry, EdificeCoordinator

# The coordinator serialises access, and the sensor only reads from it.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EdificeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the homework sensor for one ENT account."""
    async_add_entities([EdificeHomeworkSensor(entry.runtime_data)])


class EdificeHomeworkSensor(CoordinatorEntity[EdificeCoordinator], SensorEntity):
    """How many homework items are due from today onwards, with the list as attributes."""

    _attr_has_entity_name = True
    _attr_translation_key = "homework"
    _attr_icon = "mdi:notebook-edit-outline"

    # The list is the bulk of the state and changes with every teacher edit. Keeping it
    # out of the recorder stops the database growing by a few KB per change, while the
    # count and the next due date -- what history graphs want -- are still recorded.
    _unrecorded_attributes = frozenset({ATTR_HOMEWORK})

    def __init__(self, coordinator: EdificeCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_homework"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Edifice",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.upcoming)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        upcoming = self.coordinator.data.upcoming
        return {
            ATTR_NEXT_DUE: upcoming[0].date.isoformat() if upcoming else None,
            ATTR_HOMEWORK: [item.as_dict() for item in upcoming],
        }
