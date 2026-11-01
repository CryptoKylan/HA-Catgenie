"""Independent CatGenie notification and firmware-note coordinator.

Device polling stays on ``CatGenieCoordinator`` at 15s/60s. This coordinator
does not replace ``entry.runtime_data`` and does not raise
``ConfigEntryAuthFailed``: a feed or notes failure must not tear down device
state or start re-authentication by itself. The device coordinator still does
that if the token is actually dead.

The schedule is owned by setup, at ``READ_INFORMATION_INTERVAL``, because this
coordinator's own ``update_interval`` is None. That keeps a feed failure from
shortening the device poll. The interval is a local bound, not a vendor limit.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .coordinator import CatGenieConfigEntry
from .read_information import (
    READ_INFORMATION_INTERVAL,
    ReadSnapshot,
    known_devices_from,
    load_read_information,
)

_LOGGER = logging.getLogger(__name__)


def read_failure(err: BaseException) -> UpdateFailed:
    """Map any read error to UpdateFailed, never a config-entry reauth."""
    if isinstance(err, ConfigEntryAuthFailed):
        err = err.__cause__ or err
    return UpdateFailed(
        f"CatGenie notification feed unavailable: {type(err).__name__}"
    )


class CatGenieReadCoordinator(DataUpdateCoordinator[ReadSnapshot]):
    """Poll the account feed more slowly than device state. One reader."""

    config_entry: CatGenieConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: CatGenieConfigEntry,
        client: object,
        devices: object,
    ) -> None:
        """Initialise a reader that does not self-schedule."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}_read_information",
            update_interval=None,
        )
        self.client = client
        self.devices = devices
        self.update_interval = None

    async def _async_update_data(self) -> ReadSnapshot:
        try:
            return await load_read_information(
                self.client, known_devices_from(self.devices)
            )
        except Exception as err:  # noqa: BLE001 - isolate every feed failure
            raise read_failure(err) from err


def bind_read_information(
    device_coordinator: object,
    reader: CatGenieReadCoordinator,
) -> None:
    """Attach the reader beside the device coordinator. Do not replace it."""
    device_coordinator.read_information = reader  # type: ignore[attr-defined]


READ_INFORMATION_REFRESH_INTERVAL = READ_INFORMATION_INTERVAL
