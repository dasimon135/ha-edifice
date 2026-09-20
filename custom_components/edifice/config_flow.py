"""Config flow for the Edifice ENT integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_NAME, CONF_PASSWORD, CONF_URL, CONF_USERNAME
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    Diary,
    EdificeAuthError,
    EdificeClient,
    EdificeError,
    EdificeUnavailable,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Shown as an example in the form. A documentation domain, so it points at no real ENT.
EXAMPLE_URL = "https://ent.example.org"

_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password"))

# The URL is deliberately a plain string rather than a URL selector: the browser's own
# URL validation would reject "ent.example.org" typed without a scheme, which we accept.
STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): _PASSWORD,
        vol.Optional(CONF_NAME): str,
    }
)
STEP_REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): _PASSWORD})


def normalise_url(value: str) -> str:
    """Reduce whatever was typed to ``https://host[:port]``.

    Raises ValueError for anything that is not a plain https host: plain http would send
    a school password in clear, and a URL with embedded credentials would end up stored
    in the config entry.
    """
    value = value.strip()
    if "://" not in value:
        value = f"https://{value}"
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError(value)
    port = f":{parts.port}" if parts.port else ""
    return f"https://{parts.hostname.lower()}{port}"


def _probe(url: str, username: str, password: str) -> list[Diary]:
    """Blocking: check the platform, log in, and list the diaries."""
    client = EdificeClient(base_url=url, username=username, password=password)
    try:
        client.check_platform()
        client.login()
        return client.get_diaries()
    finally:
        client.close()


class EdificeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add an ENT account, and re-enter its password when it stops working."""

    VERSION = 1

    async def _async_validate(self, url: str, username: str, password: str) -> tuple[str | None, str | None]:
        """Try the account. Returns ``(first_diary_title, error_key)``; one is None."""
        try:
            diaries = await self.hass.async_add_executor_job(_probe, url, username, password)
        except EdificeAuthError:
            return None, "invalid_auth"
        except EdificeUnavailable:
            return None, "cannot_connect"
        except EdificeError:
            # Not an Edifice platform, a federated login, or no homework module.
            return None, "unsupported_platform"
        except Exception:  # a config flow must never crash on the user
            _LOGGER.exception("Unexpected error while validating the ENT account")
            return None, "unknown"
        if not diaries:
            return None, "no_diary"
        return diaries[0].title, None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                url = normalise_url(user_input[CONF_URL])
            except ValueError:
                errors[CONF_URL] = "invalid_url"
            else:
                username = user_input[CONF_USERNAME].strip()
                await self.async_set_unique_id(f"{urlsplit(url).netloc}:{username.lower()}")
                self._abort_if_unique_id_configured()

                title, error = await self._async_validate(url, username, user_input[CONF_PASSWORD])
                if error is None:
                    return self.async_create_entry(
                        title=(user_input.get(CONF_NAME) or "").strip() or title,
                        data={
                            CONF_URL: url,
                            CONF_USERNAME: username,
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                        },
                    )
                errors["base"] = error

        # Never hand the password back to the form.
        suggested = {k: v for k, v in (user_input or {}).items() if k != CONF_PASSWORD}
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_SCHEMA, suggested),
            errors=errors,
            # hassfest forbids a literal URL inside a translation string.
            description_placeholders={"example_url": EXAMPLE_URL},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            password = user_input[CONF_PASSWORD]
            _, error = await self._async_validate(entry.data[CONF_URL], entry.data[CONF_USERNAME], password)
            if error is None:
                return self.async_update_reload_and_abort(entry, data_updates={CONF_PASSWORD: password})
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={
                "username": entry.data[CONF_USERNAME],
                "host": urlsplit(entry.data[CONF_URL]).netloc,
            },
        )
