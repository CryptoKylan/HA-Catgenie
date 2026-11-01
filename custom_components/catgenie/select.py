"""Activation-mode select for CatGenie A.I."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .configuration import (
    ACTIVATION_OPTIONS,
    SettingsWriteRefused,
    activation_label,
    activation_payload,
    refusal_message,
)
from .coordinator import CatGenieConfigEntry, CatGenieCoordinator
from .configuration_lock import configuration_lock
from .entity import CatGenieEntity, async_run_command
from .settings_pending import (
    SettingsPending,
    displayed,
    note_accepted,
    pending_attributes,
)

SELECTS: tuple[SelectEntityDescription, ...] = (
    SelectEntityDescription(
        key="activation_mode",
        translation_key="activation_mode",
        entity_category=EntityCategory.CONFIG,
        options=list(ACTIVATION_OPTIONS),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CatGenieConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Cat/Manual/Time select."""
    coordinator = entry.runtime_data
    async_add_entities(
        CatGenieSelect(coordinator, manufacturer_id, description)
        for manufacturer_id in coordinator.data
        for description in SELECTS
    )


class CatGenieSelect(CatGenieEntity, SelectEntity):
    """Cat, Manual, or Time activation. Not a cycle command."""

    entity_description: SelectEntityDescription
    _attr_options = list(ACTIVATION_OPTIONS)

    def __init__(
        self,
        coordinator: CatGenieCoordinator,
        manufacturer_id: str,
        description: SelectEntityDescription,
    ) -> None:
        """Initialise the select."""
        super().__init__(coordinator, manufacturer_id)
        self.entity_description = description
        self._attr_unique_id = f"{manufacturer_id}_{description.key}"
        self._pending = SettingsPending()

    @property
    def options(self) -> list[str]:
        """Return label options, not wire or presentation enums."""
        return list(ACTIVATION_OPTIONS)

    def _activation_view(self) -> tuple[str | None, bool]:
        device = self.device
        return displayed(
            self,
            self._pending,
            activation_label(device),
            present=device is not None,
        )

    @property
    def current_option(self) -> str | None:
        """Return the polled label, or an accepted request still awaiting that poll."""
        value, _holding = self._activation_view()
        return value

    @property
    def extra_state_attributes(self) -> dict[str, bool] | None:
        """Mark an unconfirmed hold. This is not vendor confirmation."""
        _value, holding = self._activation_view()
        return pending_attributes(holding)

    async def async_select_option(self, option: str) -> None:
        """Serialize this setting with all other writers for this device."""
        async with configuration_lock(self.coordinator, self._manufacturer_id):
            await self._async_select_option(option)

    async def _async_select_option(self, option: str) -> None:
        """Write the paired mode/manual fields, then refresh once.

        The requested label is held only after the PUT await returns. The
        existing refresh is unchanged and is not treated as confirmation.
        """
        try:
            payload = activation_payload(self.device, option)
        except SettingsWriteRefused as err:
            raise HomeAssistantError(refusal_message("activation mode", err.reason)) from err
        token = self._pending.start()
        baseline = activation_label(self.device)

        async def _command() -> None:
            await self.coordinator.client.update_configuration(
                self._manufacturer_id, **payload
            )
            note_accepted(self, self._pending, token, option, baseline)

        await async_run_command(self.coordinator, _command())
