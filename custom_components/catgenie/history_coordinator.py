"""Independent CatGenie activity-history coordinator.

Device polling stays on ``CatGenieCoordinator`` at 15s/60s. This coordinator
does not replace ``entry.runtime_data`` and does not raise
``ConfigEntryAuthFailed``: a history failure must not tear down device state
or start re-authentication by itself. The device coordinator still does that
if the token is actually dead.

The schedule is owned by setup, at ``HISTORY_SCAN_INTERVAL``, because this
coordinator's own ``update_interval`` is None. That keeps a history failure
from shortening the device poll.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .coordinator import CatGenieConfigEntry
from .history import HISTORY_SCAN_INTERVAL, AccountHistory, load_window

_LOGGER = logging.getLogger(__name__)


def hass_timezone(hass: HomeAssistant) -> tuple[ZoneInfo, str, str]:
    """Return the HA timezone, or UTC when it is missing or invalid.

    Falling back to UTC is labeled. It is not a guess of the device zone.
    """
    name = getattr(getattr(hass, "config", None), "time_zone", None)
    if not isinstance(name, str) or not name:
        return ZoneInfo("UTC"), "UTC", "unconfigured_utc_fallback"
    try:
        return ZoneInfo(name), name, "home_assistant"
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC"), "UTC", "unconfigured_utc_fallback"


def history_failure(err: BaseException) -> UpdateFailed:
    """Map any history error to UpdateFailed, never a config-entry reauth."""
    if isinstance(err, ConfigEntryAuthFailed):
        err = err.__cause__ or err
    return UpdateFailed(f"CatGenie activity history unavailable ({type(err).__name__})")


class CatGenieHistoryCoordinator(DataUpdateCoordinator[AccountHistory]):
    """Poll cloud visit/flush history more slowly than device state."""

    config_entry: CatGenieConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: CatGenieConfigEntry,
        client: object,
    ) -> None:
        """Initialise a history coordinator that does not self-schedule."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}_history",
            update_interval=None,
        )
        self.client = client
        self.update_interval = None

    async def _async_update_data(self) -> AccountHistory:
        tz, _name, source = hass_timezone(self.hass)
        now = datetime.now(tz)
        try:
            return await load_window(
                self.client,
                now=now,
                tz=tz,
                timezone_source=source,
            )
        except Exception as err:  # noqa: BLE001 - isolate every history failure
            raise history_failure(err) from None


def bind_history(
    device_coordinator: object,
    history: CatGenieHistoryCoordinator,
) -> None:
    """Attach history beside the device coordinator. Do not replace it."""
    device_coordinator.history = history  # type: ignore[attr-defined]


# Re-exported so setup can schedule without importing the parser constants twice.
HISTORY_REFRESH_INTERVAL = HISTORY_SCAN_INTERVAL
