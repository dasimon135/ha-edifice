"""Setup, sensor, calendar, event and failure-handling tests for the Edifice ENT integration."""

from __future__ import annotations

import datetime
import re
from pathlib import Path

import pytest
import yaml
from edifice_test_helpers import DIARY, make_homework, refresh, sample, setup_entry, tick
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_mock_service,
)

from custom_components.edifice.api import (
    EdificeAuthError,
    EdificeError,
    EdificePlatformError,
    EdificeUnavailable,
    Homework,
)
from custom_components.edifice.const import (
    ATTR_HOMEWORK,
    ATTR_NEXT_DUE,
    DOMAIN,
    EVENT_HOMEWORK_ADDED,
    UPCOMING_DAYS,
)
from custom_components.edifice.event import EdificeNewHomeworkEvent
from custom_components.edifice.sensor import EdificeHomeworkSensor

pytestmark = pytest.mark.usefixtures("enable_custom_integrations", "pin_clock")

ENTITY_ID = "sensor.school_emma_homework"
CALENDAR_ID = "calendar.school_emma_homework"
EVENT_ID = "event.school_emma_new_homework"
# -- the sensor ----------------------------------------------------------------------


async def test_sensor_reports_the_upcoming_homework(hass, entry, client_cls, freezer):
    freezer.move_to("2026-09-21T12:00:00+00:00")

    assert await setup_entry(hass, entry)

    state = hass.states.get(ENTITY_ID)
    assert state is not None, "entity id should follow the device name: sensor.<name>_homework"
    assert state.state == "2"
    assert state.attributes[ATTR_NEXT_DUE] == "2026-09-21"
    assert state.attributes[ATTR_HOMEWORK] == [
        {
            "date": "2026-09-21",
            "subject": "Maths",
            "content": "Exercices 3 et 4",
            "entry_id": "2026-09-21-Maths",
            "diary": "CM1 A",
        },
        {
            "date": "2026-09-22",
            "subject": "Français",
            "content": "Lire le chapitre 2",
            "entry_id": "2026-09-22-Français",
            "diary": "CM1 A",
        },
    ]


async def test_sensor_is_zero_and_has_no_next_date_when_nothing_is_due(hass, entry, client_cls):
    client_cls.return_value.get_homework.return_value = []

    assert await setup_entry(hass, entry)

    state = hass.states.get(ENTITY_ID)
    assert state.state == "0"
    assert state.attributes[ATTR_NEXT_DUE] is None
    assert state.attributes[ATTR_HOMEWORK] == []


async def test_sensor_has_a_stable_unique_id(hass, entry, client_cls):
    assert await setup_entry(hass, entry)
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_homework") == ENTITY_ID
    assert registry.async_get_entity_id("calendar", DOMAIN, f"{entry.entry_id}_calendar") == CALENDAR_ID
    assert registry.async_get_entity_id("event", DOMAIN, f"{entry.entry_id}_new_homework") == EVENT_ID


def test_the_homework_list_stays_out_of_the_recorder():
    assert ATTR_HOMEWORK in EdificeHomeworkSensor._unrecorded_attributes
    assert ATTR_NEXT_DUE not in EdificeHomeworkSensor._unrecorded_attributes


def test_announced_school_text_stays_out_of_the_recorder():
    assert {"subject", "content"} <= EdificeNewHomeworkEvent._unrecorded_attributes


# -- what the coordinator asks for ---------------------------------------------------


async def test_it_fetches_the_whole_diary_once_and_reuses_the_diary_list(hass, entry, client_cls):
    assert await setup_entry(hass, entry)

    client_cls.return_value.get_diaries.assert_called_once()
    client_cls.return_value.get_homework.assert_called_once_with(diaries=[DIARY])


async def test_the_sensor_looks_fourteen_days_ahead_and_never_behind(hass, entry, client_cls):
    today = datetime.date(2026, 9, 21)
    edge = today + datetime.timedelta(days=UPCOMING_DAYS)
    client_cls.return_value.get_homework.return_value = [
        make_homework("2026-09-20", "Yesterday", "past"),
        make_homework(today.isoformat(), "Today", "today"),
        make_homework(edge.isoformat(), "Last day", "on the edge"),
        make_homework((edge + datetime.timedelta(days=1)).isoformat(), "Beyond", "too far"),
    ]

    assert await setup_entry(hass, entry)

    state = hass.states.get(ENTITY_ID)
    assert state.state == "2"
    assert [item["subject"] for item in state.attributes[ATTR_HOMEWORK]] == ["Today", "Last day"]


async def test_today_follows_the_home_assistant_timezone(hass, entry, client_cls, freezer):
    """20:00 UTC is already tomorrow in Auckland; the sensor must agree with HA, not the OS."""
    await hass.config.async_set_time_zone("Pacific/Auckland")
    freezer.move_to("2026-09-21T20:00:00+00:00")

    assert await setup_entry(hass, entry)

    state = hass.states.get(ENTITY_ID)
    assert state.state == "1"  # the 21st is already yesterday there
    assert state.attributes[ATTR_NEXT_DUE] == "2026-09-22"


async def test_the_client_is_built_from_the_entry(hass, entry, client_cls):
    assert await setup_entry(hass, entry)
    client_cls.assert_called_once_with(
        base_url="https://ent.example.org", username="parent", password="secret"
    )


# -- failures ------------------------------------------------------------------------


async def test_rejected_credentials_start_reauth_and_are_not_retried(hass, entry, client_cls):
    client_cls.return_value.get_diaries.side_effect = EdificeAuthError("credentials rejected")

    assert not await setup_entry(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]
    assert client_cls.return_value.get_diaries.call_count == 1


@pytest.mark.parametrize("error", [EdificeUnavailable("down"), EdificePlatformError("gone"), EdificeError("odd")])
async def test_other_failures_at_setup_are_retried_later(hass, entry, client_cls, error):
    client_cls.return_value.get_diaries.side_effect = error

    assert not await setup_entry(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)  # no reauth for a network blip


async def test_a_failed_refresh_makes_the_sensor_unavailable_then_it_recovers(hass, entry, client_cls, freezer):
    assert await setup_entry(hass, entry)

    client_cls.return_value.get_diaries.side_effect = EdificeUnavailable("down")
    await tick(hass, freezer)
    assert hass.states.get(ENTITY_ID).state == "unavailable"

    client_cls.return_value.get_diaries.side_effect = None
    await tick(hass, freezer)
    assert hass.states.get(ENTITY_ID).state == "2"


async def test_credentials_rejected_later_stop_all_polling(hass, entry, client_cls, freezer):
    """A password changed on the ENT must cost one failed login, not one per refresh."""
    assert await setup_entry(hass, entry)

    client_cls.return_value.get_diaries.side_effect = EdificeAuthError("credentials rejected")
    await tick(hass, freezer)
    calls_after_failure = client_cls.return_value.get_diaries.call_count

    await tick(hass, freezer)
    await tick(hass, freezer)

    assert client_cls.return_value.get_diaries.call_count == calls_after_failure
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


# -- lifecycle -----------------------------------------------------------------------


async def test_unloading_closes_the_session(hass, entry, client_cls):
    assert await setup_entry(hass, entry)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    client_cls.return_value.close.assert_called_once()


# -- the calendar --------------------------------------------------------------------


async def _events(hass, start: str, end: str) -> list[dict]:
    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {"entity_id": CALENDAR_ID, "start_date_time": start, "end_date_time": end},
        blocking=True,
        return_response=True,
    )
    return response[CALENDAR_ID]["events"]


async def test_the_calendar_shows_the_whole_diary_as_all_day_events(hass, entry, client_cls):
    client_cls.return_value.get_homework.return_value = [
        make_homework("2026-09-10", "Histoire", "déjà passé"),
        *sample(),
    ]
    assert await setup_entry(hass, entry)

    events = await _events(hass, "2026-09-01T00:00:00+00:00", "2026-10-01T00:00:00+00:00")

    assert [(e["start"], e["end"], e["summary"]) for e in events] == [
        ("2026-09-10", "2026-09-11", "Histoire"),
        ("2026-09-21", "2026-09-22", "Maths"),
        ("2026-09-22", "2026-09-23", "Français"),
    ]
    assert events[1]["description"] == "Exercices 3 et 4"
    # The past is in the calendar, while the sensor only counts what is still to do.
    assert hass.states.get(ENTITY_ID).state == "2"


async def test_the_calendar_only_returns_what_overlaps_the_window(hass, entry, client_cls):
    assert await setup_entry(hass, entry)

    # One day, expressed in the test timezone (US/Pacific, UTC-7 in September).
    events = await _events(hass, "2026-09-21T00:00:00-07:00", "2026-09-22T00:00:00-07:00")

    assert [e["summary"] for e in events] == ["Maths"]


async def test_an_entry_without_a_subject_falls_back_to_the_diary_name(hass, entry, client_cls):
    client_cls.return_value.get_homework.return_value = [make_homework("2026-09-21", "", "Sortie au parc")]
    assert await setup_entry(hass, entry)

    events = await _events(hass, "2026-09-21T00:00:00-07:00", "2026-09-22T00:00:00-07:00")

    assert [e["summary"] for e in events] == ["CM1 A"]


async def test_the_calendar_is_on_while_homework_is_due_today(hass, entry, client_cls):
    assert await setup_entry(hass, entry)

    state = hass.states.get(CALENDAR_ID)

    assert state.state == "on"
    assert state.attributes["message"] == "Maths"


async def test_the_calendar_is_off_but_shows_the_next_homework_otherwise(hass, entry, client_cls, freezer):
    freezer.move_to("2026-09-20T12:00:00+00:00")  # the day before the first entry
    assert await setup_entry(hass, entry)

    state = hass.states.get(CALENDAR_ID)

    assert state.state == "off"
    assert state.attributes["message"] == "Maths"


# -- the "new homework" event --------------------------------------------------------


def _event_changes(events) -> list:
    return [e for e in events if e.data["entity_id"] == EVENT_ID]


def _with(*extra: Homework) -> list[Homework]:
    return [*sample(), *extra]


async def test_the_first_ever_refresh_announces_nothing(hass, entry, client_cls):
    """What already exists is the baseline; only what appears afterwards is news."""
    assert await setup_entry(hass, entry)

    assert hass.states.get(EVENT_ID).state == "unknown"


async def test_a_new_entry_is_announced_with_its_details(hass, entry, client_cls):
    assert await setup_entry(hass, entry)

    client_cls.return_value.get_homework.return_value = _with(
        make_homework("2026-09-23", "Science", "Apporter une plante")
    )
    await refresh(hass, entry)

    attributes = hass.states.get(EVENT_ID).attributes
    assert attributes["event_type"] == EVENT_HOMEWORK_ADDED
    assert attributes["subject"] == "Science"
    assert attributes["date"] == "2026-09-23"
    assert attributes["content"] == "Apporter une plante"
    assert attributes["entry_id"] == "2026-09-23-Science"


async def test_an_entry_is_announced_once_only(hass, entry, client_cls):
    assert await setup_entry(hass, entry)
    changes = async_capture_events(hass, "state_changed")

    client_cls.return_value.get_homework.return_value = _with(make_homework("2026-09-23", "Science", "x"))
    await refresh(hass, entry)
    await refresh(hass, entry)
    await refresh(hass, entry)

    assert len(_event_changes(changes)) == 1


async def test_several_entries_arriving_together_are_all_announced(hass, entry, client_cls):
    assert await setup_entry(hass, entry)
    changes = async_capture_events(hass, "state_changed")

    client_cls.return_value.get_homework.return_value = _with(
        make_homework("2026-09-23", "Science", "a"),
        make_homework("2026-09-24", "Musique", "b"),
    )
    await refresh(hass, entry)

    subjects = [e.data["new_state"].attributes["subject"] for e in _event_changes(changes)]
    assert subjects == ["Science", "Musique"]


async def test_an_entry_dated_in_the_past_is_not_announced(hass, entry, client_cls):
    """A teacher back-filling last week must not notify anybody."""
    assert await setup_entry(hass, entry)

    client_cls.return_value.get_homework.return_value = _with(make_homework("2026-09-15", "Histoire", "rattrapage"))
    await refresh(hass, entry)

    assert hass.states.get(EVENT_ID).state == "unknown"


async def test_a_restart_does_not_announce_the_whole_diary_again(hass, entry, client_cls):
    assert await setup_entry(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(EVENT_ID).state == "unknown"


async def test_what_was_added_while_home_assistant_was_down_is_announced_at_startup(hass, entry, client_cls):
    """The refresh that finds it runs before the entity exists; the entity must catch up."""
    assert await setup_entry(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    client_cls.return_value.get_homework.return_value = _with(
        make_homework("2026-09-23", "Science", "pendant la coupure")
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    attributes = hass.states.get(EVENT_ID).attributes
    assert attributes["subject"] == "Science"
    assert attributes["content"] == "pendant la coupure"


async def test_removing_the_entry_forgets_what_was_announced(hass, hass_storage, entry, client_cls):
    assert await setup_entry(hass, entry)
    key = f"{DOMAIN}.seen.{entry.entry_id}"
    assert key in hass_storage

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert key not in hass_storage


# -- the automation the README documents ---------------------------------------------

DOCUMENTED_AUTOMATION = {
    "alias": "New homework",
    "triggers": [
        {
            "trigger": "state",
            "entity_id": EVENT_ID,
            "not_from": ["unavailable"],
            "not_to": ["unavailable", "unknown"],
        }
    ],
    "actions": [
        {
            "action": "test.notify",
            "data": {
                "subject": "{{ trigger.to_state.attributes.subject }}",
                "date": "{{ trigger.to_state.attributes.date }}",
            },
        }
    ],
}


async def test_the_documented_automation_fires_for_news_and_not_for_recoveries(hass, entry, client_cls):
    """An outage and its recovery flip the entity through unavailable: that is not news."""
    calls = async_mock_service(hass, "test", "notify")
    assert await async_setup_component(hass, "automation", {"automation": DOCUMENTED_AUTOMATION})
    assert await setup_entry(hass, entry)
    assert calls == []

    client_cls.return_value.get_diaries.side_effect = EdificeUnavailable("down")
    await refresh(hass, entry)
    assert hass.states.get(EVENT_ID).state == "unavailable"
    client_cls.return_value.get_diaries.side_effect = None
    await refresh(hass, entry)
    assert calls == []

    client_cls.return_value.get_homework.return_value = _with(make_homework("2026-09-23", "Science", "x"))
    await refresh(hass, entry)
    assert [call.data for call in calls] == [{"subject": "Science", "date": "2026-09-23"}]


async def test_the_documented_automation_does_not_refire_an_old_event_after_a_recovery(hass, entry, client_cls):
    """Once an event exists, recovery brings its old timestamp back: that must not fire again."""
    calls = async_mock_service(hass, "test", "notify")
    assert await async_setup_component(hass, "automation", {"automation": DOCUMENTED_AUTOMATION})
    assert await setup_entry(hass, entry)

    client_cls.return_value.get_homework.return_value = _with(make_homework("2026-09-23", "Science", "x"))
    await refresh(hass, entry)
    assert len(calls) == 1

    client_cls.return_value.get_diaries.side_effect = EdificeUnavailable("down")
    await refresh(hass, entry)
    client_cls.return_value.get_diaries.side_effect = None
    await refresh(hass, entry)
    assert len(calls) == 1


def test_the_readme_example_is_the_automation_under_test():
    """Documentation that has drifted from what is tested is worse than none."""
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    block = re.search(r"```yaml\n(automation:\n  - alias: \"New homework\".*?)```", readme, re.DOTALL)
    assert block, "the README no longer documents the new-homework automation"

    documented = yaml.safe_load(block.group(1))["automation"][0]

    assert documented["triggers"] == DOCUMENTED_AUTOMATION["triggers"]
