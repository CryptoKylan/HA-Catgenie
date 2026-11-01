"""Read-only activity sensors for one CatGenie device.

These entities listen to the history coordinator, not the 15s/60s device
poll. They do not replace cartridge, cycle, completed-cleaning or recovery
counters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CatGenieCoordinator
from .entity import device_connections, extra
from .history import (
    LOCAL_COUNTER_KEYS,
    DeviceActivity,
    DeviceFilter,
    activity_sensor_state,
    device_filter_from_identity,
)


@dataclass(frozen=True, kw_only=True)
class CatGenieActivitySensorDescription(SensorEntityDescription):
    """Describe one activity sensor."""


ACTIVITY_SENSORS: tuple[CatGenieActivitySensorDescription, ...] = (
    CatGenieActivitySensorDescription(
        key="visits_today",
        translation_key="visits_today",
        native_unit_of_measurement="visits",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    CatGenieActivitySensorDescription(
        key="last_visit",
        translation_key="last_visit",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    CatGenieActivitySensorDescription(
        key="last_visit_duration",
        translation_key="last_visit_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    CatGenieActivitySensorDescription(
        key="aborted_cycles",
        translation_key="aborted_cycles",
        native_unit_of_measurement="cycles",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


class CatGenieActivitySensor(CoordinatorEntity, SensorEntity):
    """A cloud activity reading for one already-registered device."""

    _attr_has_entity_name = True
    _unrecorded_attributes = frozenset({"visit_diary", "flush_diary"})
    entity_description: CatGenieActivitySensorDescription

    def __init__(
        self,
        history: object,
        devices: CatGenieCoordinator,
        manufacturer_id: str,
        description: CatGenieActivitySensorDescription,
    ) -> None:
        """Initialise the sensor against the history coordinator."""
        super().__init__(history)
        self._devices = devices
        self._manufacturer_id = manufacturer_id
        self.entity_description = description
        self._attr_unique_id = f"{manufacturer_id}_{description.key}"
        device = devices.data[manufacturer_id]
        self._filter = activity_filter(device)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, manufacturer_id)},
            name=device.name,
            manufacturer="PetNovations",
            model="CatGenie A.I.",
            sw_version=device.fw_version,
            hw_version=device.hw_revision,
            serial_number=manufacturer_id,
            connections=device_connections(device.mac_address),
        )

    @property
    def available(self) -> bool:
        """Unavailable when history failed or the device left the account.

        Device-sensor availability is independent. A history failure does not
        mark the unit offline.
        """
        if not super().available:
            return False
        if self.coordinator.data is None:
            return False
        return self._manufacturer_id in self._devices.data

    @property
    def _activity(self) -> DeviceActivity | None:
        data = self.coordinator.data
        if data is None:
            return None
        return data.for_device(self._filter)

    @property
    def native_value(self) -> Any:
        """Return the reading, or None when it cannot be counted."""
        activity = self._activity
        if activity is None:
            return None
        return activity_sensor_state(activity, self.entity_description.key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the window contract. Never a pet profile."""
        activity = self._activity
        if activity is None:
            return None
        attrs = activity.sensor_attributes()
        attrs["activity_sensor"] = self.entity_description.key
        for forbidden in LOCAL_COUNTER_KEYS:
            attrs.pop(forbidden, None)
        return attrs


def activity_filter(device: Any) -> DeviceFilter:
    """Filter used by an activity sensor for a real device model.

    ``manufacturerId`` is the cloud serial. ``macAddress`` is the cloud
    ``deviceId``. Extras are passed through and kept only when unambiguous.
    """
    return device_filter_from_identity(
        device.manufacturer_id,
        {
            "serialNumber": extra(device, "serialNumber"),
            "deviceId": extra(device, "deviceId"),
        },
        mac_address=device.mac_address,
    )
