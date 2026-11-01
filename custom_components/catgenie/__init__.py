"""The CatGenie A.I. integration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging

from catgenie import Credentials
from catgenie.const import TLS_IMPERSONATE
from curl_cffi.requests import AsyncSession
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .client import HomeAssistantCatGenieAuth, HomeAssistantCatGenieClient
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
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: CatGenieConfigEntry) -> bool:
    """Set up CatGenie A.I. from a config entry."""
    # PetNovations drops requests that don't carry a mobile TLS fingerprint,
    # so the library needs a curl_cffi session rather than aiohttp.
    session = AsyncSession(impersonate=TLS_IMPERSONATE)
    close_task: asyncio.Task[None] | None = None
    forwarding_started = False
    actions_started = False
    stop_updates: list[Callable[[], None]] = []
    updates: list[asyncio.Task] = []

    async def _close_once() -> None:
        """Log a failed close once without caching an exception for callbacks."""
        try:
            await session.close()
        except Exception as err:
            _LOGGER.warning("CatGenie session cleanup failed (%s)", type(err).__name__)

    async def _close_session() -> None:
        """Share one close operation across explicit and framework cleanup."""
        nonlocal close_task
        task = close_task
        if task is None:
            task = hass.async_create_task(_close_once(), "catgenie_close_session")
            close_task = task
        await asyncio.shield(task)

    def _stop_updates() -> None:
        """Cancel only this setup's subscriptions and background reads."""
        while stop_updates:
            try:
                stop_updates.pop()()
            except Exception as err:
                _LOGGER.warning("CatGenie subscription cleanup failed (%s)", type(err).__name__)
        for task in updates:
            task.cancel()

    async def _shutdown(_event: object) -> None:
        """Release the session on core shutdown as well as entry unload."""
        _stop_updates()
        try:
            if updates:
                await asyncio.gather(*updates, return_exceptions=True)
        finally:
            await _close_session()

    async def _cleanup_failed_setup() -> None:
        """Keep cleanup alive if a setup waiter is cancelled again."""
        try:
            _stop_updates()
            if updates:
                await asyncio.gather(*updates, return_exceptions=True)
            if actions_started:
                from .services import async_unload_actions

                async_unload_actions(hass, entry)
        except Exception as err:
            _LOGGER.warning("CatGenie update/action cleanup failed (%s)", type(err).__name__)
        try:
            if forwarding_started:
                await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        except Exception as err:
            _LOGGER.warning("CatGenie platform cleanup failed (%s)", type(err).__name__)
        finally:
            await _close_session()

    try:
        from homeassistant.const import EVENT_HOMEASSISTANT_STOP

        entry.async_on_unload(_close_session)
        entry.async_on_unload(_stop_updates)
        stop_updates.append(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _shutdown)
        )

        # Only the long-lived refresh token is stored. The access token is empty
        # at startup, so the first request refreshes it automatically.
        credentials = Credentials(
            refresh_token=entry.data[CONF_REFRESH_TOKEN],
            account_id=entry.data.get(CONF_ACCOUNT_ID, ""),
            user_id=entry.data.get(CONF_USER_ID, ""),
            tenant_id=entry.data.get(CONF_TENANT_ID, ""),
        )
        # Auth and client share credentials so token refreshes remain visible.
        auth = HomeAssistantCatGenieAuth(session=session)
        auth.credentials = credentials
        client = HomeAssistantCatGenieClient(credentials, session=session)
        client.set_auth(auth)

        coordinator = CatGenieCoordinator(hass, entry, client)
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        # Imported here so device-test seams do not need the history tracker.
        from homeassistant.helpers.event import async_track_time_interval

        from .history import HISTORY_SCAN_INTERVAL
        from .history_coordinator import CatGenieHistoryCoordinator, bind_history

        history = CatGenieHistoryCoordinator(hass, entry, client)
        bind_history(coordinator, history)
        from .read_information import READ_INFORMATION_INTERVAL
        from .read_information_coordinator import (
            CatGenieReadCoordinator,
            bind_read_information,
        )

        reader = CatGenieReadCoordinator(hass, entry, client, coordinator)
        bind_read_information(coordinator, reader)

        forwarding_started = True
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        from .services import async_setup_actions

        actions_started = True
        async_setup_actions(hass, entry)

        async def _refresh_history(_now: object = None) -> None:
            """Refresh activity history without affecting device polling."""
            try:
                await history.async_refresh()
            except Exception:  # noqa: BLE001 - history failures stay isolated
                _LOGGER.warning(
                    "CatGenie activity history unavailable; device polling is unchanged",
                    exc_info=True,
                )

        stop_updates.append(
            async_track_time_interval(hass, _refresh_history, HISTORY_SCAN_INTERVAL)
        )
        updates.append(entry.async_create_background_task(
            hass, _refresh_history(), "catgenie_activity_history"
        ))

        async def _refresh_read_information(_now: object = None) -> None:
            """Refresh the account feed without affecting device polling."""
            try:
                await reader.async_refresh()
            except Exception:  # noqa: BLE001 - feed failures stay isolated
                _LOGGER.warning(
                    "CatGenie notification feed unavailable; device polling is unchanged",
                    exc_info=True,
                )

        stop_updates.append(
            async_track_time_interval(
                hass, _refresh_read_information, READ_INFORMATION_INTERVAL
            )
        )
        updates.append(entry.async_create_background_task(
            hass, _refresh_read_information(), "catgenie_read_information"
        ))
        return True
    except (Exception, asyncio.CancelledError):
        # HA 2025.7 does not run on-unload callbacks for generic setup errors.
        # Own every post-allocation failure, preserving the original exception.
        cleanup = hass.async_create_task(_cleanup_failed_setup(), "catgenie_setup_cleanup")
        await asyncio.shield(cleanup)
        raise


async def async_unload_entry(hass: HomeAssistant, entry: CatGenieConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        from .services import async_unload_actions

        async_unload_actions(hass, entry)
    return unloaded
