"""Data and helpers shared by the Home Assistant tests.

Only the modules that need Home Assistant import this one: it pulls the integration in, so
the pure tests, which run without Home Assistant, never touch it.
"""

from __future__ import annotations

import datetime

from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.edifice.api import Child, Diary, Homework, Word
from custom_components.edifice.const import UPDATE_INTERVAL

DIARY = Diary(diary_id="d1", title="CM1 A")
EMMA = Child(child_id="child-emma", first_name="Emma")
TOM = Child(child_id="child-tom", first_name="Tom")


def make_homework(day: str, subject: str, text: str) -> Homework:
    return Homework(
        date=datetime.date.fromisoformat(day),
        subject=subject,
        content_html=f"<p>{text}</p>",
        content_text=text,
        entry_id=f"{day}-{subject}",
        diary_id=DIARY.diary_id,
        diary_title=DIARY.title,
    )


def sample() -> list[Homework]:
    return [
        make_homework("2026-09-21", "Maths", "Exercices 3 et 4"),
        make_homework("2026-09-22", "Français", "Lire le chapitre 2"),
    ]


def make_word(
    word_id: int,
    day: str = "2026-09-17",
    *,
    title: str | None = None,
    acknowledged: bool = False,
    sender: str = "M. Durand",
    category: str = "NOTE",
) -> Word:
    return Word(
        word_id=word_id,
        title=title or f"Mot {word_id}",
        sent=datetime.datetime.fromisoformat(f"{day}T10:00:00"),
        category=category,
        sender=sender,
        acknowledged=acknowledged,
    )


async def setup_entry(hass, entry) -> bool:
    """Add the entry, set it up, and let everything settle."""
    entry.add_to_hass(hass)
    ok = await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return ok


async def refresh(hass, entry) -> None:
    """Run one refresh now, without waiting for the timer."""
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def tick(hass, freezer) -> None:
    """Move the clock past one update interval and fire the timers."""
    freezer.tick(UPDATE_INTERVAL + datetime.timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
