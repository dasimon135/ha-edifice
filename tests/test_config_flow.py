"""Config flow tests: URL handling, error mapping, duplicates and reauthentication."""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_NAME, CONF_PASSWORD, CONF_URL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.edifice.api import (
    Diary,
    EdificeAuthError,
    EdificePlatformError,
    EdificeUnavailable,
)
from custom_components.edifice.config_flow import normalise_url
from custom_components.edifice.const import DOMAIN

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

TRANSLATIONS = Path(__file__).resolve().parent.parent / "custom_components" / "edifice" / "translations"

USER_INPUT = {
    CONF_URL: "ent.Example.org/timeline",
    CONF_USERNAME: " Parent ",
    CONF_PASSWORD: "secret",
}


@pytest.fixture
def client_cls():
    """Patch the client the config flow builds, so no request leaves the test."""
    with patch("custom_components.edifice.config_flow.EdificeClient", autospec=True) as cls:
        cls.return_value.get_diaries.return_value = [Diary(diary_id="d1", title="CM1 A")]
        yield cls


@pytest.fixture
def mock_setup_entry():
    """Stand in for the setup, leaving the runtime data that the real unload expects.

    An entry whose setup is mocked is still loaded, and Home Assistant unloads it at the end
    of the test: with no runtime data on it, that unload would fail and log noise.
    """

    async def fake_setup(hass, entry):
        entry.runtime_data = MagicMock()
        return True

    with patch("custom_components.edifice.async_setup_entry", side_effect=fake_setup) as mock:
        yield mock


async def _start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})


async def _submit(hass: HomeAssistant, user_input: dict):
    result = await _start(hass)
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


def _existing_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="School",
        unique_id="ent.example.org:parent",
        data={CONF_URL: "https://ent.example.org", CONF_USERNAME: "parent", CONF_PASSWORD: "old"},
    )


# -- URL normalisation ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("https://ent.example.org", "https://ent.example.org"),
        ("ent.example.org", "https://ent.example.org"),
        ("  ENT.Example.org/timeline?x=1  ", "https://ent.example.org"),
        ("https://ent.example.org:8443/auth/login", "https://ent.example.org:8443"),
    ],
)
def test_normalise_url_keeps_only_the_host(typed, expected):
    assert normalise_url(typed) == expected


@pytest.mark.parametrize(
    "typed",
    [
        "",
        "   ",
        "http://ent.example.org",  # a school password must never travel in clear
        "ftp://ent.example.org",
        "https://parent:secret@ent.example.org",  # would end up stored in the entry
    ],
)
def test_normalise_url_rejects_unsafe_input(typed):
    with pytest.raises(ValueError):
        normalise_url(typed)


# -- adding an account ---------------------------------------------------------------


async def test_user_flow_creates_an_entry(hass, client_cls, mock_setup_entry):
    result = await _submit(hass, USER_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "CM1 A"  # falls back to the diary name
    assert result["data"] == {
        CONF_URL: "https://ent.example.org",
        CONF_USERNAME: "Parent",
        CONF_PASSWORD: "secret",
    }
    assert result["result"].unique_id == "ent.example.org:parent"
    client_cls.assert_called_once_with(
        base_url="https://ent.example.org", username="Parent", password="secret"
    )
    client_cls.return_value.close.assert_called_once()


async def test_user_flow_uses_the_name_when_given(hass, client_cls, mock_setup_entry):
    result = await _submit(hass, {**USER_INPUT, CONF_NAME: "  School Emma  "})
    assert result["title"] == "School Emma"


@pytest.mark.parametrize(
    ("method", "error", "key"),
    [
        ("login", EdificeAuthError("no"), "invalid_auth"),
        ("login", EdificeUnavailable("down"), "cannot_connect"),
        ("check_platform", EdificeUnavailable("down"), "cannot_connect"),
        ("check_platform", EdificePlatformError("not edifice"), "unsupported_platform"),
        ("get_diaries", EdificePlatformError("no module"), "unsupported_platform"),
        ("login", RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_flow_maps_failures_to_form_errors(hass, client_cls, mock_setup_entry, method, error, key):
    getattr(client_cls.return_value, method).side_effect = error

    result = await _submit(hass, USER_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": key}
    client_cls.return_value.close.assert_called_once()  # the session is dropped either way


async def test_user_flow_reports_an_account_without_a_diary(hass, client_cls, mock_setup_entry):
    client_cls.return_value.get_diaries.return_value = []
    result = await _submit(hass, USER_INPUT)
    assert result["errors"] == {"base": "no_diary"}


async def test_user_flow_recovers_after_an_error(hass, client_cls, mock_setup_entry):
    client_cls.return_value.login.side_effect = EdificeAuthError("no")
    result = await _submit(hass, USER_INPUT)
    assert result["errors"] == {"base": "invalid_auth"}

    client_cls.return_value.login.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_rejects_plain_http_without_touching_the_network(hass, client_cls, mock_setup_entry):
    result = await _submit(hass, {**USER_INPUT, CONF_URL: "http://ent.example.org"})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_URL: "invalid_url"}
    client_cls.assert_not_called()


async def test_user_flow_never_offers_the_password_back(hass, client_cls, mock_setup_entry):
    client_cls.return_value.login.side_effect = EdificeAuthError("no")
    result = await _submit(hass, USER_INPUT)

    defaults = {
        str(key): key.default() if callable(key.default) else key.default
        for key in result["data_schema"].schema
        if getattr(key, "default", None) is not None
    }
    assert "secret" not in defaults.values()


@pytest.mark.parametrize("username", ["parent", " PARENT "])
async def test_user_flow_aborts_on_a_duplicate_account(hass, client_cls, mock_setup_entry, username):
    _existing_entry().add_to_hass(hass)

    result = await _submit(hass, {**USER_INPUT, CONF_USERNAME: username})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    client_cls.assert_not_called()  # no login is spent on an account we already have


# -- reauthentication ----------------------------------------------------------------


async def test_reauth_updates_the_password(hass, client_cls, mock_setup_entry):
    entry = _existing_entry()
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PASSWORD: "new"})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new"
    assert entry.data[CONF_URL] == "https://ent.example.org"  # the rest is untouched
    client_cls.assert_called_with(base_url="https://ent.example.org", username="parent", password="new")


async def test_reauth_keeps_asking_while_the_password_is_wrong(hass, client_cls, mock_setup_entry):
    entry = _existing_entry()
    entry.add_to_hass(hass)
    client_cls.return_value.login.side_effect = EdificeAuthError("no")

    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PASSWORD: "wrong"})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data[CONF_PASSWORD] == "old"


# -- translations --------------------------------------------------------------------


def _placeholders_used(step_id: str, language: str) -> set[str]:
    strings = json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8"))
    return set(re.findall(r"{(\w+)}", json.dumps(strings["config"]["step"][step_id])))


@pytest.mark.parametrize("language", ["en", "fr"])
async def test_the_user_form_supplies_every_placeholder_its_text_uses(hass, client_cls, language):
    """A missing placeholder would show up as a literal ``{example_url}`` in the form."""
    result = await _start(hass)
    assert _placeholders_used("user", language) <= set(result["description_placeholders"])


@pytest.mark.parametrize("language", ["en", "fr"])
async def test_the_reauth_form_supplies_every_placeholder_its_text_uses(hass, client_cls, language):
    entry = _existing_entry()
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert _placeholders_used("reauth_confirm", language) <= set(result["description_placeholders"])


def test_both_languages_have_the_same_keys():
    def keys(node, prefix=""):
        if not isinstance(node, dict):
            return {prefix}
        return {k for name, child in node.items() for k in keys(child, f"{prefix}.{name}")}

    en, fr = (json.loads((TRANSLATIONS / f"{lang}.json").read_text(encoding="utf-8")) for lang in ("en", "fr"))
    assert keys(en) == keys(fr)
