"""Shared fixtures.

Home Assistant is imported inside the fixtures, so that the pure tests, which run without it,
can still collect this file.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def pin_clock(freezer):
    """The sample data is dated: nothing may depend on the day the suite runs."""
    freezer.move_to("2026-09-21T12:00:00+00:00")


@pytest.fixture
def entry():
    from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.edifice.const import DOMAIN

    return MockConfigEntry(
        domain=DOMAIN,
        title="School Emma",
        unique_id="ent.example.org:parent",
        data={CONF_URL: "https://ent.example.org", CONF_USERNAME: "parent", CONF_PASSWORD: "secret"},
    )


@pytest.fixture
def client_cls():
    """A stand-in for the client that answers with the sample diary.

    By default the platform has neither the cahier de liaison nor the older mailbox: a test
    that wants them sets ``get_children``, ``get_unread_words`` and so on itself.
    """
    from edifice_test_helpers import DIARY, sample

    from custom_components.edifice.api import EdificePlatformError

    with patch("custom_components.edifice.EdificeClient", autospec=True) as cls:
        client = cls.return_value
        client.get_diaries.return_value = [DIARY]
        client.get_homework.return_value = sample()
        client.get_children.return_value = []
        client.get_unread_messages.side_effect = EdificePlatformError("not deployed")
        yield cls
