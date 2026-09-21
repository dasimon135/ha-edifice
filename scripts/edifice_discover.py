#!/usr/bin/env python3
"""Find out what an Edifice ENT offers beyond the homework diary -- shapes only.

Signs in once, then reads a handful of JSON routes that the official mobile app is known
to call, and prints the **structure** of each answer: keys, types, lengths and counts.
No value from your account is ever printed, so the output is safe to paste into a chat or
a bug report.

What it looks at, and why:

* the cahier de liaison (``schoolbook``): mots per child, and how many are unread;
* the mailbox, which comes in two flavours. The older ``conversation`` module answers a
  plain count. Newer platforms hand out a token for a Carbonio (Zimbra) server instead:
  this script only reports *whether* that route answers, never what it returns, because
  the body is a credential;
* the notification feed (``timeline``), and the list of modules the platform has
  registered, which is platform configuration rather than personal data.

Credentials come from the environment, then from ``~/.config/ha-edifice/credentials.env``,
then from a prompt; see scripts/edifice_login.py. The default URL is only this family of
scripts' convenience: the integration itself has none.

Read the status codes like this: ``200`` the route exists and answered, ``404`` the module
is not deployed on this platform, ``302`` the session was refused. Two or three requests
per section, one login.

Exit codes match scripts/edifice_login.py: 0 ok, 1 auth rejected, 2 config, 3 platform.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import requests

# Reuses the login, the probe and the shape printer of edifice_login.py.
_LOGIN_PATH = Path(__file__).resolve().parent / "edifice_login.py"
_spec = importlib.util.spec_from_file_location("edifice_login", _LOGIN_PATH)
et = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = et
_spec.loader.exec_module(et)

# Keys of a registered notification that name a module of the platform. These describe the
# platform, not the person, so their values are printed.
_MODULE_KEYS = ("type", "event-type", "app-name", "app-address")

# The mobile app asks for this version of the notification payload.
_TIMELINE_ACCEPT = "application/json;version=3.0"


def child_ids(payload: Any) -> list[str]:
    """Distinct child ids out of ``/directory/user/{id}/children``. Never printed."""
    ids: list[str] = []
    if not isinstance(payload, list):
        return ids
    for structure in payload:
        children = structure.get("children") if isinstance(structure, dict) else None
        for child in children or []:
            child_id = child.get("id") if isinstance(child, dict) else None
            if isinstance(child_id, str) and child_id not in ids:
                ids.append(child_id)
    return ids


def module_names(payload: Any) -> dict[str, list[str]]:
    """Distinct module identifiers out of the platform's registered notifications."""
    found: dict[str, set[str]] = {key: set() for key in _MODULE_KEYS}
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            for key in _MODULE_KEYS:
                value = item.get(key)
                if isinstance(value, str):
                    found[key].add(value)
    return {key: sorted(values) for key, values in found.items() if values}


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def run(session: requests.Session, base_url: str) -> None:
    """Probe everything and print shapes. Takes an already signed-in session."""
    identity = et.probe(session, base_url, "/auth/oauth2/userinfo", show=False)
    user_id = identity.get("userId") if isinstance(identity, dict) else None
    children = et.probe(session, base_url, f"/directory/user/{user_id}/children", show=False) if user_id else None
    ids = child_ids(children)
    print(f"  -> {len(ids)} child(ren) on this account")

    _section("Cahier de liaison (schoolbook)")
    if not ids:
        print("  no child on this account: the parent routes cannot be probed")
    for number, child_id in enumerate(ids, start=1):
        print(f"  child {number}:")
        et.probe(session, base_url, f"/schoolbook/count/{child_id}")
        et.probe(session, base_url, f"/schoolbook/list/0/{child_id}")

    _section("Mailbox")
    print("  older flavour (conversation module):")
    et.probe(session, base_url, "/conversation/count/inbox?unread=true")
    et.probe(session, base_url, "/conversation/api/folders?depth=1")
    print("  newer flavour (Carbonio): status only, the body is a credential")
    et.probe(session, base_url, "/auth/carbonio/token", show=False)

    _section("Notification feed (timeline)")
    previous = session.headers.get("Accept")
    session.headers["Accept"] = _TIMELINE_ACCEPT
    try:
        et.probe(session, base_url, "/timeline/lastNotifications?page=0")
    finally:
        if previous is None:
            session.headers.pop("Accept", None)
        else:
            session.headers["Accept"] = previous

    registered = et.probe(session, base_url, "/timeline/registeredNotifications", show=False)
    names = module_names(registered)
    if names:
        print("  modules this platform registers notifications for:")
        for key, values in names.items():
            print(f"    {key}: {', '.join(values)}")

    types = et.probe(session, base_url, "/timeline/types", show=False)
    if isinstance(types, list) and all(isinstance(item, str) for item in types):
        print(f"  notification types: {', '.join(sorted(types))}")

    print("\nDone. Nothing above is a value from your account: only structure and counts.")


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    try:
        config = et.read_config()
    except et.ProbeError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return exc.code

    session = requests.Session()
    session.headers["User-Agent"] = et.USER_AGENT

    print(f"\n=== {config.base_url} ===")
    try:
        et.check_platform(session, config.base_url)
        et.login(session, config)
    except et.ProbeError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return exc.code

    run(session, config.base_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
