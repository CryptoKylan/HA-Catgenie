"""Data update coordinator for CatGenie A.I."""

from __future__ import annotations

import logging
import asyncio

from catgenie import (
    CatGenieAuthenticationError,
    CatGenieClient,
    CatGenieException,
    Device,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from pydantic import ValidationError

from .const import DOMAIN, SCAN_INTERVAL_ACTIVE, SCAN_INTERVAL_IDLE

_LOGGER = logging.getLogger(__name__)


class CatGenieCoordinator(DataUpdateCoordinator[dict[str, Device]]):
    """Poll the CatGenie cloud for every device on the account."""

    config_entry: CatGenieConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: CatGenieConfigEntry,
        client: CatGenieClient,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL_IDLE,
        )
        self.client = client
        self._configuration_locks: dict[str, asyncio.Lock] = {}

    async def _async_update_data(self) -> dict[str, Device]:
        try:
            devices = await self.client.get_devices()
        except CatGenieAuthenticationError:
            raise ConfigEntryAuthFailed(
                "CatGenie rejected the stored login; please sign in again"
            ) from None
        except CatGenieException as err:
            raise UpdateFailed(f"CatGenie API error ({type(err).__name__})") from None
        except ValidationError as err:
            # Even loc/type/ctx can contain vendor data. Count only; never
            # stringify the error or chain its input-bearing traceback.
            raise UpdateFailed(
                f"Unexpected CatGenie response format ({err.error_count()} validation errors)"
            ) from None
        except Exception as err:  # noqa: BLE001 - curl_cffi network errors are not wrapped
            raise UpdateFailed(f"Error communicating with CatGenie ({type(err).__name__})") from None

        self.update_interval = (
            SCAN_INTERVAL_ACTIVE
            if any(device.is_cleaning for device in devices)
            else SCAN_INTERVAL_IDLE
        )
        return {device.manufacturer_id: device for device in devices}


type CatGenieConfigEntry = ConfigEntry[CatGenieCoordinator]
