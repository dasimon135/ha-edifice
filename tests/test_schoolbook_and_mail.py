"""The cahier de liaison, per child, and the unread-mail counter.

Both are optional modules: a platform may have neither, one, or both, and a module that is
missing or answers nonsense must never cost the homework.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path

import pytest
import yaml
from edifice_test_helpers import EMMA, TOM, make_word, refresh, sample, setup_entry
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_capture_events, async_mock_service

from custom_components.edifice.api import (
    EdificeAuthError,
    EdificeError,
    EdificePlatformError,
    EdificeUnavailable,
)
from custom_components.edifice.const import CHILDREN_REFRESH, DOMAIN, EVENT_WORD_ADDED

pytestmark = pytest.mark.usefixtures("enable_custom_integrations", "pin_clock")

HOMEWORK_ID = "sensor.school_emma_homework"
EMMA_UNREAD = "sensor.emma_unread_school_notes"
TOM_UNREAD = "sensor.tom_unread_school_notes"
EMMA_EVENT = "event.emma_new_school_note"
TOM_EVENT = "event.tom_new_school_note"
MESSAGES = "sensor.school_emma_unread_messages"

NEVER_KEPT = "TEXT-THAT-MUST-NEVER-BE-KEPT"


@pytest.fixture
def book(client_cls):
    """Two children and a mailbox, with state the tests can change between refreshes."""
    client = client_cls.return_value
    state = {
        "unread": {EMMA.child_id: 2, TOM.child_id: 0},
        "words": {
            EMMA.child_id: [make_word(2, "2026-09-18"), make_word(1, "2026-09-17", acknowledged=True)],
            TOM.child_id: [],
        },
    }
    client.get_children.return_value = [EMMA, TOM]
    client.get_unread_words.side_effect = lambda child_id: state["unread"][child_id]
    client.get_words.side_effect = lambda child_id: state["words"][child_id]
    client.get_unread_messages.side_effect = None
    client.get_unread_messages.return_value = 5
    return state


def _device_of(hass, entity_id):
    """The device an entity sits on. Goes through the entity: looking a device up by its
    identifiers is deprecated since identifiers are no longer unique across config entries."""
    device_id = er.async_get(hass).async_get(entity_id).device_id
    return dr.async_get(hass).async_get(device_id)


# -- entities ------------------------------------------------------------------------


async def test_each_child_gets_a_device_and_an_unread_counter(hass, entry, book):
    assert await setup_entry(hass, entry)

    assert hass.states.get(EMMA_UNREAD).state == "2"
    assert hass.states.get(TOM_UNREAD).state == "0"

    emma, tom, account = (_device_of(hass, entity_id) for entity_id in (EMMA_UNREAD, TOM_UNREAD, HOMEWORK_ID))
    assert (emma.name, tom.name) == ("Emma", "Tom")
    assert len({emma.id, tom.id, account.id}) == 3, "one device per child, and one for the account"
    assert (DOMAIN, f"{entry.entry_id}_{EMMA.child_id}") in emma.identifiers
    # Every entity of a child sits on that child's device.
    assert _device_of(hass, EMMA_EVENT).id == emma.id


async def test_the_list_carries_no_text_and_says_which_words_were_acknowledged(hass, entry, book):
    book["words"][EMMA.child_id][0] = make_word(2, "2026-09-18", title="Sortie", sender="Mme Petit", category="TRIP")

    assert await setup_entry(hass, entry)

    words = hass.states.get(EMMA_UNREAD).attributes["words"]
    assert [(w["id"], w["acknowledged"]) for w in words] == [(2, False), (1, True)]
    assert words[0] == {
        "id": 2,
        "title": "Sortie",
        "date": "2026-09-18",
        "sender": "Mme Petit",
        "category": "TRIP",
        "acknowledged": False,
    }
    assert NEVER_KEPT not in str(hass.states.get(EMMA_UNREAD).attributes)


async def test_the_mailbox_counter_lives_on_the_account_device(hass, entry, book):
    assert await setup_entry(hass, entry)

    assert hass.states.get(MESSAGES).state == "5"
    assert _device_of(hass, MESSAGES).id == _device_of(hass, HOMEWORK_ID).id


async def test_a_platform_without_these_modules_gets_only_the_homework_entities(hass, entry, client_cls):
    assert await setup_entry(hass, entry)

    assert hass.states.async_entity_ids("sensor") == [HOMEWORK_ID]
    assert hass.states.async_entity_ids("event") == ["event.school_emma_new_homework"]


def test_the_unread_lists_stay_out_of_the_recorder():
    from custom_components.edifice.sensor import EdificeUnreadWordsSensor

    assert "words" in EdificeUnreadWordsSensor._unrecorded_attributes


# -- a missing or broken module never costs the homework -----------------------------


async def test_a_missing_module_is_not_asked_for_again(hass, entry, client_cls):
    client = client_cls.return_value
    client.get_children.return_value = [EMMA]
    client.get_unread_words.side_effect = EdificePlatformError("not deployed")

    assert await setup_entry(hass, entry)
    await refresh(hass, entry)
    await refresh(hass, entry)

    assert client.get_unread_words.call_count == 1
    assert client.get_unread_messages.call_count == 1  # the default fixture has no mailbox either
    assert hass.states.get(HOMEWORK_ID).state == "2"


async def test_an_unreadable_count_falls_back_on_the_list(hass, entry, book, client_cls):
    """The count answered nonsense: the unacknowledged words of the page still tell."""
    unread = client_cls.return_value.get_unread_words

    def flaky(child_id):
        if child_id == EMMA.child_id:
            raise EdificeError("weird")
        return 0

    unread.side_effect = flaky

    assert await setup_entry(hass, entry)

    assert hass.states.get(EMMA_UNREAD).state == "1"  # word 2 is unacknowledged, word 1 is not
    assert hass.states.get(HOMEWORK_ID).state == "2"


async def test_a_child_whose_module_answers_nothing_readable_gets_no_entities(hass, entry, book, client_cls):
    client = client_cls.return_value

    def count(child_id):
        if child_id == TOM.child_id:
            raise EdificeError("weird")
        return 2

    def words(child_id):
        if child_id == TOM.child_id:
            raise EdificeError("weird")
        return book["words"][child_id]

    client.get_unread_words.side_effect = count
    client.get_words.side_effect = words

    assert await setup_entry(hass, entry)

    assert hass.states.get(EMMA_UNREAD) is not None
    assert hass.states.get(TOM_UNREAD) is None
    assert hass.states.get(HOMEWORK_ID).state == "2"


async def test_a_network_failure_in_an_optional_module_puts_the_whole_refresh_in_doubt(hass, entry, book, client_cls):
    client_cls.return_value.get_unread_words.side_effect = EdificeUnavailable("down")

    assert not await setup_entry(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_rejected_credentials_in_an_optional_module_still_start_reauth(hass, entry, book, client_cls):
    client_cls.return_value.get_unread_messages.side_effect = EdificeAuthError("rejected")

    assert not await setup_entry(hass, entry)

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_a_child_that_stops_answering_becomes_unavailable_then_recovers(hass, entry, book, client_cls):
    assert await setup_entry(hass, entry)
    client = client_cls.return_value
    working = client.get_unread_words.side_effect, client.get_words.side_effect

    client.get_unread_words.side_effect = EdificeError("weird")
    client.get_words.side_effect = EdificeError("weird")
    await refresh(hass, entry)
    assert hass.states.get(EMMA_UNREAD).state == "unavailable"
    assert hass.states.get(HOMEWORK_ID).state == "2"

    client.get_unread_words.side_effect, client.get_words.side_effect = working
    await refresh(hass, entry)
    assert hass.states.get(EMMA_UNREAD).state == "2"


# -- children are not asked for at every refresh -------------------------------------


async def test_the_children_are_asked_for_every_few_hours_not_every_refresh(hass, entry, book, client_cls, freezer):
    client = client_cls.return_value
    assert await setup_entry(hass, entry)
    await refresh(hass, entry)
    await refresh(hass, entry)
    assert client.get_children.call_count == 1

    freezer.tick(CHILDREN_REFRESH + datetime.timedelta(seconds=1))
    await refresh(hass, entry)

    assert client.get_children.call_count == 2


async def test_an_unreadable_children_list_keeps_the_previous_one(hass, entry, book, client_cls, freezer):
    client = client_cls.return_value
    assert await setup_entry(hass, entry)

    client.get_children.side_effect = EdificeError("weird")
    freezer.tick(CHILDREN_REFRESH + datetime.timedelta(seconds=1))
    await refresh(hass, entry)

    assert hass.states.get(EMMA_UNREAD).state == "2"
    assert client.get_children.call_count == 2  # it tried, and will try again


# -- the "new note" event ------------------------------------------------------------


def _event_changes(events, entity_id):
    return [e for e in events if e.data["entity_id"] == entity_id]


async def test_existing_words_are_a_baseline_not_news(hass, entry, book):
    assert await setup_entry(hass, entry)

    assert hass.states.get(EMMA_EVENT).state == "unknown"
    assert hass.states.get(TOM_EVENT).state == "unknown"


async def test_a_new_word_is_announced_with_its_details_but_never_its_text(hass, entry, book):
    assert await setup_entry(hass, entry)

    book["words"][EMMA.child_id].insert(0, make_word(3, "2026-09-19", title="Sortie", sender="Mme Petit"))
    await refresh(hass, entry)

    attributes = hass.states.get(EMMA_EVENT).attributes
    assert attributes["event_type"] == EVENT_WORD_ADDED
    assert (attributes["id"], attributes["title"], attributes["sender"]) == (3, "Sortie", "Mme Petit")
    assert (attributes["date"], attributes["acknowledged"]) == ("2026-09-19", False)
    assert NEVER_KEPT not in str(attributes)


async def test_a_word_is_announced_once_only(hass, entry, book):
    assert await setup_entry(hass, entry)
    changes = async_capture_events(hass, "state_changed")

    book["words"][EMMA.child_id].insert(0, make_word(3, "2026-09-19"))
    for _ in range(3):
        await refresh(hass, entry)

    assert len(_event_changes(changes, EMMA_EVENT)) == 1


async def test_a_word_for_one_child_does_not_fire_the_other_childs_event(hass, entry, book):
    assert await setup_entry(hass, entry)
    changes = async_capture_events(hass, "state_changed")

    book["words"][TOM.child_id].append(make_word(9, "2026-09-19"))
    await refresh(hass, entry)

    assert len(_event_changes(changes, TOM_EVENT)) == 1
    assert _event_changes(changes, EMMA_EVENT) == []


async def test_a_word_already_acknowledged_elsewhere_is_still_announced_and_says_so(hass, entry, book):
    assert await setup_entry(hass, entry)

    book["words"][EMMA.child_id].insert(0, make_word(3, "2026-09-19", acknowledged=True))
    await refresh(hass, entry)

    assert hass.states.get(EMMA_EVENT).attributes["acknowledged"] is True


async def test_several_words_arriving_together_are_all_announced(hass, entry, book):
    assert await setup_entry(hass, entry)
    changes = async_capture_events(hass, "state_changed")

    book["words"][EMMA.child_id][:0] = [make_word(4, "2026-09-20"), make_word(3, "2026-09-19")]
    await refresh(hass, entry)

    titles = [e.data["new_state"].attributes["title"] for e in _event_changes(changes, EMMA_EVENT)]
    assert sorted(titles) == ["Mot 3", "Mot 4"]


async def test_a_restart_does_not_announce_the_words_again(hass, entry, book):
    assert await setup_entry(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(EMMA_EVENT).state == "unknown"


async def test_a_word_added_while_home_assistant_was_down_is_announced_at_startup(hass, entry, book):
    assert await setup_entry(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    book["words"][EMMA.child_id].insert(0, make_word(3, "2026-09-19", title="Pendant la coupure"))
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(EMMA_EVENT).attributes["title"] == "Pendant la coupure"


async def test_the_first_run_of_this_version_on_an_existing_installation_announces_nothing(
    hass, hass_storage, entry, book
):
    """The homework file exists from the previous version; the words file does not."""
    key = f"{DOMAIN}.seen.{entry.entry_id}"
    ids = sorted(hw.entry_id for hw in sample())
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": {"seen": ids}}

    assert await setup_entry(hass, entry)

    assert hass.states.get(EMMA_EVENT).state == "unknown"
    assert hass.states.get("event.school_emma_new_homework").state == "unknown"


async def test_a_child_met_later_is_a_baseline_and_only_then_are_their_new_words_news(hass, entry, client_cls, freezer):
    client = client_cls.return_value
    words = {TOM.child_id: [make_word(9, "2026-09-10")], EMMA.child_id: [make_word(1)]}
    client.get_children.return_value = [EMMA]
    client.get_unread_words.return_value = 0
    client.get_words.side_effect = lambda child_id: words[child_id]
    assert await setup_entry(hass, entry)

    client.get_children.return_value = [EMMA, TOM]  # a second child is enrolled
    freezer.tick(CHILDREN_REFRESH + datetime.timedelta(seconds=1))
    await refresh(hass, entry)
    assert entry.runtime_data.data.new_words == {}, "Tom's existing words are the baseline"

    words[TOM.child_id].insert(0, make_word(10, "2026-09-20"))
    await refresh(hass, entry)
    assert list(entry.runtime_data.data.new_words) == [TOM.child_id]


# -- what is remembered --------------------------------------------------------------


async def test_the_announced_words_are_remembered_per_child(hass, hass_storage, entry, book):
    assert await setup_entry(hass, entry)
    book["words"][EMMA.child_id].insert(0, make_word(3, "2026-09-19"))
    await refresh(hass, entry)

    key = f"{DOMAIN}.words.{entry.entry_id}"
    assert hass_storage[key]["data"] == {EMMA.child_id: [1, 2, 3], TOM.child_id: []}


async def test_removing_the_entry_forgets_the_words_too(hass, hass_storage, entry, book):
    assert await setup_entry(hass, entry)
    keys = [f"{DOMAIN}.seen.{entry.entry_id}", f"{DOMAIN}.words.{entry.entry_id}"]
    assert all(key in hass_storage for key in keys)

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert not any(key in hass_storage for key in keys)


# -- the automation the README documents ---------------------------------------------

DOCUMENTED_AUTOMATION = {
    "alias": "New school note",
    "triggers": [
        {
            "trigger": "state",
            "entity_id": EMMA_EVENT,
            "not_from": ["unavailable"],
            "not_to": ["unavailable", "unknown"],
        }
    ],
    "actions": [
        {
            "action": "test.notify",
            "data": {
                "title": "{{ trigger.to_state.attributes.title }}",
                "sender": "{{ trigger.to_state.attributes.sender }}",
            },
        }
    ],
}


async def test_the_documented_automation_fires_for_a_new_word_and_not_for_a_recovery(hass, entry, book, client_cls):
    calls = async_mock_service(hass, "test", "notify")
    assert await async_setup_component(hass, "automation", {"automation": DOCUMENTED_AUTOMATION})
    assert await setup_entry(hass, entry)
    assert calls == []

    client = client_cls.return_value
    client.get_unread_messages.side_effect = EdificeUnavailable("down")
    await refresh(hass, entry)
    assert hass.states.get(EMMA_EVENT).state == "unavailable"
    client.get_unread_messages.side_effect = None
    await refresh(hass, entry)
    assert calls == []

    book["words"][EMMA.child_id].insert(0, make_word(3, "2026-09-19", title="Sortie", sender="Mme Petit"))
    await refresh(hass, entry)
    assert [call.data for call in calls] == [{"title": "Sortie", "sender": "Mme Petit"}]


def test_the_readme_example_matches_the_one_under_test():
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    block = re.search(r"```yaml\n(automation:\n  - alias: \"New school note\".*?)```", readme, re.DOTALL)
    assert block, "the README no longer documents the new-note automation"

    documented = yaml.safe_load(block.group(1))["automation"][0]

    assert documented["triggers"] == DOCUMENTED_AUTOMATION["triggers"]
