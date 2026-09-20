#!/usr/bin/env python3
"""Exercise the homework client against a live ENT.

By default this prints a summary carrying no homework content -- safe to paste into a
bug report or a chat. Pass ``--show`` to print the actual homework on your own screen.

    EDIFICE_URL       base URL of the ENT (default: https://ent.parisclassenumerique.fr)
    EDIFICE_USERNAME  login (prompted if unset)
    EDIFICE_PASSWORD  password (prompted without echo if unset)

Exit codes match scripts/edifice_login.py: 0 ok, 1 auth rejected, 2 config, 3 platform.
"""

from __future__ import annotations

import datetime
import getpass
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components" / "edifice"))

from api import (
    EdificeAuthError,
    EdificeClient,
    EdificeError,
    EdificePlatformError,
    EdificeUnavailable,
)

# The client itself has no default URL; only this demo script does.
DEFAULT_URL = "https://ent.parisclassenumerique.fr"


def print_audit(raw_payloads: list, homework: list) -> None:
    """Compare what the server sent with what the parser kept, per day. Numbers only.

    A row marked MISMATCH means the parser dropped (or invented) entries for that day.
    """
    raw_by_day: Counter[str] = Counter()
    odd: Counter[str] = Counter()
    for payload in raw_payloads:
        days = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(days, list):
            odd["payload has no 'data' list"] += 1
            continue
        for day in days:
            if not isinstance(day, dict):
                odd["day is not an object"] += 1
                continue
            entries = day.get("entries")
            if not isinstance(entries, list):
                odd["day.entries is not a list"] += 1
                continue
            for entry in entries:
                if isinstance(entry, dict):
                    raw_by_day[str(day.get("date"))] += 1
                else:
                    odd["entry is not an object"] += 1

    parsed_by_day = Counter(hw.date.isoformat() for hw in homework)
    raw_total, parsed_total = sum(raw_by_day.values()), sum(parsed_by_day.values())

    print("\n--- audit: server payload vs parsed ---")
    print(f"  entries in the raw payload : {raw_total}")
    print(f"  entries kept by the parser : {parsed_total}")
    for reason, count in odd.items():
        print(f"  malformed                  : {count} x {reason}")

    print("\n  date         day  raw  parsed")
    week_totals: Counter[str] = Counter()
    for day in sorted(set(raw_by_day) | set(parsed_by_day)):
        try:
            when = datetime.date.fromisoformat(day)
        except ValueError:
            print(f"  {day:<12} ???  {raw_by_day[day]:>3}  {parsed_by_day[day]:>6}  unreadable date")
            continue
        week_totals[(when - datetime.timedelta(days=when.weekday())).isoformat()] += raw_by_day[day]
        flag = "  <-- MISMATCH" if raw_by_day[day] != parsed_by_day[day] else ""
        print(f"  {day:<12} {when:%a}  {raw_by_day[day]:>3}  {parsed_by_day[day]:>6}{flag}")

    print("\n  per week (Monday .. Sunday), raw entries:")
    for monday, count in sorted(week_totals.items()):
        print(f"    week of {monday}: {count}")


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    show = "--show" in sys.argv

    base_url = os.environ.get("EDIFICE_URL", DEFAULT_URL)
    try:
        username = os.environ.get("EDIFICE_USERNAME") or input("ENT login: ").strip()
        password = os.environ.get("EDIFICE_PASSWORD") or getpass.getpass("ENT password: ")
    except (EOFError, KeyboardInterrupt):
        print("no credentials on stdin", file=sys.stderr)
        return 2
    if not username or not password:
        print("missing credentials", file=sys.stderr)
        return 2

    client = EdificeClient(base_url=base_url, username=username, password=password)
    try:
        client.login()
        diaries = client.get_diaries()
        homework = client.get_homework()
        # The untouched server payloads, so the audit below can tell what the parser dropped.
        raw_payloads = [client._get_json(f"/homeworks/get/{diary.diary_id}") for diary in diaries]
    except EdificeAuthError as exc:
        print(f"authentication failed: {exc}", file=sys.stderr)
        return 1
    except (EdificePlatformError, EdificeUnavailable) as exc:
        print(f"platform error: {exc}", file=sys.stderr)
        return 3
    except EdificeError as exc:
        print(f"client error: {exc}", file=sys.stderr)
        return 3
    finally:
        client.close()

    print(f"\ndiaries : {len(diaries)}")
    for diary in diaries:
        modified = diary.entries_modified.isoformat() if diary.entries_modified else "unknown"
        print(f"  - {len(diary.title)}-char title, last change {modified}")

    print(f"homework: {len(homework)} item(s)")
    print_audit(raw_payloads, homework)
    if not homework:
        return 0

    print(f"  range : {homework[0].date} .. {homework[-1].date}")
    subjects = Counter(hw.subject for hw in homework)
    print(f"  subjects: {len(subjects)} distinct")
    empty = sum(1 for hw in homework if not hw.content_text)
    print(f"  entries with empty text after stripping: {empty}")

    if show:
        print("\n--- content (your screen only) ---")
        for hw in homework:
            print(f"\n[{hw.date}] {hw.subject}\n{hw.content_text}")
    else:
        print("\n--- shape only; pass --show to read the actual homework ---")
        for hw in homework[:8]:
            print(
                f"  {hw.date}  subject={len(hw.subject):>3}c  "
                f"html={len(hw.content_html):>5}c  text={len(hw.content_text):>5}c  "
                f"id={'set' if hw.entry_id else 'MISSING'}"
            )
        if len(homework) > 8:
            print(f"  ... {len(homework) - 8} more")

    return 0


if __name__ == "__main__":
    sys.exit(main())
