"""Sensors for CatGenie A.I."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from catgenie import Device
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .cartridge import cartridge_capacity, cartridge_capacity_attributes
from .coordinator import CatGenieConfigEntry, CatGenieCoordinator
from .reported_config import (
    reported_activation_mode,
    reported_integer,
    reported_setting,
    reported_schedule_count,
    cartridge_type_attributes,
    cartridge_type_value,
    reported_dnd_attributes,
    reported_dnd_value,
    reported_timezone_attributes,
    reported_timezone_value,
)
from .entity import CatGenieEntity
from .operation_state import (
    OPERATION_STATE_OPTIONS,
    operation_error_attributes,
    operation_error_label,
    operation_state_attributes,
    operation_state_value,
)
from .operation_status import (
    operation_progress_value,
    operation_status_available,
    operation_status_text,
)


def _cleaning_mode(device: Device) -> str | None:
    """Use the same strict reported activation mode as cartridge ratings."""
    return reported_activation_mode(device)


def _schedule_attrs(device: Device) -> dict[str, Any]:
    return {
        "entries": [
            entry.model_dump(exclude_none=True)
            for entry in device.configuration.schedule
        ]
    }


@dataclass(frozen=True, kw_only=True)
class CatGenieSensorDescription(SensorEntityDescription):
    """Describe a CatGenie sensor."""

    value_fn: Callable[[Device], StateType | datetime]
    attrs_fn: Callable[[Device], dict[str, Any]] | None = None
    available_fn: Callable[[Device], bool] | None = None


SENSORS: tuple[CatGenieSensorDescription, ...] = (
    CatGenieSensorDescription(
        key="last_clean",
        translation_key="last_clean",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.last_clean,
    ),
    CatGenieSensorDescription(
        key="total_cycles",
        translation_key="total_cycles",
        native_unit_of_measurement="cycles",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: reported_integer(d, "total_cycles"),
    ),
    CatGenieSensorDescription(
        key="cartridge_remaining",
        translation_key="cartridge_remaining",
        native_unit_of_measurement="cycles",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: reported_integer(d, "remaining_sani_solution"),
    ),
    CatGenieSensorDescription(
        key="cartridge_capacity",
        translation_key="cartridge_capacity",
        native_unit_of_measurement="cycles",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=cartridge_capacity,
        attrs_fn=cartridge_capacity_attributes,
    ),
    CatGenieSensorDescription(
        key="operation_state",
        translation_key="operation_state",
        device_class=SensorDeviceClass.ENUM,
        options=list(OPERATION_STATE_OPTIONS),
        # 0 idle, 1 cleaning. Reported 2 is paused only for an explicit
        # no-error connected report. Other integers are "error" plus raw_state.
        # Do not use is_cleaning: it is False for unrecognized states.
        value_fn=operation_state_value,
        attrs_fn=operation_state_attributes,
    ),
    CatGenieSensorDescription(
        key="operation_progress",
        translation_key="operation_progress",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=operation_progress_value,
    ),
    CatGenieSensorDescription(
        key="operation_status",
        translation_key="operation_status",
        value_fn=operation_status_text,
        available_fn=operation_status_available,
    ),
    CatGenieSensorDescription(
        key="operation_error",
        translation_key="operation_error",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=operation_error_label,
        attrs_fn=operation_error_attributes,
    ),
    CatGenieSensorDescription(
        key="cleaning_mode",
        translation_key="cleaning_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=["cat", "time", "manual"],
        value_fn=_cleaning_mode,
    ),
    CatGenieSensorDescription(
        key="scheduled_cycles",
        translation_key="scheduled_cycles",
        value_fn=reported_schedule_count,
        attrs_fn=_schedule_attrs,
    ),
    CatGenieSensorDescription(
        key="cat_activation_delay",
        translation_key="cat_activation_delay",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: reported_setting(d, "cat_delay"),
    ),
    CatGenieSensorDescription(
        key="panel_lock_delay",
        translation_key="panel_lock_delay",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: reported_setting(d, "auto_lock"),
    ),
    CatGenieSensorDescription(
        key="cat_sensitivity",
        translation_key="cat_sensitivity",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: reported_integer(d, "cat_sense"),
    ),
    CatGenieSensorDescription(
        key="volume_level",
        translation_key="volume_level",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: reported_setting(d, "volume_level"),
    ),
    CatGenieSensorDescription(
        key="network_type",
        translation_key="network_type",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.connection_mode or None,
    ),
    # Local schedule display remains unverified in reported_config.py.
    # Do not duplicate the scheduled_cycles count here.
    CatGenieSensorDescription(
        key="cartridge_type",
        translation_key="cartridge_type",
        device_class=SensorDeviceClass.ENUM,
        options=["missing", "regular", "maintenance", "unknown"],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=cartridge_type_value,
        attrs_fn=cartridge_type_attributes,
    ),
    CatGenieSensorDescription(
        key="reported_timezone",
        translation_key="reported_timezone",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=reported_timezone_value,
        attrs_fn=reported_timezone_attributes,
    ),
    CatGenieSensorDescription(
        key="reported_dnd",
        translation_key="reported_dnd",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=reported_dnd_value,
        attrs_fn=reported_dnd_attributes,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CatGenieConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up CatGenie sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        CatGenieSensor(coordinator, manufacturer_id, description)
        for manufacturer_id in coordinator.data
        for description in SENSORS
    )
    history = getattr(coordinator, "history", None)
    if history is None:
        return
    from .activity import ACTIVITY_SENSORS, CatGenieActivitySensor

    async_add_entities(
        CatGenieActivitySensor(history, coordinator, manufacturer_id, description)
        for manufacturer_id in coordinator.data
        for description in ACTIVITY_SENSORS
    )
    reader = getattr(coordinator, "read_information", None)
    if reader is None:
        return
    from .read_sensors import READ_SENSORS, CatGenieReadSensor

    async_add_entities(
        CatGenieReadSensor(reader, coordinator, manufacturer_id, description)
        for manufacturer_id in coordinator.data
        for description in READ_SENSORS
    )


class CatGenieSensor(CatGenieEntity, SensorEntity):
    """A CatGenie sensor."""

    entity_description: CatGenieSensorDescription

    def __init__(
        self,
        coordinator: CatGenieCoordinator,
        manufacturer_id: str,
        description: CatGenieSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, manufacturer_id)
        self.entity_description = description
        self._attr_unique_id = f"{manufacturer_id}_{description.key}"

    @property
    def available(self) -> bool:
        """Keep the shared presence rule, with an optional connectivity gate."""
        if not super().available:
            return False
        available_fn = self.entity_description.available_fn
        if available_fn is None:
            return True
        device = self.device
        return bool(device and available_fn(device))

    @property
    def native_value(self) -> StateType | datetime:
        """Return the sensor value."""
        device = self.device
        return self.entity_description.value_fn(device) if device else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return optional extra attributes."""
        device = self.device
        attrs_fn = self.entity_description.attrs_fn
        return attrs_fn(device) if device and attrs_fn else None
