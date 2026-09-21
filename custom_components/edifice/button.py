"""Button platform for the Edifice ENT integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import EdificeConfigEntry, EdificeCoordinator
from .entity import account_device_info

# The coordinator serialises the refreshes, and a press only asks for one.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EdificeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One refresh button per ENT account."""
    async_add_entities([EdificeRefreshButton(entry.runtime_data)])


class EdificeRefreshButton(CoordinatorEntity[EdificeCoordinator], ButtonEntity):
    """Read the ENT now, instead of waiting for the next scheduled refresh."""

    _attr_has_entity_name = True
    _attr_translation_key = "refresh"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: EdificeCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_refresh"
        self._attr_device_info = account_device_info(entry)

    @property
    def available(self) -> bool:
        # Pressing it is how someone retries after the ENT was unreachable, so a failed
        # refresh must not grey it out.
        return True

    async def async_press(self) -> None:
        # Debounced by Home Assistant: the first press reads at once, and however many
        # follow within the next few seconds are answered by one more read when it ends.
        await self.coordinator.async_request_refresh()
