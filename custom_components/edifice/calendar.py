"""Calendar platform for the Edifice ENT integration."""

from __future__ import annotations

import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import Homework
from .coordinator import EdificeConfigEntry, EdificeCoordinator
from .entity import account_device_info

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EdificeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the homework calendar for one ENT account."""
    async_add_entities([EdificeHomeworkCalendar(entry.runtime_data)])


def _to_event(homework: Homework) -> CalendarEvent:
    """One homework item is an all-day event on the day it is due.

    The official mobile app groups the diary under "Pour <date>", so the date of an
    entry is the day the work is for, not the day it was set.
    """
    return CalendarEvent(
        start=homework.date,
        end=homework.date + datetime.timedelta(days=1),
        summary=homework.subject or homework.diary_title,
        description=homework.content_text or None,
        uid=homework.entry_id or None,
    )


class EdificeHomeworkCalendar(CoordinatorEntity[EdificeCoordinator], CalendarEntity):
    """The whole diary as a calendar, past weeks included."""

    _attr_has_entity_name = True
    _attr_translation_key = "homework"

    def __init__(self, coordinator: EdificeCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_calendar"
        self._attr_device_info = account_device_info(entry)

    @property
    def event(self) -> CalendarEvent | None:
        """Today's first homework if there is any, otherwise the next one."""
        today = dt_util.now().date()
        for homework in self.coordinator.data.homework:
            if homework.date >= today:
                return _to_event(homework)
        return None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> list[CalendarEvent]:
        """Every homework item overlapping the requested window."""
        events = (_to_event(homework) for homework in self.coordinator.data.homework)
        return [
            event
            for event in events
            if event.start_datetime_local < end_date and event.end_datetime_local > start_date
        ]
