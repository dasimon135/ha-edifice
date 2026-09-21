"""The refresh button and the polling interval."""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

import pytest
from edifice_test_helpers import make_homework, sample, setup_entry
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.edifice.api import EdificeUnavailable
from custom_components.edifice.const import (
    DEFAULT_SCAN_MINUTES,
    DOMAIN,
    MAX_SCAN_MINUTES,
    MIN_SCAN_MINUTES,
    UPDATE_INTERVAL,
    scan_interval,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations", "pin_clock")

TRANSLATIONS = Path(__file__).resolve().parent.parent / "custom_components" / "edifice" / "translations"
DEBOUNCE = datetime.timedelta(seconds=11)  # a little more than Home Assistant's 10 s cooldown


def _minutes(value: int) -> datetime.timedelta:
    return datetime.timedelta(minutes=value)


def _entry_with(entry, options: dict) -> MockConfigEntry:
    """The shared fixture, plus options: MockConfigEntry cannot be given them afterwards."""
    return MockConfigEntry(
        domain=DOMAIN, title=entry.title, unique_id=entry.unique_id, data=dict(entry.data), options=options
    )


def _button_id(hass, entry) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("button", DOMAIN, f"{entry.entry_id}_refresh")
    assert entity_id, "the refresh button was not created"
    return entity_id


async def _press(hass, entity_id: str) -> None:
    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)
    await hass.async_block_till_done()


async def _later(hass, freezer, delta: datetime.timedelta) -> None:
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


# -- the interval ---------------------------------------------------------------------


def test_the_interval_is_twenty_minutes_unless_chosen_otherwise():
    assert DEFAULT_SCAN_MINUTES == 20
    assert scan_interval({}) == UPDATE_INTERVAL == _minutes(20)


@pytest.mark.parametrize("minutes", [MIN_SCAN_MINUTES, 45, MAX_SCAN_MINUTES])
def test_a_chosen_interval_is_used(minutes):
    assert scan_interval({CONF_SCAN_INTERVAL: minutes}) == _minutes(minutes)


@pytest.mark.parametrize(
    "junk", [0, MIN_SCAN_MINUTES - 1, MAX_SCAN_MINUTES + 1, -30, "30", None, True, [30], {"minutes": 30}]
)
def test_an_absurd_interval_falls_back_to_the_default_instead_of_hammering_the_ent(junk):
    """Nothing typed into the config entry by hand may make the refreshes stop or flood."""
    assert scan_interval({CONF_SCAN_INTERVAL: junk}) == UPDATE_INTERVAL


async def test_the_coordinator_polls_at_the_default_interval(hass, entry, client_cls):
    assert await setup_entry(hass, entry)

    assert entry.runtime_data.update_interval == _minutes(20)


async def test_the_coordinator_polls_at_the_chosen_interval(hass, entry, client_cls):
    chosen = _entry_with(entry, {CONF_SCAN_INTERVAL: 45})

    assert await setup_entry(hass, chosen)

    assert chosen.runtime_data.update_interval == _minutes(45)


# -- the button -----------------------------------------------------------------------


async def test_the_button_sits_on_the_account_device_and_is_named_in_the_language(hass, entry, client_cls):
    assert await setup_entry(hass, entry)

    entity_id = _button_id(hass, entry)
    assert hass.states.get(entity_id).attributes["friendly_name"] == "School Emma Refresh"
    registered = er.async_get(hass).async_get(entity_id)
    device = dr.async_get(hass).async_get(registered.device_id)
    assert (DOMAIN, entry.entry_id) in device.identifiers


async def test_pressing_the_button_reads_the_ent_now(hass, entry, client_cls):
    assert await setup_entry(hass, entry)
    client = client_cls.return_value
    before = client.get_diaries.call_count
    client.get_homework.return_value = [*sample(), make_homework("2026-09-23", "Science", "x")]

    await _press(hass, _button_id(hass, entry))

    assert client.get_diaries.call_count == before + 1
    assert len(entry.runtime_data.data.upcoming) == 3


async def test_pressing_it_repeatedly_costs_two_reads_at_most(hass, entry, client_cls, freezer):
    """The first press reads at once; the rest are answered by one read when the cooldown ends."""
    assert await setup_entry(hass, entry)
    client = client_cls.return_value
    button = _button_id(hass, entry)
    before = client.get_diaries.call_count

    for _ in range(5):
        await _press(hass, button)
    assert client.get_diaries.call_count == before + 1

    await _later(hass, freezer, DEBOUNCE)
    assert client.get_diaries.call_count == before + 2

    await _later(hass, freezer, DEBOUNCE)
    assert client.get_diaries.call_count == before + 2


async def test_the_button_stays_available_when_the_ent_is_down_and_pressing_it_retries(
    hass, entry, client_cls, freezer
):
    assert await setup_entry(hass, entry)
    client = client_cls.return_value
    button = _button_id(hass, entry)
    homework = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_homework")
    assert homework, "the homework sensor was not found"

    client.get_diaries.side_effect = EdificeUnavailable("down")
    await _later(hass, freezer, DEBOUNCE)
    await _press(hass, button)
    assert hass.states.get(homework).state == "unavailable"
    assert hass.states.get(button).state != "unavailable"

    client.get_diaries.side_effect = None
    await _later(hass, freezer, DEBOUNCE)
    await _press(hass, button)
    assert hass.states.get(homework).state != "unavailable"


# -- the options ----------------------------------------------------------------------


def _suggested(result) -> object:
    for key in result["data_schema"].schema:
        if key == CONF_SCAN_INTERVAL:
            return key.description["suggested_value"]
    raise AssertionError("the form has no interval field")


async def test_the_options_form_offers_the_default_and_then_the_current_value(hass, entry, client_cls):
    assert await setup_entry(hass, entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert _suggested(result) == 20
    assert result["description_placeholders"] == {"default": "20", "minimum": "5"}


async def test_the_options_form_shows_a_previously_chosen_value(hass, entry, client_cls):
    chosen = _entry_with(entry, {CONF_SCAN_INTERVAL: 45})
    assert await setup_entry(hass, chosen)

    result = await hass.config_entries.options.async_init(chosen.entry_id)

    assert _suggested(result) == 45


async def test_saving_the_interval_reloads_the_entry_with_it(hass, entry, client_cls):
    assert await setup_entry(hass, entry)
    before = entry.runtime_data
    result = await hass.config_entries.options.async_init(entry.entry_id)

    # The selector hands back a float, like every number field in the interface.
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_SCAN_INTERVAL: 60.0})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_SCAN_INTERVAL: 60}
    assert isinstance(entry.options[CONF_SCAN_INTERVAL], int)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not before, "the entry was not reloaded"
    assert entry.runtime_data.update_interval == _minutes(60)


@pytest.mark.parametrize("minutes", [MIN_SCAN_MINUTES - 1, MAX_SCAN_MINUTES + 1])
async def test_an_interval_out_of_bounds_is_refused(hass, entry, client_cls, minutes):
    assert await setup_entry(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)

    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(result["flow_id"], {CONF_SCAN_INTERVAL: minutes})

    assert entry.options == {}


# -- translations ---------------------------------------------------------------------


def _load(language: str) -> dict:
    return json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("language", ["en", "fr"])
async def test_the_options_form_supplies_every_placeholder_its_text_uses(hass, entry, client_cls, language):
    """A missing placeholder would show up as a literal ``{default}`` in the form."""
    assert await setup_entry(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    used = set(re.findall(r"{(\w+)}", _load(language)["options"]["step"]["init"]["description"]))

    assert used
    assert used <= set(result["description_placeholders"])


@pytest.mark.parametrize("language", ["en", "fr"])
def test_the_new_texts_exist_in_both_languages(language):
    texts = _load(language)

    assert texts["entity"]["button"]["refresh"]["name"]
    step = texts["options"]["step"]["init"]
    assert all(step[key] for key in ("title", "description"))
    assert step["data"][CONF_SCAN_INTERVAL]
    assert step["data_description"][CONF_SCAN_INTERVAL]


def test_the_two_languages_have_the_same_keys():
    def keys(node, prefix=""):
        if isinstance(node, dict):
            for key, value in node.items():
                yield from keys(value, f"{prefix}.{key}")
        else:
            yield prefix

    assert set(keys(_load("en"))) == set(keys(_load("fr")))
