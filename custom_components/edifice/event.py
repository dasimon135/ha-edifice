"""Event platform for the Edifice ENT integration."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Child, Homework, Word
from .const import EVENT_HOMEWORK_ADDED, EVENT_WORD_ADDED
from .coordinator import EdificeConfigEntry, EdificeCoordinator
from .entity import account_device_info, child_device_info

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EdificeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the "new homework" event, and a "new note" event for each child."""
    coordinator = entry.runtime_data
    data = coordinator.data

    entities: list[EventEntity] = [EdificeNewHomeworkEvent(coordinator)]
    entities.extend(
        EdificeNewWordEvent(coordinator, child) for child in data.children if child.child_id in data.schoolbook
    )
    async_add_entities(entities)


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
        self._attr_device_info = account_device_info(entry)

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


class EdificeNewWordEvent(CoordinatorEntity[EdificeCoordinator], EventEntity):
    """Fires once for every word that appears in a child's cahier de liaison.

    The event carries the title, date, sender, category and whether the word was already
    acknowledged -- never its text.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "new_word"
    _attr_icon = "mdi:bell-ring-outline"
    _attr_event_types = [EVENT_WORD_ADDED]

    _unrecorded_attributes = frozenset({"id", "title", "date", "sender", "category", "acknowledged"})

    def __init__(self, coordinator: EdificeCoordinator, child: Child) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._child_id = child.child_id
        self._attr_unique_id = f"{entry.entry_id}_{child.child_id}_new_word"
        self._attr_device_info = child_device_info(entry, child)

    @property
    def available(self) -> bool:
        return super().available and self._child_id in self.coordinator.data.schoolbook

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Same catch-up as the homework event: the first refresh found it before we existed.
        self._announce(self.coordinator.data.new_words.get(self._child_id, []))

    @callback
    def _handle_coordinator_update(self) -> None:
        self._announce(self.coordinator.data.new_words.get(self._child_id, []))
        super()._handle_coordinator_update()

    @callback
    def _announce(self, words: list[Word]) -> None:
        for word in words:
            self._trigger_event(EVENT_WORD_ADDED, word.as_dict())
            self.async_write_ha_state()
