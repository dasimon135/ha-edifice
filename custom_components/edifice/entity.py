"""Device descriptions shared by the platforms of the Edifice ENT integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .api import Child
from .const import DOMAIN


def account_device_info(entry: ConfigEntry) -> DeviceInfo:
    """One device per ENT account: the class diary and the mailbox belong to it."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Edifice",
        entry_type=DeviceEntryType.SERVICE,
    )


def child_device_info(entry: ConfigEntry, child: Child) -> DeviceInfo:
    """One device per child, named after their first name.

    The cahier de liaison is kept per child, unlike the homework diary, which belongs to a
    class. There is deliberately no ``via_device``: it was replaced by ``via_device_id``
    between Home Assistant 2026.7 and 2026.9, and the link would only be cosmetic.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_{child.child_id}")},
        name=child.first_name,
        manufacturer="Edifice",
        entry_type=DeviceEntryType.SERVICE,
    )
