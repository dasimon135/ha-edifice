#!/usr/bin/env python3
"""Standalone login probe for an Edifice-based ENT (formerly Open ENT NG / CGI OpenENT).

This script does three things and nothing else:

1. Confirms the target host really is an Edifice platform (no credentials needed).
2. Performs the entcore form login and reports whether a usable session was obtained.
3. Probes a handful of read-only endpoints and prints the *shape* of what they
   return -- keys and types only, never values.

Point 3 matters: the cahier de textes module (``homeworks``) has no public server
source, so its response format has to be established empirically. Printing the
schema rather than the content keeps a child's school data out of the terminal,
out of logs, and out of any transcript.

Credentials are read from the environment, or prompted for interactively if the
environment does not carry them. They are never written to the output.

    EDIFICE_URL       base URL of the ENT (default: https://ent.parisclassenumerique.fr)
    EDIFICE_USERNAME  login (prompted if unset)
    EDIFICE_PASSWORD  password (prompted without echo if unset -- preferred)

Exactly one login attempt is made. There is no retry loop, by design.

Pass ``--watch`` to measure how long the session survives: the script then re-checks
the identity route at a fixed interval until the server stops accepting the cookie,
and prints the measured lifetime. It never re-authenticates.

Exit codes:
    0  session established
    1  authentication rejected
    2  configuration error
    3  platform error, network error, or a login flow this script does not handle
"""

from __future__ import annotations

import getpass
import os
import re
import sys
import urllib.parse
from dataclasses import dataclass
from typing import Any

import requests

# Any path segment that looks like an opaque identifier, so printed URLs carry none.
_ID_SEGMENT = re.compile(r"/[A-Za-z0-9_-]{20,}")

DEFAULT_URL = "https://ent.parisclassenumerique.fr"
SESSION_COOKIE = "oneSessionId"
USER_AGENT = "ha-edifice-probe/0.1 (+https://github.com/dasimon135/ha-edifice)"
TIMEOUT = 20

# Tried in order until one returns JSON identifying the current user.
WHOAMI_ROUTES = ("/auth/oauth2/userinfo", "/userbook/api/person", "/directory/user/current")


@dataclass(frozen=True)
class Config:
    base_url: str
    username: str
    password: str


class ProbeError(Exception):
    """Fatal condition, carrying the exit code to use."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


def read_config() -> Config:
    base_url = os.environ.get("EDIFICE_URL", DEFAULT_URL).rstrip("/")
    if not base_url.startswith("https://"):
        raise ProbeError(f"EDIFICE_URL must be an https URL, got {base_url!r}", 2)

    try:
        username = os.environ.get("EDIFICE_USERNAME") or input("ENT login: ").strip()
        password = os.environ.get("EDIFICE_PASSWORD") or getpass.getpass("ENT password: ")
    except (EOFError, KeyboardInterrupt):
        raise ProbeError(
            "no credentials on stdin. Set EDIFICE_USERNAME and EDIFICE_PASSWORD, "
            "or run this from an interactive terminal.",
            2,
        ) from None

    if not username:
        raise ProbeError("no username supplied", 2)
    if not password:
        raise ProbeError("no password supplied", 2)

    return Config(base_url=base_url, username=username, password=password)


# A dict key that is itself an identifier (uuid, Mongo id, long number) must not be printed.
_ID_KEY = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|[0-9a-fA-F]{24}|\d{5,}"
)


def _safe_key(key: Any) -> str:
    text = str(key)
    return "<id>" if _ID_KEY.fullmatch(text) else text


def describe(value: Any, depth: int = 0, max_keys: int = 25) -> Any:
    """Return the structure of a JSON value, with every scalar replaced by its type.

    No leaf value ever survives this function, so the result is safe to print.
    """
    if depth > 4:
        return "..."
    if isinstance(value, dict):
        keys = list(value)[:max_keys]
        shape = {_safe_key(k): describe(value[k], depth + 1) for k in keys}
        if len(value) > max_keys:
            shape["..."] = f"+{len(value) - max_keys} more keys"
        return shape
    if isinstance(value, list):
        if not value:
            return "[] (empty)"
        return [f"list of {len(value)}", describe(value[0], depth + 1)]
    if isinstance(value, str):
        return f"str({len(value)})"
    if isinstance(value, bool):
        return "bool"
    if value is None:
        return "null"
    return type(value).__name__


def dump(label: str, value: Any, indent: int = 2) -> None:
    import json

    print(f"{' ' * indent}{label}:")
    text = json.dumps(describe(value), indent=2, ensure_ascii=False)
    for line in text.splitlines():
        print(f"{' ' * (indent + 2)}{line}")


def check_platform(session: requests.Session, base_url: str) -> None:
    """GET /auth/context -- public, and the cheapest proof the host runs Edifice."""
    url = f"{base_url}/auth/context"
    try:
        response = session.get(url, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise ProbeError(f"cannot reach {url}: {exc}", 3) from exc

    if _looks_blocked(response):
        raise ProbeError(
            f"{url} returned {response.status_code} and looks like a bot-protection "
            "challenge. Stop here -- do not try to work around it.",
            3,
        )
    if response.status_code != 200 or "json" not in response.headers.get("content-type", ""):
        raise ProbeError(
            f"{url} returned {response.status_code} ({response.headers.get('content-type')}). "
            "This host does not look like an Edifice platform.",
            3,
        )

    context = response.json()
    print(f"  platform  : Edifice confirmed ({url})")
    print(f"  cgu       : {context.get('cgu')}")
    print(f"  pwd policy: {context.get('passwordRegex', '(none)')[:60]}")


def login(session: requests.Session, config: Config) -> None:
    """One POST to /auth/login. Success is a 302 that sets the session cookie."""
    url = f"{config.base_url}/auth/login"
    payload = {
        "email": config.username,
        "password": config.password,
        "callBack": config.base_url + "/",
    }
    try:
        response = session.post(url, data=payload, timeout=TIMEOUT, allow_redirects=False)
    except requests.RequestException as exc:
        raise ProbeError(f"login request failed: {exc}", 3) from exc

    if _looks_blocked(response):
        raise ProbeError(
            f"login returned {response.status_code} and looks like a bot-protection "
            "challenge. Stop here -- do not try to work around it.",
            3,
        )

    cookie = session.cookies.get(SESSION_COOKIE)
    location = response.headers.get("location", "")

    if response.status_code == 200:
        # entcore re-renders the login page instead of redirecting.
        raise ProbeError("credentials rejected (login page was re-served)", 1)

    if response.status_code not in (301, 302, 303, 307, 308):
        raise ProbeError(f"unexpected status {response.status_code} from {url}", 3)

    if not cookie:
        target_host = urllib.parse.urlsplit(location).netloc
        base_host = urllib.parse.urlsplit(config.base_url).netloc
        if target_host and target_host != base_host:
            raise ProbeError(
                f"login redirected to another host ({target_host}). This platform "
                "federates authentication (CAS / EduConnect / SAML) and needs a "
                "different flow than the entcore form login.",
                3,
            )
        raise ProbeError(
            f"redirected to {location or '(no location)'} without a {SESSION_COOKIE} "
            "cookie. Likely a forced password renewal, an activation step, or a CGU "
            "acceptance page that must be cleared in a browser first.",
            3,
        )

    print(f"  login     : accepted (HTTP {response.status_code} -> {location or '/'})")
    _report_cookie(session)


def _report_cookie(session: requests.Session) -> None:
    """Print what the server declares about the session cookie, never its value."""
    for cookie in session.cookies:
        if cookie.name != SESSION_COOKIE:
            continue
        value = cookie.value or ""
        fingerprint = f"{value[:4]}...{value[-4:]} ({len(value)} chars)" if value else "(empty)"
        expires = "session cookie (no expiry sent)" if cookie.expires is None else str(cookie.expires)
        print(f"  cookie    : {SESSION_COOKIE}={fingerprint}")
        print(f"  declared  : expires={expires} secure={cookie.secure} domain={cookie.domain}")
        return


def whoami(session: requests.Session, base_url: str) -> tuple[str, dict[str, Any] | None] | None:
    """Find an endpoint that identifies the session. Returns (route, payload)."""
    for route in WHOAMI_ROUTES:
        response = _get(session, base_url, route)
        if response is None:
            continue
        if response.status_code == 200 and "json" in response.headers.get("content-type", ""):
            payload = response.json()
            print(f"  session   : confirmed active via {route}")
            dump(route, payload)
            return route, payload if isinstance(payload, dict) else None
        print(f"  {route}: HTTP {response.status_code} ({response.headers.get('content-type')})")
    return None


def watch(session: requests.Session, base_url: str, route: str, interval_min: int, max_hours: int) -> None:
    """Re-check the identity route until the session dies, then report its lifetime.

    This never logs in again -- it only observes an existing session expiring.
    """
    import time

    started = time.monotonic()
    deadline = started + max_hours * 3600
    print(
        f"\n=== watching {route} every {interval_min} min (max {max_hours}h) ===\n"
        "Leave this running. Ctrl-C to stop early."
    )
    try:
        while time.monotonic() < deadline:
            time.sleep(interval_min * 60)
            elapsed = (time.monotonic() - started) / 60
            response = _get(session, base_url, route)
            status = "request failed" if response is None else f"HTTP {response.status_code}"
            alive = response is not None and response.status_code == 200
            print(f"  t+{elapsed:6.1f} min  {status}  {'alive' if alive else 'DEAD'}")
            if not alive:
                print(f"\nSession lifetime: between {elapsed - interval_min:.0f} and {elapsed:.0f} minutes.")
                return
        print(f"\nStill alive after {max_hours}h -- lifetime exceeds the watch window.")
    except KeyboardInterrupt:
        print(f"\nStopped after {(time.monotonic() - started) / 60:.1f} min, session still alive.")


def redact(route: str) -> str:
    """Strip identifiers out of a URL before printing it."""
    return _ID_SEGMENT.sub("/{id}", route)


def probe(session: requests.Session, base_url: str, route: str, show: bool = True) -> Any | None:
    """Fetch one route, print its status and shape, and return the parsed payload."""
    response = _get(session, base_url, route)
    if response is None:
        return None
    content_type = response.headers.get("content-type", "")
    print(f"  {redact(route)}: HTTP {response.status_code} ({content_type}, {len(response.content)} bytes)")
    if response.status_code != 200 or "json" not in content_type:
        return None
    try:
        payload = response.json()
    except ValueError:
        print("      (declared JSON but did not parse)")
        return None
    if show:
        dump("shape", payload, indent=4)
    return payload


def explore(session: requests.Session, base_url: str, identity: dict[str, Any] | None) -> None:
    """Walk from the identity to the homework entries, printing shapes only."""
    user_id = (identity or {}).get("userId") or (identity or {}).get("id")
    if user_id:
        _summarise_children(probe(session, base_url, f"/directory/user/{user_id}/children"))

    diaries = probe(session, base_url, "/homeworks/list")
    diary_id = None
    if isinstance(diaries, list) and diaries:
        print(f"      -> {len(diaries)} diary/diaries")
        if isinstance(diaries[0], dict):
            diary_id = diaries[0].get("_id")

    if not diary_id:
        print("      -> no diary id found; cannot fetch entries")
        return

    # The payload behind this one is the whole point of the integration.
    probe(session, base_url, f"/homeworks/get/{diary_id}")
    probe(session, base_url, f"/homeworks/{diary_id}/entry/status")


def _summarise_children(payload: Any) -> None:
    """Report how many children exist without printing any of their details."""
    if not isinstance(payload, list):
        return
    ids = {
        child["id"]
        for structure in payload
        if isinstance(structure, dict)
        for child in structure.get("children") or []
        if isinstance(child, dict) and child.get("id")
    }
    print(f"      -> {len(payload)} structure(s), {len(ids)} distinct child(ren)")


def _get(session: requests.Session, base_url: str, route: str) -> requests.Response | None:
    try:
        return session.get(f"{base_url}{route}", timeout=TIMEOUT, allow_redirects=False)
    except requests.RequestException as exc:
        print(f"  {redact(route)}: request failed ({exc})")
        return None


def _looks_blocked(response: requests.Response) -> bool:
    if response.status_code in (403, 429, 503) and "cf-mitigated" in response.headers:
        return True
    return response.status_code in (403, 503) and "just a moment" in response.text[:2000].lower()


def main() -> int:
    # Keep stdout and stderr in order when the output is redirected to a file.
    sys.stdout.reconfigure(line_buffering=True)

    try:
        config = read_config()
    except ProbeError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return exc.code

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    print(f"\n=== {config.base_url} ===")
    try:
        check_platform(session, config.base_url)
        login(session, config)
    except ProbeError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return exc.code

    print("\n=== session ===")
    found = whoami(session, config.base_url)

    print("\n=== endpoints ===")
    explore(session, config.base_url, found[1] if found else None)

    if "--watch" in sys.argv:
        if not found:
            print("\nCannot watch: no identity route answered.", file=sys.stderr)
            return 3
        watch(session, config.base_url, found[0], interval_min=5, max_hours=12)
    else:
        print("\nDone. Re-run with --watch to measure how long the session stays valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
