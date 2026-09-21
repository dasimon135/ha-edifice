"""Constants for the Edifice ENT integration."""

from datetime import timedelta

DOMAIN = "edifice"

# Every 20 minutes: a teacher edits the diary a few times a day at most, and each
# refresh is two requests against a school platform we do not operate.
UPDATE_INTERVAL = timedelta(minutes=20)

# How far ahead the sensor looks. Teachers fill the diary about a week in advance,
# so two weeks comfortably covers everything that exists.
UPCOMING_DAYS = 14

ATTR_HOMEWORK = "homework"
ATTR_NEXT_DUE = "next_due"

# Fired by the "new homework" event entity when an entry appears that was not there
# on the previous refresh.
EVENT_HOMEWORK_ADDED = "homework_added"

# Version of the file that remembers which entries have already been announced.
STORAGE_VERSION = 1
