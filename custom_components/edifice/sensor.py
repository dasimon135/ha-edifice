"""Sensor platform for the Edifice ENT integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Child
from .const import ATTR_HOMEWORK, ATTR_NEXT_DUE, ATTR_WORDS
from .coordinator import EdificeConfigEntry, EdificeCoordinator
from .entity import account_device_info, child_device_info

# The coordinator serialises access, and the sensors only read from it.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EdificeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the sensors for one ENT account: what the platform actually offers."""
    coordinator = entry.runtime_data
    data = coordinator.data

    entities: list[SensorEntity] = [EdificeHomeworkSensor(coordinator)]
    entities.extend(
        EdificeUnreadWordsSensor(coordinator, child) for child in data.children if child.child_id in data.schoolbook
    )
    if data.unread_messages is not None:
        entities.append(EdificeUnreadMessagesSensor(coordinator))
    async_add_entities(entities)


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
        self._attr_device_info = account_device_info(entry)

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


class EdificeUnreadWordsSensor(CoordinatorEntity[EdificeCoordinator], SensorEntity):
    """How many words of a child's cahier de liaison this account has not acknowledged.

    The attribute lists the latest words -- title, date, sender, category and whether they
    were acknowledged -- and never their text.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "unread_words"
    _attr_icon = "mdi:message-text-outline"

    # Senders are people: the count is what history needs, the list is not.
    _unrecorded_attributes = frozenset({ATTR_WORDS})

    def __init__(self, coordinator: EdificeCoordinator, child: Child) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._child_id = child.child_id
        self._attr_unique_id = f"{entry.entry_id}_{child.child_id}_unread_words"
        self._attr_device_info = child_device_info(entry, child)

    @property
    def available(self) -> bool:
        return super().available and self._child_id in self.coordinator.data.schoolbook

    @property
    def native_value(self) -> int | None:
        book = self.coordinator.data.schoolbook.get(self._child_id)
        return book.unread if book else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        book = self.coordinator.data.schoolbook.get(self._child_id)
        return {ATTR_WORDS: [word.as_dict() for word in book.words] if book else []}


class EdificeUnreadMessagesSensor(CoordinatorEntity[EdificeCoordinator], SensorEntity):
    """Unread messages in the account's inbox. Only the count is read, never a message."""

    _attr_has_entity_name = True
    _attr_translation_key = "unread_messages"
    _attr_icon = "mdi:email-outline"

    def __init__(self, coordinator: EdificeCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_unread_messages"
        self._attr_device_info = account_device_info(entry)

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.unread_messages is not None

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.unread_messages
