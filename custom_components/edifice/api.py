"""Minimal client for the homework module of an Edifice-based ENT.

The server side of this module (``fr.wseduc.homeworks``) is not open source, so every
route and field name here was established by observing the official mobile client and a
live platform. Parsing is therefore deliberately tolerant: unknown fields are ignored and
malformed records are skipped rather than raising, because the payload can gain a field
at any time without warning.

Two rules that the ENT imposes and that this client must never break:

* Redirects are never followed. A failed login answers ``200`` with the login page, and
  an expired session answers ``302`` to that same page -- a client that follows redirects
  reads an HTML login form as if it were data. See ``docs/session.md``.
* A failed re-authentication is final. One re-login, one retry, then raise. Repeated
  failed logins are what gets an ENT account restricted.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

import requests

_LOGGER = logging.getLogger(__name__)

SESSION_COOKIE = "oneSessionId"
USER_AGENT = "ha-edifice/0.1 (+https://github.com/dasimon135/ha-edifice)"
TIMEOUT = 20

_REDIRECTS = (301, 302, 303, 307, 308)


class EdificeError(Exception):
    """Base class for every failure this client reports."""


class EdificeAuthError(EdificeError):
    """Credentials were rejected. Never retry on this one."""


class EdificeUnavailable(EdificeError):
    """Network failure or server error. Retrying later is reasonable."""


class EdificePlatformError(EdificeError):
    """The host is not a usable Edifice platform, or needs a flow we do not implement."""


@dataclass(frozen=True)
class Diary:
    """A homework diary, which belongs to a class rather than to one child."""

    diary_id: str
    title: str
    # Server-side timestamp of the last content change. Comparing it between polls tells
    # the coordinator whether re-fetching the entries is worth it at all.
    entries_modified: datetime.datetime | None = None


@dataclass(frozen=True)
class Homework:
    """One piece of homework, on one day, for one subject."""

    date: datetime.date
    subject: str
    content_html: str
    content_text: str
    entry_id: str
    diary_id: str
    diary_title: str

    def as_dict(self) -> dict[str, Any]:
        """Serialise for a Home Assistant state attribute."""
        return {
            "date": self.date.isoformat(),
            "subject": self.subject,
            "content": self.content_text,
            "entry_id": self.entry_id,
            "diary": self.diary_title,
        }


class _TextExtractor(HTMLParser):
    """Turn the stored rich text into something a notification can read aloud."""

    _BLOCK = {"br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._BLOCK:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._BLOCK:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def text(self) -> str:
        lines = (line.strip() for line in "".join(self._parts).splitlines())
        return "\n".join(line for line in lines if line).strip()


def html_to_text(value: str) -> str:
    """Strip markup, collapse blank lines, and keep paragraph breaks."""
    if not value:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(value)
        parser.close()
    except Exception:  # malformed markup must never break a refresh
        _LOGGER.debug("could not parse rich text, falling back to raw value")
        return value.strip()
    return parser.text()


def _unwrap_date(value: Any) -> datetime.datetime | None:
    """Read MongoDB extended JSON: ``{"$date": "2026-09-01T12:00:00.000Z"}``."""
    if isinstance(value, dict):
        value = value.get("$date")
    if not isinstance(value, str):
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_day(value: Any) -> datetime.date | None:
    """Read the plain ``YYYY-MM-DD`` used by day buckets -- not ``$date`` wrapped."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.date.fromisoformat(value[:10])
    except ValueError:
        return None


@dataclass
class EdificeClient:
    """Session-cookie client for the Edifice homework module.

    Not thread-safe, and blocking. Home Assistant callers must run it in an executor.
    """

    # No default URL on purpose: this client serves every Edifice platform, and a
    # baked-in default would quietly point someone's credentials at the wrong ENT.
    base_url: str
    username: str
    password: str
    _session: requests.Session = field(default_factory=requests.Session, repr=False)
    _logged_in: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self._session.headers["User-Agent"] = USER_AGENT

    # -- authentication ------------------------------------------------------------

    def check_platform(self) -> None:
        """Confirm the host is an Edifice platform. Needs no credentials.

        ``/auth/context`` is public and answers JSON on every Edifice platform probed.
        Other hosts answer 404, or an HTML page for a catch-all single-page app.
        """
        url = f"{self.base_url}/auth/context"
        try:
            response = self._session.get(url, timeout=TIMEOUT, allow_redirects=False)
        except requests.RequestException as exc:
            raise EdificeUnavailable(f"cannot reach {url}: {exc}") from exc

        if response.status_code >= 500:
            raise EdificeUnavailable(f"{url} returned {response.status_code}")
        if response.status_code != 200 or "json" not in response.headers.get("content-type", ""):
            raise EdificePlatformError(f"{url} does not look like an Edifice platform")
        try:
            payload = response.json()
        except ValueError as exc:
            raise EdificePlatformError(f"{url} did not return JSON") from exc
        if not isinstance(payload, dict):
            raise EdificePlatformError(f"{url} did not return a JSON object")

    def login(self) -> None:
        """Authenticate once. Raises rather than retrying."""
        url = f"{self.base_url}/auth/login"
        payload = {"email": self.username, "password": self.password, "callBack": f"{self.base_url}/"}
        try:
            response = self._session.post(url, data=payload, timeout=TIMEOUT, allow_redirects=False)
        except requests.RequestException as exc:
            raise EdificeUnavailable(f"login request failed: {exc}") from exc

        if response.status_code == 200:
            # entcore re-serves the login page instead of redirecting.
            raise EdificeAuthError("credentials rejected")
        if response.status_code not in _REDIRECTS:
            raise EdificePlatformError(f"unexpected status {response.status_code} from {url}")
        if not self._session.cookies.get(SESSION_COOKIE):
            raise EdificePlatformError(
                "logged in without a session cookie: the platform is federated, or is "
                "asking for a password change or terms acceptance that must be cleared "
                "in a browser first"
            )
        self._logged_in = True
        _LOGGER.debug("session established on %s", self.base_url)

    def close(self) -> None:
        self._session.close()
        self._logged_in = False

    # -- requests ------------------------------------------------------------------

    def _get_json(self, route: str) -> Any:
        """GET a route, re-authenticating at most once if the session has expired."""
        if not self._logged_in:
            self.login()

        response = self._request(route)
        if response.status_code in _REDIRECTS:
            _LOGGER.debug("session expired, re-authenticating once")
            self._logged_in = False
            self.login()
            response = self._request(route)
            if response.status_code in _REDIRECTS:
                raise EdificeAuthError("session rejected immediately after re-authenticating")

        if response.status_code == 404:
            raise EdificePlatformError(f"{route} is not deployed on this platform")
        if response.status_code >= 500:
            raise EdificeUnavailable(f"{route} returned {response.status_code}")
        if response.status_code != 200:
            raise EdificeError(f"{route} returned {response.status_code}")
        if "json" not in response.headers.get("content-type", ""):
            raise EdificeError(f"{route} returned {response.headers.get('content-type')}, not JSON")

        try:
            return response.json()
        except ValueError as exc:
            raise EdificeError(f"{route} returned unparseable JSON") from exc

    def _request(self, route: str) -> requests.Response:
        try:
            return self._session.get(f"{self.base_url}{route}", timeout=TIMEOUT, allow_redirects=False)
        except requests.RequestException as exc:
            raise EdificeUnavailable(f"{route} failed: {exc}") from exc

    # -- public API ----------------------------------------------------------------

    def get_diaries(self) -> list[Diary]:
        """List the homework diaries this account can read, excluding trashed ones."""
        payload = self._get_json("/homeworks/list")
        if not isinstance(payload, list):
            raise EdificeError("/homeworks/list did not return a list")

        diaries: list[Diary] = []
        for raw in payload:
            if not isinstance(raw, dict) or raw.get("trashed"):
                continue
            diary_id = raw.get("_id")
            if not isinstance(diary_id, str):
                continue
            diaries.append(
                Diary(
                    diary_id=diary_id,
                    title=str(raw.get("title") or raw.get("name") or "").strip() or "Cahier de textes",
                    entries_modified=_unwrap_date(raw.get("entriesModified")),
                )
            )
        return diaries

    def get_homework(
        self,
        since: datetime.date | None = None,
        until: datetime.date | None = None,
        diaries: list[Diary] | None = None,
    ) -> list[Homework]:
        """Return homework across every readable diary, sorted by date then subject.

        ``since`` and ``until`` are inclusive; both default to no bound. Pass ``diaries``
        when you already hold the list, to save a request.
        """
        items: list[Homework] = []
        for diary in diaries if diaries is not None else self.get_diaries():
            items.extend(self._homework_for(diary, since, until))
        items.sort(key=lambda hw: (hw.date, hw.subject.lower()))
        return items

    # -- parsing -------------------------------------------------------------------

    def _homework_for(
        self,
        diary: Diary,
        since: datetime.date | None,
        until: datetime.date | None,
    ) -> list[Homework]:
        payload = self._get_json(f"/homeworks/get/{diary.diary_id}")
        if not isinstance(payload, dict):
            _LOGGER.warning("diary %s did not return an object; skipping", diary.diary_id)
            return []

        days = payload.get("data")
        if not isinstance(days, list):
            _LOGGER.warning("diary %s has no 'data' list; skipping", diary.diary_id)
            return []

        items: list[Homework] = []
        for day in days:
            if not isinstance(day, dict):
                continue
            when = _parse_day(day.get("date"))
            if when is None:
                _LOGGER.debug("skipping day with unreadable date %r", day.get("date"))
                continue
            if (since and when < since) or (until and when > until):
                continue
            for entry in day.get("entries") or []:
                parsed = self._parse_entry(entry, when, diary)
                if parsed is not None:
                    items.append(parsed)
        return items

    @staticmethod
    def _parse_entry(entry: Any, when: datetime.date, diary: Diary) -> Homework | None:
        if not isinstance(entry, dict):
            return None
        raw_value = entry.get("value")
        content_html = raw_value if isinstance(raw_value, str) else ""
        subject = entry.get("title")
        return Homework(
            date=when,
            subject=str(subject).strip() if isinstance(subject, str) else "",
            content_html=content_html,
            content_text=html_to_text(content_html),
            entry_id=str(entry.get("_id") or ""),
            diary_id=diary.diary_id,
            diary_title=diary.title,
        )
