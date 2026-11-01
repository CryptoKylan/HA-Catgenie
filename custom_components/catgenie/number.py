"""Bounded volume and auto-lock timeout controls for CatGenie A.I."""

from __future__ import annotations

from catgenie import Device
from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .configuration import (
    VOLUME_MAX,
    VOLUME_MIN,
    SettingsWriteRefused,
    auto_lock_payload,
    cat_delay_payload,
    display_auto_lock_minutes,
    display_cat_delay_minutes,
    display_volume,
    guard_cat_delay_before_read,
    refusal_message,
    volume_payload,
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

NUMBERS: tuple[NumberEntityDescription, ...] = (
    NumberEntityDescription(
        key="volume",
        translation_key="volume",
        entity_category=EntityCategory.CONFIG,
        native_min_value=VOLUME_MIN,
        native_max_value=VOLUME_MAX,
        native_step=1,
        mode=NumberMode.BOX,
    ),
    NumberEntityDescription(
        key="auto_lock_timeout",
        translation_key="auto_lock_timeout",
        entity_category=EntityCategory.CONFIG,
        native_min_value=0,
        native_max_value=30,
        native_step=5,
        mode=NumberMode.BOX,
        native_unit_of_measurement=UnitOfTime.MINUTES,
    ),
    NumberEntityDescription(
        key="cat_activation_delay",
        translation_key="cat_activation_delay",
        entity_category=EntityCategory.CONFIG,
        native_min_value=5,
        native_max_value=30,
        native_step=5,
        mode=NumberMode.BOX,
        native_unit_of_measurement=UnitOfTime.MINUTES,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CatGenieConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up volume, auto-lock timeout, and cat activation delay."""
    coordinator = entry.runtime_data
    async_add_entities(
        CatGenieNumber(coordinator, manufacturer_id, description)
        for manufacturer_id in coordinator.data
        for description in NUMBERS
    )


class CatGenieNumber(CatGenieEntity, NumberEntity):
    """Volume is 1–7. Auto-lock is 0 or 5–30 minutes. Cat delay is 5–30 minutes."""

    entity_description: NumberEntityDescription
    _attr_native_min_value = VOLUME_MIN
    _attr_native_max_value = VOLUME_MAX
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = None

    def __init__(
        self,
        coordinator: CatGenieCoordinator,
        manufacturer_id: str,
        description: NumberEntityDescription,
    ) -> None:
        """Initialise the number."""
        super().__init__(coordinator, manufacturer_id)
        self.entity_description = description
        self._attr_unique_id = f"{manufacturer_id}_{description.key}"
        self._pending = SettingsPending()
        if description.key == "auto_lock_timeout":
            self._attr_native_min_value = 0
            self._attr_native_max_value = 30
            self._attr_native_step = 5
            self._attr_native_unit_of_measurement = UnitOfTime.MINUTES
        elif description.key == "cat_activation_delay":
            self._attr_native_min_value = 5
            self._attr_native_max_value = 30
            self._attr_native_step = 5
            self._attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def _is_auto_lock(self) -> bool:
        return self.entity_description.key == "auto_lock_timeout"

    def _is_cat_delay(self) -> bool:
        return self.entity_description.key == "cat_activation_delay"

    @property
    def native_min_value(self) -> float:
        """Return the proven minimum for this control."""
        if self._is_cat_delay():
            return 5.0
        if self._is_auto_lock():
            return 0.0
        return float(VOLUME_MIN)

    @property
    def native_max_value(self) -> float:
        """Return the proven maximum for this control."""
        if self._is_cat_delay() or self._is_auto_lock():
            return 30.0
        return float(VOLUME_MAX)

    @property
    def native_step(self) -> float:
        """Return the proven step. Auto-lock and cat delay are five minutes."""
        if self._is_cat_delay() or self._is_auto_lock():
            return 5.0
        return 1

    @property
    def mode(self) -> NumberMode:
        """Use a box so the UI cannot send a value outside the choice set."""
        return NumberMode.BOX

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Volume is a level. Auto-lock and cat delay are minutes; wire values are seconds."""
        if self._is_cat_delay() or self._is_auto_lock():
            return UnitOfTime.MINUTES
        return None

    def _shown(self) -> tuple[int | None, bool]:
        device = self.device
        if self._is_cat_delay():
            cloud = display_cat_delay_minutes(device)
        elif self._is_auto_lock():
            cloud = display_auto_lock_minutes(device)
        else:
            cloud = display_volume(device)
        return displayed(
            self,
            self._pending,
            cloud,
            present=device is not None,
        )

    @property
    def native_value(self) -> float | None:
        """Return the polled choice, or an accepted choice still awaiting that poll."""
        value, _holding = self._shown()
        return value

    @property
    def extra_state_attributes(self) -> dict[str, bool] | None:
        """Mark an unconfirmed hold. This is not vendor confirmation."""
        _value, holding = self._shown()
        return pending_attributes(holding)

    def _delay_device_from_read(self, devices: object) -> Device:
        """Pick this manufacturer from a get_devices() list. No cache write."""
        if not isinstance(devices, list) or any(
            not isinstance(item, Device) for item in devices
        ):
            raise HomeAssistantError(
                "CatGenie device read failed (unexpected); "
                "cat activation delay was not changed."
            )
        matches = [
            item
            for item in devices
            if item.manufacturer_id == self._manufacturer_id
        ]
        if len(matches) != 1:
            raise SettingsWriteRefused("missing")
        return matches[0]

    async def async_set_native_value(self, value: float) -> None:
        """Serialize the complete local GET/PUT/refresh transaction per device."""
        async with configuration_lock(self.coordinator, self._manufacturer_id):
            await self._async_set_native_value(value)

    async def _async_set_native_value(self, value: float) -> None:
        """Write the proven payload, then refresh once.

        The requested integer is held only after the PUT await returns.
        Cat delay calls ``coordinator.client.get_devices()`` once, outside
        this command's refresh, then sends dndFrom, dndTo, and catDelay
        from that snapshot. Volume and auto-lock still send one key and
        do not read devices.

        ``get_devices(self) -> list[Device]`` is the pinned client method.
        The integration client normalizes each thing with TolerantDevice.
        This read does not write coordinator.data, does not change the poll
        interval, and does not retry.

        A fresh read narrows the cached do-not-disturb race. It is not a
        remote compare-and-swap: another client can still change DND after
        this GET and before the PUT.
        """
        if self._is_cat_delay():
            setting = "cat activation delay"
            try:
                guard_cat_delay_before_read(self.device, value)
            except SettingsWriteRefused as err:
                raise HomeAssistantError(refusal_message(setting, err.reason)) from err
            try:
                devices = await self.coordinator.client.get_devices()
            except Exception as err:
                raise HomeAssistantError(
                    "CatGenie device read failed "
                    f"({type(err).__name__}); cat activation delay was not changed."
                ) from None
            try:
                fresh = self._delay_device_from_read(devices)
                delay_payload = cat_delay_payload(fresh, value)
            except SettingsWriteRefused as err:
                raise HomeAssistantError(refusal_message(setting, err.reason)) from err
            seconds = delay_payload["catDelay"]
            if type(seconds) is not int:
                raise HomeAssistantError(refusal_message(setting, "unsupported"))
            payload = delay_payload
            requested = seconds // 60
            baseline = display_cat_delay_minutes(self.device)
        elif self._is_auto_lock():
            setting = "auto-lock timeout"
            try:
                payload = auto_lock_payload(self.device, value)
            except SettingsWriteRefused as err:
                raise HomeAssistantError(refusal_message(setting, err.reason)) from err
            requested = payload["autoLock"] // 60
            baseline = display_auto_lock_minutes(self.device)
        else:
            setting = "volume"
            try:
                payload = volume_payload(self.device, value)
            except SettingsWriteRefused as err:
                raise HomeAssistantError(refusal_message(setting, err.reason)) from err
            requested = payload["volumeLevel"]
            baseline = display_volume(self.device)
        token = self._pending.start()

        async def _command() -> None:
            await self.coordinator.client.update_configuration(
                self._manufacturer_id, **payload
            )
            note_accepted(self, self._pending, token, requested, baseline)

        await async_run_command(self.coordinator, _command())
