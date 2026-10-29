"""Sensors for CatGenie A.I."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from catgenie import CleaningMode, Device
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

from .coordinator import CatGenieConfigEntry, CatGenieCoordinator
from .entity import CatGenieEntity, extra
from .operation_state import (
    OPERATION_STATE_OPTIONS,
    operation_error_attributes,
    operation_state_attributes,
    operation_state_label,
)


def _cleaning_mode(device: Device) -> str:
    """Map the device configuration to cat / time / manual activation.

    Mirrors the interpretation used by the earlier PetNovations integration:
    a separate ``manual`` flag wins, otherwise mode 0 is cat activation and
    mode 1 is time (scheduled) activation.
    """
    if extra(device.configuration, "manual") in (1, True):
        return "manual"
    return "cat" if device.configuration.mode == CleaningMode.AUTOMATIC else "time"


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
        value_fn=lambda d: d.configuration.total_cycles,
    ),
    CatGenieSensorDescription(
        key="cartridge_remaining",
        translation_key="cartridge_remaining",
        native_unit_of_measurement="cycles",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.remaining_sani_solution,
    ),
    CatGenieSensorDescription(
        key="cartridge_capacity",
        translation_key="cartridge_capacity",
        native_unit_of_measurement="cycles",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: extra(d, "totalSaniSolution"),
    ),
    CatGenieSensorDescription(
        key="operation_state",
        translation_key="operation_state",
        device_class=SensorDeviceClass.ENUM,
        options=list(OPERATION_STATE_OPTIONS),
        # 0 idle, 1 cleaning. The fallback is "error" plus raw_state.
        # Do not use is_cleaning: it is False for unrecognized states.
        value_fn=lambda d: operation_state_label(d.operation_status.state),
        attrs_fn=operation_state_attributes,
    ),
    CatGenieSensorDescription(
        key="operation_progress",
        translation_key="operation_progress",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.operation_status.clean_progress_pct,
    ),
    CatGenieSensorDescription(
        key="operation_error",
        translation_key="operation_error",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.operation_status.error or None,
        attrs_fn=operation_error_attributes,
    ),
    CatGenieSensorDescription(
        key="cleaning_mode",
        translation_key="cleaning_mode",
        device_class=SensorDeviceClass.ENUM,
        options=["cat", "time", "manual"],
        value_fn=_cleaning_mode,
    ),
    CatGenieSensorDescription(
        key="scheduled_cycles",
        translation_key="scheduled_cycles",
        value_fn=lambda d: sum(1 for e in d.configuration.schedule if e.enabled),
        attrs_fn=_schedule_attrs,
    ),
    CatGenieSensorDescription(
        key="cat_activation_delay",
        translation_key="cat_activation_delay",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.configuration.cat_delay,
    ),
    CatGenieSensorDescription(
        key="panel_lock_delay",
        translation_key="panel_lock_delay",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.configuration.auto_lock,
    ),
    CatGenieSensorDescription(
        key="cat_sensitivity",
        translation_key="cat_sensitivity",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.configuration.cat_sense,
    ),
    CatGenieSensorDescription(
        key="volume_level",
        translation_key="volume_level",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.configuration.volume_level,
    ),
    CatGenieSensorDescription(
        key="network_type",
        translation_key="network_type",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.connection_mode or None,
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
