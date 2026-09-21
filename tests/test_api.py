"""Offline tests for the homework client.

The fixtures below reproduce the payload shape observed on a live Paris Classe
Numerique account on 2026-09-20: MongoDB extended JSON for record timestamps
(``{"$date": ...}``) but a plain ``YYYY-MM-DD`` string for the day buckets.
"""

from __future__ import annotations

import datetime
import importlib.util
import sys
from pathlib import Path

import pytest
import requests

# api.py is loaded by path, under a name of its own, so that this file needs no Home
# Assistant install and never creates a second copy of the classes the integration uses.
_API_PATH = Path(__file__).resolve().parent.parent / "custom_components" / "edifice" / "api.py"
_spec = importlib.util.spec_from_file_location("edifice_api_standalone", _API_PATH)
_api = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _api  # dataclasses resolve string annotations through here
_spec.loader.exec_module(_api)

EdificeAuthError = _api.EdificeAuthError
EdificeClient = _api.EdificeClient
EdificeError = _api.EdificeError
EdificePlatformError = _api.EdificePlatformError
EdificeUnavailable = _api.EdificeUnavailable
html_to_text = _api.html_to_text

DIARY_ID = "11111111-2222-3333-4444-555555555555"

DIARY_LIST = [
    {
        "_id": DIARY_ID,
        "title": "Cahier CM1",
        "name": "Cahier CM1",
        "trashed": 0,
        "entriesModified": {"$date": "2026-09-19T17:04:11.000Z"},
        "owner": {"userId": "x", "displayName": "y"},
    },
    {"_id": "trashed-one", "title": "Ancien", "trashed": 1},
]

DIARY_CONTENT = {
    "_id": DIARY_ID,
    "title": "Cahier CM1",
    "entriesModified": {"$date": "2026-09-19T17:04:11.000Z"},
    "data": [
        {
            "date": "2026-09-21",
            "entries": [
                {"_id": "e1", "title": "Mathematiques", "value": "<p>Exercices 3 et 4</p>"},
                {"_id": "e2", "title": "Français", "value": "Lire <b>le chapitre 2</b>"},
            ],
        },
        {"date": "2026-09-22", "entries": [{"_id": "e3", "title": "Histoire", "value": ""}]},
        {"date": "not-a-date", "entries": [{"_id": "e4", "title": "Ignored", "value": "x"}]},
        {"date": "2026-09-23", "entries": "not-a-list"},
        {"date": "2026-09-24", "entries": [None, 42, {"_id": "e5", "title": "SVT", "value": "ok"}]},
    ],
}


class FakeCookies(dict):
    def get(self, name, default=None):
        return super().get(name, default)


class FakeResponse:
    def __init__(self, status_code, payload=None, content_type="application/json"):
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    """Stand-in for requests.Session, driven by a queue of scripted responses."""

    def __init__(self):
        self.headers = {}
        self.cookies = FakeCookies()
        self.posts = []
        self.gets = []
        self.get_responses = {}
        self.post_response = FakeResponse(302)
        self.grant_cookie_on_login = True

    def post(self, url, data=None, timeout=None, allow_redirects=None):
        assert allow_redirects is False, "login must not follow redirects"
        self.posts.append((url, data))
        if self.grant_cookie_on_login:
            self.cookies["oneSessionId"] = "fake"
        return self.post_response

    def get(self, url, timeout=None, allow_redirects=None):
        assert allow_redirects is False, "API calls must not follow redirects"
        self.gets.append(url)
        route = url.split("example.org", 1)[-1]
        response = self.get_responses.get(route)
        if response is None:
            return FakeResponse(404, content_type="text/html")
        if isinstance(response, list):
            response = response.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        pass


def make_client(**kwargs):
    session = FakeSession()
    session.get_responses = {
        "/homeworks/list": FakeResponse(200, DIARY_LIST),
        f"/homeworks/get/{DIARY_ID}": FakeResponse(200, DIARY_CONTENT),
    }
    client = EdificeClient(
        base_url="https://example.org", username="u", password="p", _session=session, **kwargs
    )
    return client, session


# -- rich text -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("markup", "expected"),
    [
        ("<p>Exercices 3 et 4</p>", "Exercices 3 et 4"),
        ("Lire <b>le chapitre 2</b>", "Lire le chapitre 2"),
        ("a<br>b", "a\nb"),
        ("<p>a</p><p>b</p>", "a\nb"),
        ("&eacute;t&eacute;", "été"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_html_to_text(markup, expected):
    assert html_to_text(markup) == expected


# -- diaries -------------------------------------------------------------------------


def test_get_diaries_skips_trashed_and_reads_timestamp():
    client, _ = make_client()
    diaries = client.get_diaries()
    assert [d.diary_id for d in diaries] == [DIARY_ID]
    assert diaries[0].title == "Cahier CM1"
    assert diaries[0].entries_modified == datetime.datetime(
        2026, 9, 19, 17, 4, 11, tzinfo=datetime.UTC
    )


# -- homework parsing ----------------------------------------------------------------


def test_get_homework_parses_days_and_entries():
    client, _ = make_client()
    homework = client.get_homework()
    assert [(hw.date.isoformat(), hw.subject) for hw in homework] == [
        ("2026-09-21", "Français"),
        ("2026-09-21", "Mathematiques"),
        ("2026-09-22", "Histoire"),
        ("2026-09-24", "SVT"),
    ]


def test_get_homework_strips_markup_and_keeps_raw():
    client, _ = make_client()
    maths = next(hw for hw in client.get_homework() if hw.subject == "Mathematiques")
    assert maths.content_html == "<p>Exercices 3 et 4</p>"
    assert maths.content_text == "Exercices 3 et 4"


def test_malformed_records_are_skipped_not_fatal():
    """An unreadable day, a non-list entries field and junk entries must not raise."""
    client, _ = make_client()
    subjects = {hw.subject for hw in client.get_homework()}
    assert "Ignored" not in subjects  # day with an unparseable date
    assert "SVT" in subjects  # survived None and 42 in the same list


def test_unknown_fields_are_ignored():
    client, session = make_client()
    payload = dict(DIARY_CONTENT)
    payload["somethingNew"] = {"nested": [1, 2]}
    payload["data"] = [
        {"date": "2026-09-21", "entries": [{"_id": "e1", "title": "M", "value": "v", "extra": 1}]}
    ]
    session.get_responses[f"/homeworks/get/{DIARY_ID}"] = FakeResponse(200, payload)
    assert len(client.get_homework()) == 1


def test_date_filtering_is_inclusive():
    client, _ = make_client()
    got = client.get_homework(
        since=datetime.date(2026, 9, 22), until=datetime.date(2026, 9, 24)
    )
    assert [hw.date.isoformat() for hw in got] == ["2026-09-22", "2026-09-24"]


def test_as_dict_is_serialisable():
    client, _ = make_client()
    item = client.get_homework()[0].as_dict()
    assert set(item) == {"date", "subject", "content", "entry_id", "diary"}
    assert item["date"] == "2026-09-21"


# -- authentication ------------------------------------------------------------------


def test_login_rejects_credentials_on_200():
    client, session = make_client()
    session.post_response = FakeResponse(200, content_type="text/html")
    session.grant_cookie_on_login = False
    with pytest.raises(EdificeAuthError):
        client.login()


def test_login_without_cookie_is_a_platform_error():
    """A 302 that sets no cookie means federation, password renewal or CGU."""
    client, session = make_client()
    session.grant_cookie_on_login = False
    with pytest.raises(EdificePlatformError):
        client.login()


def test_expired_session_reauthenticates_exactly_once():
    client, session = make_client()
    session.get_responses["/homeworks/list"] = [
        FakeResponse(302, content_type="text/html"),  # expired
        FakeResponse(200, DIARY_LIST),  # after re-login
    ]
    client.get_diaries()
    assert len(session.posts) == 2, "expected one initial login and one re-login"


def test_second_redirect_raises_instead_of_looping():
    client, session = make_client()
    session.get_responses["/homeworks/list"] = [
        FakeResponse(302, content_type="text/html"),
        FakeResponse(302, content_type="text/html"),
    ]
    with pytest.raises(EdificeAuthError):
        client.get_diaries()
    assert len(session.posts) == 2, "must not keep logging in"


def test_missing_module_is_a_platform_error():
    client, session = make_client()
    session.get_responses = {}
    client.login()
    with pytest.raises(EdificePlatformError):
        client.get_diaries()


# -- platform probe ------------------------------------------------------------------


def test_check_platform_accepts_a_json_object():
    client, session = make_client()
    session.get_responses["/auth/context"] = FakeResponse(200, {"cgu": True, "passwordRegex": "x"})
    client.check_platform()  # must not raise


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(404, content_type="text/html"),
        FakeResponse(200, content_type="text/html"),  # catch-all single-page app
        FakeResponse(200, ["not", "an", "object"]),
    ],
)
def test_check_platform_rejects_hosts_that_are_not_edifice(response):
    client, session = make_client()
    session.get_responses["/auth/context"] = response
    with pytest.raises(EdificePlatformError):
        client.check_platform()


def test_check_platform_reports_server_errors_as_unavailable():
    client, session = make_client()
    session.get_responses["/auth/context"] = FakeResponse(502, content_type="text/html")
    with pytest.raises(EdificeUnavailable):
        client.check_platform()


def test_check_platform_reports_network_errors_as_unavailable():
    client, session = make_client()
    session.get_responses["/auth/context"] = requests.ConnectionError("boom")
    with pytest.raises(EdificeUnavailable):
        client.check_platform()


# -- request economy and configuration -----------------------------------------------


def test_get_homework_reuses_diaries_it_is_given():
    client, session = make_client()
    diaries = client.get_diaries()
    session.gets.clear()
    client.get_homework(diaries=diaries)
    assert not any(url.endswith("/homeworks/list") for url in session.gets)


def test_client_has_no_default_url():
    """A baked-in default would quietly send someone's password to the wrong ENT."""
    with pytest.raises(TypeError):
        EdificeClient(username="u", password="p")


# -- children, cahier de liaison and mailbox -----------------------------------------

ME = "11111111-aaaa-bbbb-cccc-000000000001"
OTHER_PARENT = "11111111-aaaa-bbbb-cccc-000000000002"
CHILD_A = "22222222-aaaa-bbbb-cccc-00000000000a"
CHILD_B = "22222222-aaaa-bbbb-cccc-00000000000b"

USERINFO = {"userId": ME, "firstName": "Parent"}
CHILDREN = [
    {"structureName": "Ecole 1", "children": [{"id": CHILD_A, "firstName": "Lea", "displayName": "Lea Dupont"}]},
    {
        "structureName": "Ecole 2",
        "children": [
            {"id": CHILD_A, "firstName": "Lea"},  # the same child, enrolled twice
            {"id": CHILD_B, "displayName": "Tom Martin"},  # no first name
        ],
    },
]


def _word(word_id, sent, acknowledged_by=(), **extra):
    return {
        "id": word_id,
        "title": f"Titre {word_id}",
        "text": "TEXT-THAT-MUST-NEVER-BE-KEPT",
        "sending_date": sent,
        "category": "NOTE",
        "owner_name": "M. Durand",
        "acknowledgments": [{"id": i, "owner": owner, "parent_name": "x"} for i, owner in enumerate(acknowledged_by)],
        **extra,
    }


def routes(client_session, **payloads):
    for route, payload in payloads.items():
        client_session.get_responses[route] = FakeResponse(200, payload)


def test_the_user_id_is_read_once_and_reused():
    client, session = make_client()
    routes(session, **{"/auth/oauth2/userinfo": USERINFO, f"/directory/user/{ME}/children": CHILDREN})

    client.get_children()
    client.get_children()

    assert sum(url.endswith("/auth/oauth2/userinfo") for url in session.gets) == 1


def test_get_children_lists_each_child_once_and_names_them():
    client, session = make_client()
    routes(session, **{"/auth/oauth2/userinfo": USERINFO, f"/directory/user/{ME}/children": CHILDREN})

    children = client.get_children()

    assert [(c.child_id, c.first_name) for c in children] == [(CHILD_A, "Lea"), (CHILD_B, "Tom Martin")]


def test_get_children_tolerates_junk():
    client, session = make_client()
    routes(
        session,
        **{
            "/auth/oauth2/userinfo": USERINFO,
            f"/directory/user/{ME}/children": ["junk", {"children": None}, {"children": ["junk", {"id": 5}]}],
        },
    )

    assert client.get_children() == []


@pytest.mark.parametrize("payload", [{}, {"userId": ""}, {"userId": 3}, ["not", "a", "dict"]])
def test_an_unreadable_userinfo_is_an_error_not_a_guess(payload):
    client, session = make_client()
    routes(session, **{"/auth/oauth2/userinfo": payload})

    with pytest.raises(EdificeError):
        client.get_children()


def test_get_unread_words_reads_the_counter():
    client, session = make_client()
    routes(session, **{f"/schoolbook/count/{CHILD_A}": {"unread_words": 3}})

    assert client.get_unread_words(CHILD_A) == 3


@pytest.mark.parametrize("payload", [{}, {"unread_words": "3"}, {"unread_words": -1}, {"unread_words": True}, [3]])
def test_get_unread_words_rejects_an_unexpected_payload(payload):
    client, session = make_client()
    routes(session, **{f"/schoolbook/count/{CHILD_A}": payload})

    with pytest.raises(EdificeError):
        client.get_unread_words(CHILD_A)


def test_a_platform_without_the_module_is_reported_as_such():
    client, _ = make_client()  # every unknown route answers 404

    with pytest.raises(EdificePlatformError):
        client.get_unread_words(CHILD_A)
    with pytest.raises(EdificePlatformError):
        client.get_unread_messages()


def test_get_words_marks_only_my_own_acknowledgment():
    client, session = make_client()
    routes(
        session,
        **{
            "/auth/oauth2/userinfo": USERINFO,
            f"/schoolbook/list/0/{CHILD_A}": [
                _word(1, "2026-09-17 10:00:00.000", acknowledged_by=[ME]),
                _word(2, "2026-09-18 10:00:00.000", acknowledged_by=[OTHER_PARENT]),
                _word(3, "2026-09-19 10:00:00.000"),
            ],
        },
    )

    words = client.get_words(CHILD_A)

    assert {w.word_id: w.acknowledged for w in words} == {1: True, 2: False, 3: False}


def test_get_words_sorts_newest_first_whatever_the_server_order():
    client, session = make_client()
    routes(
        session,
        **{
            "/auth/oauth2/userinfo": USERINFO,
            f"/schoolbook/list/0/{CHILD_A}": [
                _word(1, "2026-09-17 10:00:00.000"),
                _word(3, "2026-09-19 10:00:00.000"),
                _word(2, "2026-09-18 10:00:00.000"),
                _word(4, "not a date"),
            ],
        },
    )

    assert [w.word_id for w in client.get_words(CHILD_A)] == [3, 2, 1, 4]


@pytest.mark.parametrize(
    "sent",
    ["2026-09-17 10:12:33.123", "2026-09-17T10:12:33.123", "2026-09-17T10:12:33", "2026-09-17T10:12:33.123Z"],
)
def test_the_sending_date_is_read_in_the_formats_the_server_may_use(sent):
    client, session = make_client()
    routes(session, **{"/auth/oauth2/userinfo": USERINFO, f"/schoolbook/list/0/{CHILD_A}": [_word(1, sent)]})

    [word] = client.get_words(CHILD_A)

    assert word.as_dict()["date"] == "2026-09-17"


def test_an_aware_and_a_naive_date_can_be_sorted_together():
    client, session = make_client()
    routes(
        session,
        **{
            "/auth/oauth2/userinfo": USERINFO,
            f"/schoolbook/list/0/{CHILD_A}": [_word(1, "2026-09-17T10:00:00+02:00"), _word(2, "2026-09-18 10:00:00")],
        },
    )

    assert [w.word_id for w in client.get_words(CHILD_A)] == [2, 1]


def test_the_text_of_a_word_is_never_kept():
    client, session = make_client()
    routes(
        session,
        **{"/auth/oauth2/userinfo": USERINFO, f"/schoolbook/list/0/{CHILD_A}": [_word(1, "2026-09-17 10:00:00")]},
    )

    [word] = client.get_words(CHILD_A)

    assert "TEXT-THAT-MUST-NEVER-BE-KEPT" not in repr(word) + repr(word.as_dict())
    assert set(word.as_dict()) == {"id", "title", "date", "sender", "category", "acknowledged"}


def test_get_words_tolerates_junk_entries():
    client, session = make_client()
    routes(
        session,
        **{
            "/auth/oauth2/userinfo": USERINFO,
            f"/schoolbook/list/0/{CHILD_A}": [
                None,
                42,
                {"title": "no id"},
                {"id": True},
                _word(7, "2026-09-17 10:00:00"),
            ],
        },
    )

    assert [w.word_id for w in client.get_words(CHILD_A)] == [7]


def test_get_words_rejects_a_payload_that_is_not_a_list():
    client, session = make_client()
    routes(session, **{"/auth/oauth2/userinfo": USERINFO, f"/schoolbook/list/0/{CHILD_A}": {"oops": 1}})

    with pytest.raises(EdificeError):
        client.get_words(CHILD_A)


def test_get_unread_messages_reads_the_counter():
    client, session = make_client()
    routes(session, **{"/conversation/count/inbox?unread=true": {"count": 4}})

    assert client.get_unread_messages() == 4


@pytest.mark.parametrize("payload", [{}, {"count": "4"}, {"count": -2}, {"count": False}, 4])
def test_get_unread_messages_rejects_an_unexpected_payload(payload):
    client, session = make_client()
    routes(session, **{"/conversation/count/inbox?unread=true": payload})

    with pytest.raises(EdificeError):
        client.get_unread_messages()
