"""DataUpdateCoordinator for the Edifice ENT integration."""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import Diary, EdificeAuthError, EdificeClient, EdificeError, Homework
from .const import DOMAIN, STORAGE_VERSION, UPCOMING_DAYS, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)

type EdificeConfigEntry = ConfigEntry[EdificeCoordinator]


def seen_store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, list[str]]]:
    """The file that remembers which entries have already been announced."""
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.seen.{entry_id}")


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


class EdificeCoordinator(DataUpdateCoordinator[EdificeData]):
    """Poll the ENT and work out what is upcoming and what is new."""

    config_entry: EdificeConfigEntry

    def __init__(self, hass: HomeAssistant, entry: EdificeConfigEntry, client: EdificeClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {entry.title}",
            config_entry=entry,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self._store = seen_store(hass, entry.entry_id)
        # Ids of the entries already announced. None until the file has been read.
        self._seen: set[str] | None = None

    async def _async_update_data(self) -> EdificeData:
        try:
            diaries, homework = await self.hass.async_add_executor_job(self._fetch)
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
        )

    def _fetch(self) -> tuple[list[Diary], list[Homework]]:
        """Blocking: runs in the executor."""
        diaries = self.client.get_diaries()
        return diaries, self.client.get_homework(diaries=diaries)

    async def _async_find_new(self, homework: list[Homework], today: datetime.date) -> list[Homework]:
        """Return the entries never seen before, and remember them.

        The set of seen ids is kept on disk so that a restart neither announces the whole
        diary again nor loses what a teacher added while Home Assistant was down. The very
        first run has nothing to compare with, so it records what exists and announces
        nothing.
        """
        current = {hw.entry_id for hw in homework if hw.entry_id}

        if self._seen is None:
            stored = await self._store.async_load()
            if stored is None:
                self._seen = current
                await self._store.async_save({"seen": sorted(current)})
                return []
            self._seen = set(stored.get("seen", []))

        fresh = current - self._seen
        if not fresh:
            return []

        self._seen |= fresh
        await self._store.async_save({"seen": sorted(self._seen)})
        # An entry dated in the past is remembered but not announced: nobody wants a
        # notification for last week's homework because a teacher back-filled the diary.
        return [hw for hw in homework if hw.entry_id in fresh and hw.date >= today]
