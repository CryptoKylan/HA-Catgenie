"""Base entity and helpers for CatGenie A.I."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from catgenie import CatGenieException, Device
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CatGenieCoordinator


def extra(model: Any, key: str) -> Any:
    """Return a field the library model doesn't declare, or None.

    The library's models allow extra fields, so values such as
    ``totalSaniSolution`` are reachable through ``model_extra``.
    """
    return (getattr(model, "model_extra", None) or {}).get(key)


class CatGenieEntity(CoordinatorEntity[CatGenieCoordinator]):
    """Common base for every CatGenie entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CatGenieCoordinator, manufacturer_id: str) -> None:
        """Initialise the entity and its device registry entry."""
        super().__init__(coordinator)
        self._manufacturer_id = manufacturer_id
        device = coordinator.data[manufacturer_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, manufacturer_id)},
            name=device.name,
            manufacturer="PetNovations",
            model="CatGenie A.I.",
            sw_version=device.fw_version,
            hw_version=device.hw_revision,
            serial_number=manufacturer_id,
            connections={(CONNECTION_NETWORK_MAC, format_mac(device.mac_address))},
        )

    @property
    def device(self) -> Device | None:
        """Return the latest data for this entity's device."""
        return self.coordinator.data.get(self._manufacturer_id)

    @property
    def available(self) -> bool:
        """Entity is available while the device is present in the account."""
        return super().available and self.device is not None


async def async_run_command(
    coordinator: CatGenieCoordinator, command: Awaitable[Any]
) -> None:
    """Send a command, surface failures nicely, then refresh state."""
    try:
        await command
    except CatGenieException as err:
        raise HomeAssistantError(f"CatGenie request failed: {err}") from err
    except Exception as err:  # noqa: BLE001 - curl_cffi network errors are not wrapped
        raise HomeAssistantError(f"Could not reach CatGenie: {err}") from err
    await coordinator.async_request_refresh()
