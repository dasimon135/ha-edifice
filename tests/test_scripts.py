"""The discovery script prints structure, never values.

It runs against a signed-in session on a real school account, and its output is meant to be
pasted into a chat. These tests feed it answers stuffed with recognisable secrets and check
that not one of them reaches the output.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "edifice_discover.py"
_spec = importlib.util.spec_from_file_location("edifice_discover", _SCRIPT)
discover = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = discover
_spec.loader.exec_module(discover)

BASE = "https://ent.example.org"
USER_ID = "USER-ID-SECRET-0123456789012345678"
CHILD_ID = "CHILD-ID-SECRET-012345678901234567"
UUID_KEY = "4ba045e5-a016-4179-98b9-6f414e893d84"

# Every one of these must stay out of the output.
SECRETS = [
    "PRENOM-SECRET",
    "ECOLE-SECRET",
    "ENFANT-SECRET",
    "CLASSE-SECRET",
    "TITRE-SECRET",
    "TEXTE-SECRET",
    "AUTEUR-SECRET",
    "DOSSIER-SECRET",
    "TOKEN-SECRET",
    "MESSAGE-SECRET",
    "EXPEDITEUR-SECRET",
    USER_ID,
    CHILD_ID,
    UUID_KEY,
]

ANSWERS = {
    "/auth/oauth2/userinfo": {"userId": USER_ID, "firstName": "PRENOM-SECRET"},
    f"/directory/user/{USER_ID}/children": [
        {
            "structureName": "ECOLE-SECRET",
            "children": [{"id": CHILD_ID, "firstName": "ENFANT-SECRET", "classesNames": ["CLASSE-SECRET"]}],
        },
        # The same child, enrolled in a second structure.
        {"structureName": "ECOLE-SECRET", "children": [{"id": CHILD_ID, "firstName": "ENFANT-SECRET"}]},
    ],
    f"/schoolbook/count/{CHILD_ID}": {"count": 3},
    f"/schoolbook/list/0/{CHILD_ID}": [
        {
            "id": 1234567,
            "title": "TITRE-SECRET",
            "text": "TEXTE-SECRET",
            "owner": {"name": "AUTEUR-SECRET"},
            UUID_KEY: {"x": 1},
        }
    ],
    "/conversation/count/inbox?unread=true": {"count": 4},
    "/conversation/api/folders?depth=1": [{"id": "DOSSIER-ID-0123456789012345", "name": "DOSSIER-SECRET"}],
    "/timeline/lastNotifications?page=0": {
        "results": [{"message": "MESSAGE-SECRET", "sender": "EXPEDITEUR-SECRET", "type": "SCHOOLBOOK"}],
        "status": "ok",
        "number": 1,
    },
    "/timeline/registeredNotifications": [
        {"type": "SCHOOLBOOK", "event-type": "NEW-WORD", "app-name": "Schoolbook", "app-address": "/schoolbook"},
        {"type": "HOMEWORKS", "event-type": "NEW-ENTRY", "app-name": "Homeworks", "app-address": "/homeworks"},
    ],
    "/timeline/types": ["SCHOOLBOOK", "HOMEWORKS"],
}


class FakeResponse:
    def __init__(self, status_code, body=None, content_type="application/json"):
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self._body = body
        self.content = json.dumps(body).encode() if content_type == "application/json" else str(body).encode()

    def json(self):
        if "json" not in self.headers["content-type"]:
            raise ValueError("not json")
        return self._body


class FakeSession:
    def __init__(self, answers, *, carbonio=True):
        self.headers = {"User-Agent": "test"}
        self.answers = dict(answers)
        self.carbonio = carbonio
        self.accept_seen: dict[str, str | None] = {}

    def get(self, url, timeout=None, allow_redirects=None):
        assert allow_redirects is False
        route = url.removeprefix(BASE)
        self.accept_seen[route] = self.headers.get("Accept")
        if route == "/auth/carbonio/token" and self.carbonio:
            return FakeResponse(200, "TOKEN-SECRET-abcdef", content_type="text/plain")
        if route in self.answers:
            return FakeResponse(200, self.answers[route])
        return FakeResponse(404, "not found", content_type="text/html")


def _run(session, capsys) -> str:
    discover.run(session, BASE)
    return capsys.readouterr().out


def test_no_value_from_the_account_reaches_the_output(capsys):
    output = _run(FakeSession(ANSWERS), capsys)

    leaked = [secret for secret in SECRETS if secret in output]
    assert not leaked, f"printed values it must not: {leaked}"


def test_it_still_reports_the_structure_and_the_status_codes(capsys):
    output = _run(FakeSession(ANSWERS), capsys)

    assert "1 child(ren)" in output  # counted once even though enrolled twice
    assert "/schoolbook/count/{id}: HTTP 200" in output
    assert "/conversation/count/inbox?unread=true: HTTP 200" in output
    assert "/auth/carbonio/token: HTTP 200" in output


def test_module_names_the_platform_registers_are_printed_because_they_are_not_personal(capsys):
    output = _run(FakeSession(ANSWERS), capsys)

    assert "type: HOMEWORKS, SCHOOLBOOK" in output
    assert "notification types: HOMEWORKS, SCHOOLBOOK" in output


def test_a_route_that_is_not_deployed_is_reported_as_404(capsys):
    answers = {k: v for k, v in ANSWERS.items() if not k.startswith("/conversation")}

    output = _run(FakeSession(answers), capsys)

    assert "/conversation/count/inbox?unread=true: HTTP 404" in output


def test_an_account_without_children_skips_the_parent_routes(capsys):
    answers = {**ANSWERS, f"/directory/user/{USER_ID}/children": []}

    output = _run(FakeSession(answers), capsys)

    assert "no child on this account" in output
    assert "/schoolbook/" not in output


def test_the_notification_feed_gets_the_version_the_app_asks_for_and_nothing_leaks_after(capsys):
    session = FakeSession(ANSWERS)

    _run(session, capsys)

    assert session.accept_seen["/timeline/lastNotifications?page=0"] == "application/json;version=3.0"
    assert session.accept_seen["/timeline/registeredNotifications"] is None
    assert "Accept" not in session.headers


def test_an_existing_accept_header_is_restored(capsys):
    session = FakeSession(ANSWERS)
    session.headers["Accept"] = "text/html"

    _run(session, capsys)

    assert session.headers["Accept"] == "text/html"


# -- helpers -------------------------------------------------------------------------


def test_child_ids_are_distinct_and_tolerate_junk():
    payload = [
        {"children": [{"id": "a"}, {"id": "b"}, "junk", {"noid": 1}]},
        {"children": [{"id": "a"}]},
        "junk",
        {"children": None},
    ]
    assert discover.child_ids(payload) == ["a", "b"]
    assert discover.child_ids("not a list") == []


def test_module_names_ignore_what_is_not_a_string():
    payload = [{"type": "X", "app-name": 3}, "junk", {"type": "Y"}]
    assert discover.module_names(payload) == {"type": ["X", "Y"]}


@pytest.mark.parametrize(
    "key",
    [UUID_KEY, "507f1f77bcf86cd799439011", "1234567"],  # a uuid, a Mongo id, a long number
)
def test_shapes_never_print_a_key_that_is_an_identifier(key):
    shape = discover.et.describe({key: {"a": 1}, "normal": "x"})

    assert key not in shape
    assert "<id>" in shape
    assert "normal" in shape


def test_ordinary_keys_survive_including_the_long_ones_the_server_uses():
    long_key = "fr-wseduc-homeworks-controllers-HomeworksController|getHomework"
    assert long_key in discover.et.describe({long_key: True})


# -- credentials ---------------------------------------------------------------------

TRICKY_PASSWORD = "P@ss\"w$rd#1'x =y "  # quotes, $, #, = and a trailing space


def _read_config(monkeypatch, tmp_path, content: str | None, **env: str):
    """Run read_config() against a fresh credentials file and a controlled environment."""
    for name in ("EDIFICE_URL", "EDIFICE_USERNAME", "EDIFICE_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / "credentials.env"
    if content is not None:
        path.write_bytes(content.encode("utf-8"))
    monkeypatch.setenv("EDIFICE_CREDENTIALS_FILE", str(path))
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return discover.et.read_config()


def test_credentials_come_from_the_file(monkeypatch, tmp_path):
    config = _read_config(
        monkeypatch,
        tmp_path,
        "EDIFICE_URL=https://ent.example.org/\nEDIFICE_USERNAME=parent\nEDIFICE_PASSWORD=secret\n",
    )

    assert (config.base_url, config.username, config.password) == ("https://ent.example.org", "parent", "secret")


def test_the_password_is_read_back_exactly(monkeypatch, tmp_path):
    content = f"EDIFICE_USERNAME=parent\nEDIFICE_PASSWORD={TRICKY_PASSWORD}\n"

    config = _read_config(monkeypatch, tmp_path, content)

    assert config.password == TRICKY_PASSWORD


def test_a_byte_order_mark_and_windows_line_endings_are_tolerated(monkeypatch, tmp_path):
    """Windows PowerShell 5 writes a BOM; Notepad and friends write CRLF."""
    content = "﻿EDIFICE_USERNAME=parent\r\nEDIFICE_PASSWORD=secret\r\n"

    config = _read_config(monkeypatch, tmp_path, content)

    assert (config.username, config.password) == ("parent", "secret")


def test_comments_and_blank_lines_are_ignored(tmp_path):
    path = tmp_path / "credentials.env"
    path.write_text(
        "# my account\n\nEDIFICE_USERNAME=parent\n  # EDIFICE_USERNAME=someone-else\nEDIFICE_PASSWORD=secret\n",
        encoding="utf-8",
    )

    # Compared as a whole: a commented-out line must not leave a stray key behind either.
    assert discover.et.read_credentials_file(path) == {
        "EDIFICE_USERNAME": "parent",
        "EDIFICE_PASSWORD": "secret",
    }


def test_a_missing_url_falls_back_to_the_default(monkeypatch, tmp_path):
    config = _read_config(monkeypatch, tmp_path, "EDIFICE_USERNAME=parent\nEDIFICE_PASSWORD=secret\n")

    assert config.base_url == discover.et.DEFAULT_URL


def test_the_environment_beats_the_file(monkeypatch, tmp_path):
    content = "EDIFICE_USERNAME=from-file\nEDIFICE_PASSWORD=from-file\n"

    config = _read_config(monkeypatch, tmp_path, content, EDIFICE_USERNAME="from-env")

    assert (config.username, config.password) == ("from-env", "from-file")


def test_without_a_file_it_asks_and_fails_cleanly_when_nobody_can_answer(monkeypatch, tmp_path):
    def nobody(*_args, **_kwargs):
        raise EOFError

    monkeypatch.setattr("builtins.input", nobody)
    monkeypatch.setattr(discover.et.getpass, "getpass", nobody)

    with pytest.raises(discover.et.ProbeError) as error:
        _read_config(monkeypatch, tmp_path, None)

    assert error.value.code == 2
    assert "credentials.env" in str(error.value)


def test_reading_the_credentials_prints_nothing(monkeypatch, tmp_path, capsys):
    _read_config(monkeypatch, tmp_path, f"EDIFICE_USERNAME=parent\nEDIFICE_PASSWORD={TRICKY_PASSWORD}\n")

    captured = capsys.readouterr()

    assert captured.out == "" and captured.err == ""


def test_the_default_location_is_in_the_users_config_folder_not_in_a_project():
    """The README tells people to create the file there, so it must not drift."""
    assert discover.et.CREDENTIALS_FILE == Path.home() / ".config" / "ha-edifice" / "credentials.env"


# -- printed routes ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("route", "printed"),
    [
        (f"/schoolbook/count/{CHILD_ID}", "/schoolbook/count/{id}"),
        (f"/directory/user/{UUID_KEY}/children", "/directory/user/{id}/children"),
        # A long route name is not an identifier: it has neither a digit nor a hyphen.
        ("/timeline/registeredNotifications", "/timeline/registeredNotifications"),
        ("/timeline/lastNotifications?page=0", "/timeline/lastNotifications?page=0"),
        ("/conversation/count/inbox?unread=true", "/conversation/count/inbox?unread=true"),
    ],
)
def test_redact_hides_identifiers_and_keeps_route_names(route, printed):
    assert discover.et.redact(route) == printed
