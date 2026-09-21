"""The dashboard cards of the README, rendered against sample data.

A markdown card is a Jinja template, and a template that fails renders as an empty card without
a word of explanation. Nothing else would notice, so this is where the examples are held to
what the README promises.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from edifice_test_helpers import EMMA, make_homework, make_word, sample, setup_entry
from homeassistant.helpers.template import Template

pytestmark = pytest.mark.usefixtures("enable_custom_integrations", "pin_clock")

README = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")

# The clock is pinned to 2026-09-21: Maths is due today, Français tomorrow.
EXPECTED_TYPES = ["markdown", "markdown", "calendar", "markdown", "button", "markdown"]


def _section() -> str:
    match = re.search(r"^## Dashboard examples\n(.*?)(?=^## )", README, re.DOTALL | re.MULTILINE)
    assert match, "the README no longer has a Dashboard examples section"
    return match.group(1)


def _cards() -> list[dict]:
    return [yaml.safe_load(block) for block in re.findall(r"```yaml\n(.*?)```", _section(), re.DOTALL)]


def _render(hass, card: dict) -> str:
    return Template(card["content"], hass).async_render(parse_result=False)


@pytest.fixture
async def ready(hass, entry, client_cls, enable_custom_integrations, pin_clock):
    """The integration running with a class diary, one child and three of their notes.

    The two fixtures at the end are named so that they run before this one: a fixture that
    only reaches the test through ``usefixtures`` is ordered after the ones it lists.
    """
    client = client_cls.return_value
    client.get_homework.return_value = [*sample(), make_homework("2026-09-25", "Sciences", "Apporter une plante")]
    client.get_children.return_value = [EMMA]
    client.get_unread_words.return_value = 2
    client.get_words.side_effect = lambda child_id: [
        make_word(3, "2026-05-01", title="Old and unanswered"),
        make_word(2, "2026-09-18", title="Sortie au musee"),
        make_word(1, "2026-09-17", title="Already done", acknowledged=True),
    ]
    assert await setup_entry(hass, entry)


def test_the_section_holds_exactly_the_examples_this_file_checks():
    """Adding an example without a check for it would let it rot unnoticed."""
    assert [card["type"] for card in _cards()] == EXPECTED_TYPES


def test_the_examples_carry_no_emoji():
    """A project decision: they draw differently on every device, and a state is better said in words."""
    assert not re.search("[\U0001f300-\U0001faff☀-➿️]", _section())


@pytest.mark.usefixtures("ready")
async def test_every_entity_the_examples_name_exists(hass):
    # Only the cards: the introduction names the French entity ids as an example of another
    # language. `button.press` is the name of an action, not of an entity.
    in_cards = json.dumps(_cards())
    named = set(re.findall(r"\b(?:sensor|calendar|button|event)\.[a-z0-9_]+", in_cards)) - {"button.press"}

    assert named, "the examples name no entity"
    assert {entity_id for entity_id in named if hass.states.get(entity_id) is None} == set()


@pytest.mark.usefixtures("ready")
async def test_homework_by_day_groups_and_names_the_days(hass):
    text = _render(hass, _cards()[0])

    assert "**Today**" in text
    assert "- **Maths**: Exercices 3 et 4" in text
    assert "**Tomorrow**" in text
    assert "- **Français**: Lire le chapitre 2" in text
    assert "**Friday 25 September**" in text
    assert "- **Sciences**: Apporter une plante" in text
    assert text.index("Today") < text.index("Tomorrow") < text.index("Friday")


@pytest.mark.usefixtures("ready")
async def test_tomorrow_at_a_glance_lists_the_subjects_due_tomorrow_only(hass):
    text = _render(hass, _cards()[1])

    assert text.strip() == "**Tomorrow**: Français"


@pytest.mark.usefixtures("ready")
async def test_notes_to_acknowledge_keeps_recent_unacknowledged_ones_with_their_year(hass):
    text = _render(hass, _cards()[3])

    assert "**To acknowledge** (1):" in text
    assert "- 2026-09-18: Sortie au musee" in text
    assert "Already done" not in text, "an acknowledged note is not to be acknowledged"
    assert "Old and unanswered" not in text, "a note older than 30 days is noise"


@pytest.mark.usefixtures("ready")
async def test_the_last_read_line_says_how_old_the_data_is(hass):
    text = _render(hass, _cards()[5])

    assert re.fullmatch(r"Last read: .+ ago\s*", text), text


@pytest.mark.usefixtures("ready")
async def test_the_button_example_presses_the_refresh_button(hass, client_cls):
    action = _cards()[4]["tap_action"]
    client = client_cls.return_value
    before = client.get_diaries.call_count

    assert action["perform_action"] == "button.press"
    await hass.services.async_call("button", "press", action["target"], blocking=True)
    await hass.async_block_till_done()

    assert client.get_diaries.call_count == before + 1
