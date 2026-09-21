"""Constants for the Edifice ENT integration."""

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from homeassistant.const import CONF_SCAN_INTERVAL

DOMAIN = "edifice"

# Every 20 minutes by default: a teacher edits the diary a few times a day at most, and a
# refresh is a handful of small requests against a school platform we do not operate. The
# interval can be changed in the options, within these bounds; the refresh button covers the
# times when waiting is the problem.
DEFAULT_SCAN_MINUTES = 20
MIN_SCAN_MINUTES = 5
MAX_SCAN_MINUTES = 1440
UPDATE_INTERVAL = timedelta(minutes=DEFAULT_SCAN_MINUTES)

# Children change rarely; the list is asked for this often instead of at every refresh.
CHILDREN_REFRESH = timedelta(hours=6)

# How far ahead the sensor looks. Teachers fill the diary about a week in advance,
# so two weeks comfortably covers everything that exists.
UPCOMING_DAYS = 14

ATTR_HOMEWORK = "homework"
ATTR_NEXT_DUE = "next_due"
ATTR_WORDS = "words"

# Fired by the "new homework" event entity when an entry appears that was not there
# on the previous refresh.
EVENT_HOMEWORK_ADDED = "homework_added"

# Fired by a child's "new note" event entity when a word of the cahier de liaison appears.
EVENT_WORD_ADDED = "word_added"

# Version of the files that remember what has already been announced.
STORAGE_VERSION = 1


def scan_interval(options: Mapping[str, Any]) -> timedelta:
    """The polling interval chosen in the options, or the default when it is missing or absurd.

    A value edited by hand into the config entry must not be able to hammer the ENT or to
    stop the refreshes, so anything outside the bounds falls back rather than being clamped.
    """
    value = options.get(CONF_SCAN_INTERVAL)
    if not isinstance(value, int | float) or not MIN_SCAN_MINUTES <= value <= MAX_SCAN_MINUTES:
        return UPDATE_INTERVAL
    return timedelta(minutes=value)
