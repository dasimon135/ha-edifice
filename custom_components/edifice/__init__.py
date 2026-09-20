"""The Edifice ENT integration: school homework from an Edifice-based ENT."""

from __future__ import annotations

from functools import partial

from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant

from .api import EdificeClient
from .coordinator import EdificeConfigEntry, EdificeCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: EdificeConfigEntry) -> bool:
    """Set up one ENT account."""
    # Built in the executor: creating a requests session can touch the filesystem.
    client = await hass.async_add_executor_job(
        partial(
            EdificeClient,
            base_url=entry.data[CONF_URL],
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
        )
    )

    coordinator = EdificeCoordinator(hass, entry, client)
    # Raises ConfigEntryAuthFailed / ConfigEntryNotReady, which HA turns into a
    # reauthentication flow / a retry with backoff.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EdificeConfigEntry) -> bool:
    """Unload one ENT account and drop its session."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await hass.async_add_executor_job(entry.runtime_data.client.close)
    return unloaded
