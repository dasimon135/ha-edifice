"""The bundled dashboard card: served before any entry, registered once as a resource.

The registration is the one daikin_madoka ships, with the reasons recorded there: Lovelace
waits for its own resources before rendering a card and nothing waits for a frontend module
URL (ha-rf-fan#44), and a second resource for the same file is a second copy of the element
racing the first (ha-rf-fan#29).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.components.lovelace.const import LOVELACE_DATA, MODE_YAML
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component

from custom_components.edifice import frontend
from custom_components.edifice.const import DOMAIN
from custom_components.edifice.frontend import CARD_URL, async_register_card

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

CARD_FILE = Path(frontend.__file__).parent / "frontend" / "edifice-card.js"


def _ours(hass: HomeAssistant) -> list[dict]:
    return [
        item
        for item in hass.data[LOVELACE_DATA].resources.async_items()
        if item["url"].split("?")[0] == CARD_URL
    ]


async def _setup(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "lovelace", {})
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()


async def test_card_is_served_without_any_config_entry(hass: HomeAssistant, hass_client) -> None:
    """The dashboard asks for the URL on every load, entry or not: it must answer."""
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    response = await (await hass_client()).get(CARD_URL)

    assert response.status == 200
    assert 'customElements.define("edifice-card"' in await response.text()


async def test_registering_twice_is_a_no_op(hass: HomeAssistant, hass_client) -> None:
    """A static path registered twice raises; the guard keeps a second call harmless."""
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    await async_register_card(hass)

    assert (await (await hass_client()).get(CARD_URL)).status == 200


async def test_registered_once_as_a_module_resource_keyed_on_the_file(hass: HomeAssistant) -> None:
    await _setup(hass)

    ours = _ours(hass)
    digest = hashlib.sha256(CARD_FILE.read_bytes()).hexdigest()[:12]
    assert len(ours) == 1
    assert ours[0]["type"] == "module"
    assert ours[0]["url"] == f"{CARD_URL}?v={digest}"

    assert await frontend._async_register_resource(hass, ours[0]["url"])
    assert len(_ours(hass)) == 1


async def test_a_resource_added_by_hand_is_adopted(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "lovelace", {})
    resources = hass.data[LOVELACE_DATA].resources
    await resources.async_get_info()
    await resources.async_create_item({"res_type": "module", "url": f"{CARD_URL}?v=stale"})

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    ours = _ours(hass)
    assert len(ours) == 1
    assert ours[0]["url"] != f"{CARD_URL}?v=stale"


async def test_yaml_mode_falls_back_to_the_module_list(hass: HomeAssistant) -> None:
    """In YAML mode the resource list is the user's file, not ours to write."""
    assert await async_setup_component(hass, "lovelace", {})
    hass.data[LOVELACE_DATA].resource_mode = MODE_YAML

    with patch("custom_components.edifice.frontend.add_extra_js_url") as add_extra_js_url:
        assert await async_setup_component(hass, DOMAIN, {})
        await hass.async_block_till_done()

    add_extra_js_url.assert_called_once()
    assert add_extra_js_url.call_args[0][1].split("?")[0] == CARD_URL


async def test_the_account_device_links_to_the_ent(hass: HomeAssistant, entry, client_cls) -> None:
    """The card's "Open the ENT" link is the account device's configuration URL."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    account = [d for d in devices if (DOMAIN, entry.entry_id) in d.identifiers]

    assert len(account) == 1
    assert account[0].configuration_url == "https://ent.example.org"
