"""Constants for the Edifice ENT integration."""

from datetime import timedelta

DOMAIN = "edifice"

# Every 20 minutes: a teacher edits the diary a few times a day at most, and a refresh is a
# handful of small requests against a school platform we do not operate.
UPDATE_INTERVAL = timedelta(minutes=20)

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
