"""DataUpdateCoordinator for the Edifice ENT integration."""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import Diary, EdificeAuthError, EdificeClient, EdificeError, Homework
from .const import DOMAIN, UPCOMING_DAYS, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)

type EdificeConfigEntry = ConfigEntry[EdificeCoordinator]


@dataclass(frozen=True)
class EdificeData:
    """What one refresh produced."""

    diaries: list[Diary]
    upcoming: list[Homework]


class EdificeCoordinator(DataUpdateCoordinator[EdificeData]):
    """Poll the ENT for upcoming homework."""

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

    async def _async_update_data(self) -> EdificeData:
        # HA's configured timezone, not the process's: in a container the two differ.
        today = dt_util.now().date()
        try:
            return await self.hass.async_add_executor_job(self._fetch, today)
        except EdificeAuthError as err:
            # Rejected credentials are never retried: raising this stops the refreshes
            # and opens a reauthentication flow, so a changed password costs one failed
            # login rather than one every 20 minutes.
            raise ConfigEntryAuthFailed(str(err)) from err
        except EdificeError as err:
            raise UpdateFailed(str(err)) from err

    def _fetch(self, today: datetime.date) -> EdificeData:
        """Blocking: runs in the executor."""
        diaries = self.client.get_diaries()
        upcoming = self.client.get_homework(
            since=today,
            until=today + datetime.timedelta(days=UPCOMING_DAYS),
            diaries=diaries,
        )
        return EdificeData(diaries=diaries, upcoming=upcoming)
