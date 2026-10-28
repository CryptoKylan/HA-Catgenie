"""Buttons for CatGenie A.I."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from catgenie import CatGenieClient
from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import CatGenieConfigEntry, CatGenieCoordinator
from .entity import CatGenieEntity, async_run_command


@dataclass(frozen=True, kw_only=True)
class CatGenieButtonDescription(ButtonEntityDescription):
    """Describe a CatGenie button."""

    press_fn: Callable[[CatGenieClient, str], Awaitable[Any]]


BUTTONS: tuple[CatGenieButtonDescription, ...] = (
    CatGenieButtonDescription(
        key="start_cleaning",
        translation_key="start_cleaning",
        press_fn=lambda client, mid: client.start_cleaning(mid),
    ),
    CatGenieButtonDescription(
        key="stop_cleaning",
        translation_key="stop_cleaning",
        press_fn=lambda client, mid: client.stop_cleaning(mid),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CatGenieConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up CatGenie buttons."""
    coordinator = entry.runtime_data
    async_add_entities(
        CatGenieButton(coordinator, manufacturer_id, description)
        for manufacturer_id in coordinator.data
        for description in BUTTONS
    )


class CatGenieButton(CatGenieEntity, ButtonEntity):
    """A CatGenie action button."""

    entity_description: CatGenieButtonDescription

    def __init__(
        self,
        coordinator: CatGenieCoordinator,
        manufacturer_id: str,
        description: CatGenieButtonDescription,
    ) -> None:
        """Initialise the button."""
        super().__init__(coordinator, manufacturer_id)
        self.entity_description = description
        self._attr_unique_id = f"{manufacturer_id}_{description.key}"

    async def async_press(self) -> None:
        """Send the command."""
        await async_run_command(
            self.coordinator,
            self.entity_description.press_fn(
                self.coordinator.client, self._manufacturer_id
            ),
        )
