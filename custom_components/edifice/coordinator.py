"""DataUpdateCoordinator for the Edifice ENT integration."""

from __future__ import annotations

import datetime
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    Child,
    Diary,
    EdificeAuthError,
    EdificeClient,
    EdificeError,
    EdificePlatformError,
    EdificeUnavailable,
    Homework,
    Word,
)
from .const import CHILDREN_REFRESH, DOMAIN, STORAGE_VERSION, UPCOMING_DAYS, scan_interval

_LOGGER = logging.getLogger(__name__)

type EdificeConfigEntry = ConfigEntry[EdificeCoordinator]

# Returned by _optional() when a module answers 404: it is not deployed on this platform.
_ABSENT: Any = object()


def seen_store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, list[str]]]:
    """The file that remembers which homework entries have already been announced."""
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.seen.{entry_id}")


def words_store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, list[int]]]:
    """The file that remembers, per child, which words have already been announced."""
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.words.{entry_id}")


@dataclass(frozen=True)
class Schoolbook:
    """The cahier de liaison of one child."""

    unread: int
    # One page, newest first. The text of a word is not kept.
    words: list[Word]


@dataclass(frozen=True)
class EdificeData:
    """What one refresh produced."""

    diaries: list[Diary]
    # Everything the diary holds, past included, sorted by date then subject.
    homework: list[Homework]
    # From today through UPCOMING_DAYS ahead.
    upcoming: list[Homework]
    # Entries seen for the first time on *this* refresh and due today or later. Empty
    # on the very first refresh ever, which only establishes what already exists.
    new: list[Homework]
    children: list[Child] = field(default_factory=list)
    # By child id. Empty when the platform has no cahier de liaison.
    schoolbook: dict[str, Schoolbook] = field(default_factory=dict)
    # Words seen for the first time on this refresh, by child id.
    new_words: dict[str, list[Word]] = field(default_factory=dict)
    # None when the platform does not use the older conversation module.
    unread_messages: int | None = None


class EdificeCoordinator(DataUpdateCoordinator[EdificeData]):
    """Poll the ENT and work out what is upcoming and what is new."""

    config_entry: EdificeConfigEntry

    def __init__(self, hass: HomeAssistant, entry: EdificeConfigEntry, client: EdificeClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {entry.title}",
            config_entry=entry,
            update_interval=scan_interval(entry.options),
        )
        self.client = client
        self._seen_store = seen_store(hass, entry.entry_id)
        self._words_store = words_store(hass, entry.entry_id)
        # Ids already announced. None until the file has been read.
        self._seen: set[str] | None = None
        self._words_seen: dict[str, set[int]] | None = None
        # Children change rarely, so they are asked for every few hours, not every refresh.
        self._children: list[Child] = []
        self._children_fetched: datetime.datetime | None = None
        # A 404 means the module is not deployed: it is not asked for again until a reload.
        self._schoolbook_absent = False
        self._mailbox_absent = False

    async def _async_update_data(self) -> EdificeData:
        try:
            diaries, homework, schoolbook, unread_messages = await self.hass.async_add_executor_job(self._fetch)
        except EdificeAuthError as err:
            # Rejected credentials are never retried: raising this stops the refreshes
            # and opens a reauthentication flow, so a changed password costs one failed
            # login rather than one every 20 minutes.
            raise ConfigEntryAuthFailed(str(err)) from err
        except EdificeError as err:
            raise UpdateFailed(str(err)) from err

        # HA's configured timezone, not the process's: in a container the two differ.
        today = dt_util.now().date()
        last_day = today + datetime.timedelta(days=UPCOMING_DAYS)
        return EdificeData(
            diaries=diaries,
            homework=homework,
            upcoming=[hw for hw in homework if today <= hw.date <= last_day],
            new=await self._async_find_new(homework, today),
            children=list(self._children),
            schoolbook=schoolbook,
            new_words=await self._async_find_new_words(schoolbook),
            unread_messages=unread_messages,
        )

    # -- fetching (blocking, runs in the executor) ---------------------------------

    def _fetch(self) -> tuple[list[Diary], list[Homework], dict[str, Schoolbook], int | None]:
        diaries = self.client.get_diaries()
        homework = self.client.get_homework(diaries=diaries)
        return diaries, homework, self._fetch_schoolbook(), self._fetch_unread_messages()

    def _optional(self, label: str, func: Callable[..., Any], *args: Any) -> Any:
        """Call a read that must not be allowed to cost the homework.

        A network failure or a rejected login still raises: the whole refresh is then in
        doubt. A module that is missing (_ABSENT) or answers something unreadable (None)
        only costs its own entities.
        """
        try:
            return func(*args)
        except (EdificeAuthError, EdificeUnavailable):
            raise
        except EdificePlatformError as err:
            _LOGGER.debug("%s is not available on this platform: %s", label, err)
            return _ABSENT
        except EdificeError as err:
            _LOGGER.debug("%s returned something unreadable: %s", label, err)
            return None

    def _refresh_children(self) -> list[Child]:
        now = dt_util.utcnow()
        if self._children_fetched is None or now - self._children_fetched >= CHILDREN_REFRESH:
            children = self._optional("children", self.client.get_children)
            if isinstance(children, list):
                self._children, self._children_fetched = children, now
            elif children is _ABSENT:
                self._children, self._children_fetched = [], now
            # Otherwise keep the previous list and ask again next time.
        return self._children

    def _fetch_schoolbook(self) -> dict[str, Schoolbook]:
        if self._schoolbook_absent:
            return {}

        result: dict[str, Schoolbook] = {}
        for child in self._refresh_children():
            unread = self._optional("cahier de liaison count", self.client.get_unread_words, child.child_id)
            if unread is _ABSENT:
                self._schoolbook_absent = True
                return {}
            words = self._optional("cahier de liaison list", self.client.get_words, child.child_id)
            if words is _ABSENT:
                self._schoolbook_absent = True
                return {}
            if unread is None and words is None:
                continue
            words = words or []
            if unread is None:
                unread = sum(not word.acknowledged for word in words)
            result[child.child_id] = Schoolbook(unread=unread, words=words)
        return result

    def _fetch_unread_messages(self) -> int | None:
        if self._mailbox_absent:
            return None
        count = self._optional("mailbox count", self.client.get_unread_messages)
        if count is _ABSENT:
            self._mailbox_absent = True
            return None
        return count

    # -- what is new ---------------------------------------------------------------

    async def _async_find_new(self, homework: list[Homework], today: datetime.date) -> list[Homework]:
        """Return the entries never seen before, and remember them.

        The set of seen ids is kept on disk so that a restart neither announces the whole
        diary again nor loses what a teacher added while Home Assistant was down. The very
        first run has nothing to compare with, so it records what exists and announces
        nothing.
        """
        current = {hw.entry_id for hw in homework if hw.entry_id}

        if self._seen is None:
            stored = await self._seen_store.async_load()
            if stored is None:
                self._seen = current
                await self._seen_store.async_save({"seen": sorted(current)})
                return []
            self._seen = set(stored.get("seen", []))

        fresh = current - self._seen
        if not fresh:
            return []

        self._seen |= fresh
        await self._seen_store.async_save({"seen": sorted(self._seen)})
        # An entry dated in the past is remembered but not announced: nobody wants a
        # notification for last week's homework because a teacher back-filled the diary.
        return [hw for hw in homework if hw.entry_id in fresh and hw.date >= today]

    async def _async_find_new_words(self, schoolbook: dict[str, Schoolbook]) -> dict[str, list[Word]]:
        """Return the words never seen before, per child, and remember them.

        A child met for the first time is a baseline: their existing words are recorded and
        announced to nobody. That is also what happens for every child the first time this
        version runs on an existing installation.
        """
        if self._words_seen is None:
            stored = await self._words_store.async_load() or {}
            self._words_seen = {child_id: set(ids) for child_id, ids in stored.items()}

        fresh: dict[str, list[Word]] = {}
        changed = False
        for child_id, book in schoolbook.items():
            current = {word.word_id for word in book.words}
            if child_id not in self._words_seen:
                self._words_seen[child_id] = current
                changed = True
                continue
            new_ids = current - self._words_seen[child_id]
            if new_ids:
                self._words_seen[child_id] |= new_ids
                changed = True
                fresh[child_id] = [word for word in book.words if word.word_id in new_ids]

        if changed:
            await self._words_store.async_save({child_id: sorted(ids) for child_id, ids in self._words_seen.items()})
        return fresh
