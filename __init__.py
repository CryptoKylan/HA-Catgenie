"""The CatGenie A.I. integration."""

from __future__ import annotations

import logging

from catgenie import CatGenieAuth, Credentials
from catgenie.const import TLS_IMPERSONATE
from curl_cffi.requests import AsyncSession
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .client import HomeAssistantCatGenieClient
from .const import (
    CONF_ACCOUNT_ID,
    CONF_REFRESH_TOKEN,
    CONF_TENANT_ID,
    CONF_USER_ID,
)
from .coordinator import CatGenieConfigEntry, CatGenieCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: CatGenieConfigEntry) -> bool:
    """Set up CatGenie A.I. from a config entry."""
    _LOGGER.warning("Loading CatGenie A.I. integration 0.1.2 (schedule fix active)")
    # PetNovations drops requests that don't carry a mobile TLS fingerprint,
    # so the library needs a curl_cffi session rather than aiohttp.
    session = AsyncSession(impersonate=TLS_IMPERSONATE)
    entry.async_on_unload(session.close)

    # Only the long-lived refresh token is stored. The access token is empty
    # at startup, so the first request refreshes it automatically.
    credentials = Credentials(
        refresh_token=entry.data[CONF_REFRESH_TOKEN],
        account_id=entry.data.get(CONF_ACCOUNT_ID, ""),
        user_id=entry.data.get(CONF_USER_ID, ""),
        tenant_id=entry.data.get(CONF_TENANT_ID, ""),
    )
    # The auth object and client must share the SAME Credentials instance so
    # a refresh performed by auth is visible to the client.
    auth = CatGenieAuth(session=session)
    auth.credentials = credentials
    client = HomeAssistantCatGenieClient(credentials, session=session)
    client.set_auth(auth)

    coordinator = CatGenieCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CatGenieConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
