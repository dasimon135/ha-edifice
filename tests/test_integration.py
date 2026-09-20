"""Setup, sensor and failure-handling tests for the Edifice ENT integration."""

from __future__ import annotations

import datetime
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.edifice.api import (
    Diary,
    EdificeAuthError,
    EdificeError,
    EdificePlatformError,
    EdificeUnavailable,
    Homework,
)
from custom_components.edifice.const import ATTR_HOMEWORK, ATTR_NEXT_DUE, DOMAIN, UPCOMING_DAYS, UPDATE_INTERVAL
from custom_components.edifice.sensor import EdificeHomeworkSensor

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

ENTITY_ID = "sensor.school_emma_homework"
DIARY = Diary(diary_id="d1", title="CM1 A")


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


@pytest.fixture
def entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="School Emma",
        unique_id="ent.example.org:parent",
        data={CONF_URL: "https://ent.example.org", CONF_USERNAME: "parent", CONF_PASSWORD: "secret"},
    )


@pytest.fixture
def client_cls():
    with patch("custom_components.edifice.EdificeClient", autospec=True) as cls:
        client = cls.return_value
        client.get_diaries.return_value = [DIARY]
        client.get_homework.return_value = [
            make_homework("2026-09-21", "Maths", "Exercices 3 et 4"),
            make_homework("2026-09-22", "Français", "Lire le chapitre 2"),
        ]
        yield cls


async def _setup(hass, entry) -> bool:
    entry.add_to_hass(hass)
    ok = await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return ok


async def _tick(hass, freezer) -> None:
    freezer.tick(UPDATE_INTERVAL + datetime.timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


# -- the sensor ----------------------------------------------------------------------


async def test_sensor_reports_the_upcoming_homework(hass, entry, client_cls, freezer):
    freezer.move_to("2026-09-21T12:00:00+00:00")

    assert await _setup(hass, entry)

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

    assert await _setup(hass, entry)

    state = hass.states.get(ENTITY_ID)
    assert state.state == "0"
    assert state.attributes[ATTR_NEXT_DUE] is None
    assert state.attributes[ATTR_HOMEWORK] == []


async def test_sensor_has_a_stable_unique_id(hass, entry, client_cls):
    assert await _setup(hass, entry)
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_homework") == ENTITY_ID


def test_the_homework_list_stays_out_of_the_recorder():
    assert ATTR_HOMEWORK in EdificeHomeworkSensor._unrecorded_attributes
    assert ATTR_NEXT_DUE not in EdificeHomeworkSensor._unrecorded_attributes


# -- what the coordinator asks for ---------------------------------------------------


async def test_the_window_starts_today_and_reuses_the_diary_list(hass, entry, client_cls, freezer):
    freezer.move_to("2026-09-21T12:00:00+00:00")

    assert await _setup(hass, entry)

    client_cls.return_value.get_diaries.assert_called_once()
    client_cls.return_value.get_homework.assert_called_once_with(
        since=datetime.date(2026, 9, 21),
        until=datetime.date(2026, 9, 21) + datetime.timedelta(days=UPCOMING_DAYS),
        diaries=[DIARY],
    )


async def test_today_follows_the_home_assistant_timezone(hass, entry, client_cls, freezer):
    """20:00 UTC is already tomorrow in Auckland; the sensor must agree with HA, not the OS."""
    await hass.config.async_set_time_zone("Pacific/Auckland")
    freezer.move_to("2026-09-21T20:00:00+00:00")

    assert await _setup(hass, entry)

    kwargs = client_cls.return_value.get_homework.call_args.kwargs
    assert kwargs["since"] == datetime.date(2026, 9, 22)


async def test_the_client_is_built_from_the_entry(hass, entry, client_cls):
    assert await _setup(hass, entry)
    client_cls.assert_called_once_with(
        base_url="https://ent.example.org", username="parent", password="secret"
    )


# -- failures ------------------------------------------------------------------------


async def test_rejected_credentials_start_reauth_and_are_not_retried(hass, entry, client_cls):
    client_cls.return_value.get_diaries.side_effect = EdificeAuthError("credentials rejected")

    assert not await _setup(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]
    assert client_cls.return_value.get_diaries.call_count == 1


@pytest.mark.parametrize("error", [EdificeUnavailable("down"), EdificePlatformError("gone"), EdificeError("odd")])
async def test_other_failures_at_setup_are_retried_later(hass, entry, client_cls, error):
    client_cls.return_value.get_diaries.side_effect = error

    assert not await _setup(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)  # no reauth for a network blip


async def test_a_failed_refresh_makes_the_sensor_unavailable_then_it_recovers(hass, entry, client_cls, freezer):
    assert await _setup(hass, entry)

    client_cls.return_value.get_diaries.side_effect = EdificeUnavailable("down")
    await _tick(hass, freezer)
    assert hass.states.get(ENTITY_ID).state == "unavailable"

    client_cls.return_value.get_diaries.side_effect = None
    await _tick(hass, freezer)
    assert hass.states.get(ENTITY_ID).state == "2"


async def test_credentials_rejected_later_stop_all_polling(hass, entry, client_cls, freezer):
    """A password changed on the ENT must cost one failed login, not one per refresh."""
    assert await _setup(hass, entry)

    client_cls.return_value.get_diaries.side_effect = EdificeAuthError("credentials rejected")
    await _tick(hass, freezer)
    calls_after_failure = client_cls.return_value.get_diaries.call_count

    await _tick(hass, freezer)
    await _tick(hass, freezer)

    assert client_cls.return_value.get_diaries.call_count == calls_after_failure
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


# -- lifecycle -----------------------------------------------------------------------


async def test_unloading_closes_the_session(hass, entry, client_cls):
    assert await _setup(hass, entry)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    client_cls.return_value.close.assert_called_once()
