"""Switches for CatGenie A.I."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from catgenie import CatGenieClient, Device
from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import CatGenieConfigEntry, CatGenieCoordinator
from .entity import CatGenieEntity, async_run_command


@dataclass(frozen=True, kw_only=True)
class CatGenieSwitchDescription(SwitchEntityDescription):
    """Describe a CatGenie switch."""

    is_on_fn: Callable[[Device], bool | None]
    set_fn: Callable[[CatGenieClient, str, bool], Awaitable[Any]]
    supported_fn: Callable[[Device], bool] = lambda _device: True


SWITCHES: tuple[CatGenieSwitchDescription, ...] = (
    CatGenieSwitchDescription(
        key="panel_lock",
        translation_key="panel_lock",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda d: bool(d.configuration.child_lock),
        set_fn=lambda client, mid, on: client.set_child_lock(mid, on),
    ),
    CatGenieSwitchDescription(
        key="extra_dry",
        translation_key="extra_dry",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda d: d.configuration.extra_dry,
        set_fn=lambda client, mid, on: client.set_extra_dry(mid, on),
    ),
    CatGenieSwitchDescription(
        key="extra_wash",
        translation_key="extra_wash",
        entity_category=EntityCategory.CONFIG,
        supported_fn=lambda d: d.configuration.binary_elements is not None,
        is_on_fn=lambda d: (
            d.configuration.binary_elements.extra_wash
            if d.configuration.binary_elements
            else None
        ),
        set_fn=lambda client, mid, on: client.set_extra_wash(mid, on),
    ),
    CatGenieSwitchDescription(
        key="extra_shake",
        translation_key="extra_shake",
        entity_category=EntityCategory.CONFIG,
        supported_fn=lambda d: d.configuration.binary_elements is not None,
        is_on_fn=lambda d: (
            d.configuration.binary_elements.extra_shake
            if d.configuration.binary_elements
            else None
        ),
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
        return self.entity_description.is_on_fn(device) if device else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the setting on."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the setting off."""
        await self._async_set(False)

    async def _async_set(self, on: bool) -> None:
        await async_run_command(
            self.coordinator,
            self.entity_description.set_fn(
                self.coordinator.client, self._manufacturer_id, on
            ),
        )
