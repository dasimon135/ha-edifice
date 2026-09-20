"""Event platform for the Edifice ENT integration."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Homework
from .const import DOMAIN, EVENT_HOMEWORK_ADDED
from .coordinator import EdificeConfigEntry, EdificeCoordinator

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EdificeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the "new homework" event entity for one ENT account."""
    async_add_entities([EdificeNewHomeworkEvent(entry.runtime_data)])


class EdificeNewHomeworkEvent(CoordinatorEntity[EdificeCoordinator], EventEntity):
    """Fires once for every homework entry that appears in the diary."""

    _attr_has_entity_name = True
    _attr_translation_key = "new_homework"
    _attr_icon = "mdi:bell-ring-outline"
    _attr_event_types = [EVENT_HOMEWORK_ADDED]

    # School text has no business sitting in the database: automations read it from the
    # live state, and the recorder does not need to keep it.
    _unrecorded_attributes = frozenset({"date", "subject", "content", "entry_id", "diary"})

    def __init__(self, coordinator: EdificeCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_new_homework"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Edifice",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # The first refresh ran before this entity existed. If a teacher added something
        # while Home Assistant was down, that refresh found it and nobody listened.
        self._announce(self.coordinator.data.new)

    @callback
    def _handle_coordinator_update(self) -> None:
        self._announce(self.coordinator.data.new)
        super()._handle_coordinator_update()

    @callback
    def _announce(self, homework: list[Homework]) -> None:
        # _trigger_event only records the event; the state has to be written for each
        # one, or several arriving together would collapse into the last.
        for item in homework:
            self._trigger_event(EVENT_HOMEWORK_ADDED, item.as_dict())
            self.async_write_ha_state()
