"""Switches for CatGenie A.I."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from catgenie import CatGenieClient, Device
from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import CatGenieConfigEntry, CatGenieCoordinator
from .configuration_lock import configuration_lock
from .entity import CatGenieEntity, async_run_command
from .operation_status import explicit_online


@dataclass(frozen=True, kw_only=True)
class CatGenieSwitchDescription(SwitchEntityDescription):
    """Describe a CatGenie switch."""

    set_fn: Callable[[CatGenieClient, str, bool], Awaitable[Any]]
    supported_fn: Callable[[Device], bool] = lambda _device: True


SWITCHES: tuple[CatGenieSwitchDescription, ...] = (
    CatGenieSwitchDescription(
        key="panel_lock",
        translation_key="panel_lock",
        entity_category=EntityCategory.CONFIG,
        set_fn=lambda client, mid, on: client.set_child_lock(mid, on),
    ),
    CatGenieSwitchDescription(
        key="extra_dry",
        translation_key="extra_dry",
        entity_category=EntityCategory.CONFIG,
        set_fn=lambda client, mid, on: client.set_extra_dry(mid, on),
    ),
    CatGenieSwitchDescription(
        key="extra_wash",
        translation_key="extra_wash",
        entity_category=EntityCategory.CONFIG,
        supported_fn=lambda d: d.configuration.binary_elements is not None,
        set_fn=lambda client, mid, on: client.set_extra_wash(mid, on),
    ),
    CatGenieSwitchDescription(
        key="extra_shake",
        translation_key="extra_shake",
        entity_category=EntityCategory.CONFIG,
        supported_fn=lambda d: d.configuration.binary_elements is not None,
        set_fn=lambda client, mid, on: client.set_extra_shake(mid, on),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CatGenieConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up CatGenie switches."""
    coordinator = entry.runtime_data
    async_add_entities(
        CatGenieSwitch(coordinator, manufacturer_id, description)
        for manufacturer_id, device in coordinator.data.items()
        for description in SWITCHES
        if description.supported_fn(device)
    )


class CatGenieSwitch(CatGenieEntity, SwitchEntity):
    """A CatGenie configuration switch."""

    entity_description: CatGenieSwitchDescription

    def __init__(
        self,
        coordinator: CatGenieCoordinator,
        manufacturer_id: str,
        description: CatGenieSwitchDescription,
    ) -> None:
        """Initialise the switch."""
        super().__init__(coordinator, manufacturer_id)
        self.entity_description = description
        self._attr_unique_id = f"{manufacturer_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return the switch state."""
        device = self.device
        if device is None or "configuration" not in device.model_fields_set:
            return None
        config = device.configuration
        key = self.entity_description.key
        if key in ("panel_lock", "extra_dry"):
            field = "child_lock" if key == "panel_lock" else "extra_dry"
            if field not in config.model_fields_set:
                return None
            value = getattr(config, field)
            if key == "panel_lock":
                return bool(value) if type(value) is int and value in (0, 1) else None
            return value if type(value) is bool else None
        if "binary_elements" not in config.model_fields_set:
            return None
        binary = config.binary_elements
        if binary is None or key not in binary.model_fields_set:
            return None
        value = getattr(binary, key, None)
        return value if type(value) is bool else None

    @property
    def available(self) -> bool:
        """Require the same explicit online evidence as other write controls."""
        return super().available and self.device is not None and explicit_online(self.device)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the setting on."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the setting off."""
        await self._async_set(False)

    async def _async_set(self, on: bool) -> None:
        async with configuration_lock(self.coordinator, self._manufacturer_id):
            await self._async_set_locked(on)

    async def _async_set_locked(self, on: bool) -> None:
        if self.device is None or not explicit_online(self.device):
            raise HomeAssistantError("CatGenie is not online; setting was not changed.")
        await async_run_command(
            self.coordinator,
            self.entity_description.set_fn(
                self.coordinator.client, self._manufacturer_id, on
            ),
        )
