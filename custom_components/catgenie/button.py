"""Buttons for CatGenie A.I."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from catgenie import CatGenieClient
from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .abort import post_abort
from .coordinator import CatGenieConfigEntry, CatGenieCoordinator
from .entity import CatGenieEntity, async_run_command
from .no_scoop import post_no_scoop, special_cycle_firmware_eligible
from .operation_status import explicit_online
from .pause import post_pause
from .resume import post_resume


@dataclass(frozen=True, kw_only=True)
class CatGenieButtonDescription(ButtonEntityDescription):
    """Describe a CatGenie button."""

    press_fn: Callable[..., Awaitable[Any]]
    requires_explicit_online: bool = False
    requires_firmware_gate: bool = False
    offline_message: str = "CatGenie is not online; command was not sent."


BUTTONS: tuple[CatGenieButtonDescription, ...] = (
    CatGenieButtonDescription(
        key="start_cleaning",
        translation_key="start_cleaning",
        requires_explicit_online=True,
        press_fn=lambda client, mid: client.start_cleaning(mid),
    ),
    CatGenieButtonDescription(
        key="stop_cleaning",
        translation_key="stop_cleaning",
        requires_explicit_online=True,
        press_fn=lambda client, mid: client.stop_cleaning(mid),
    ),
    # Normal-cycle Pause, Resume, Abort, and No-scoop were owner-verified.
    # Fault resume and cartridge allowance effects are not proven.
    # entity_registry_enabled_default applies only when Home Assistant first
    # registers the entity. This module does not read or write the entity
    # registry, so an existing enabled or disabled choice is left alone.
    # Outbound state 2 is app SUSPENDED, not a reported-state contract.
    CatGenieButtonDescription(
        key="pause_cleaning",
        translation_key="pause_cleaning",
        entity_registry_enabled_default=True,
        requires_explicit_online=True,
        offline_message="CatGenie is not online; pause was not sent.",
        press_fn=post_pause,
    ),
    CatGenieButtonDescription(
        key="resume_cleaning",
        translation_key="resume_cleaning",
        entity_registry_enabled_default=True,
        requires_explicit_online=True,
        offline_message="CatGenie is not online; resume was not sent.",
        press_fn=post_resume,
    ),
    # Abort is app stopClean state 4. It does not replace Stop, which still
    # posts state 0. Reported integers are not a send guard.
    CatGenieButtonDescription(
        key="abort_cleaning",
        translation_key="abort_cleaning",
        entity_registry_enabled_default=True,
        requires_explicit_online=True,
        offline_message="CatGenie is not online; abort was not sent.",
        press_fn=post_abort,
    ),
    # No-scoop is app playSpecial state 129. The writer refuses unless the
    # traced fwVersion gate passes. Not a finishing cycle.
    CatGenieButtonDescription(
        key="no_scoop_cleaning",
        translation_key="no_scoop_cleaning",
        entity_registry_enabled_default=True,
        requires_explicit_online=True,
        requires_firmware_gate=True,
        offline_message="CatGenie is not online; no-scoop was not sent.",
        press_fn=post_no_scoop,
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
        self._attr_entity_registry_enabled_default = (
            description.entity_registry_enabled_default
        )

    @property
    def available(self) -> bool:
        """All buttons require an explicit online report.

        No-scoop also requires the traced firmware gate.
        """
        if not super().available:
            return False
        if (
            not self.entity_description.requires_explicit_online
            and not self.entity_description.requires_firmware_gate
        ):
            return True
        device = self.device
        if self.entity_description.requires_explicit_online:
            if device is None or not explicit_online(device):
                return False
        if self.entity_description.requires_firmware_gate:
            fw = getattr(device, "fw_version", None) if device is not None else None
            if not special_cycle_firmware_eligible(fw):
                return False
        return True

    async def async_press(self) -> None:
        """Send the command. Gated buttons are refused before any request."""
        device = self.device
        if self.entity_description.requires_explicit_online:
            if device is None or not explicit_online(device):
                raise HomeAssistantError(self.entity_description.offline_message)
        if self.entity_description.requires_firmware_gate:
            fw = getattr(device, "fw_version", None) if device is not None else None
            if not special_cycle_firmware_eligible(fw):
                raise HomeAssistantError(
                    "CatGenie firmware is not eligible for no-scoop; nothing was sent."
                )
            command = post_no_scoop(
                self.coordinator.client, self._manufacturer_id, fw
            )
        else:
            command = self.entity_description.press_fn(
                self.coordinator.client, self._manufacturer_id
            )
        await async_run_command(self.coordinator, command)
