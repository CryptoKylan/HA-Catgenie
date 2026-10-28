"""Binary sensors for CatGenie A.I."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from catgenie import Device
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import CatGenieConfigEntry, CatGenieCoordinator
from .entity import CatGenieEntity


@dataclass(frozen=True, kw_only=True)
class CatGenieBinarySensorDescription(BinarySensorEntityDescription):
    """Describe a CatGenie binary sensor."""

    is_on_fn: Callable[[Device], bool]


BINARY_SENSORS: tuple[CatGenieBinarySensorDescription, ...] = (
    CatGenieBinarySensorDescription(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda d: d.is_online,
    ),
    CatGenieBinarySensorDescription(
        key="cleaning",
        translation_key="cleaning",
        device_class=BinarySensorDeviceClass.RUNNING,
        is_on_fn=lambda d: d.is_cleaning,
    ),
    # The meaning of these two flags isn't documented by the vendor, so they
    # are exposed as raw diagnostics and disabled until the user opts in.
    CatGenieBinarySensorDescription(
        key="low_heater",
        translation_key="low_heater",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        is_on_fn=lambda d: d.low_heater,
    ),
    CatGenieBinarySensorDescription(
        key="fan_shutter",
        translation_key="fan_shutter",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        is_on_fn=lambda d: d.fan_shutter,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CatGenieConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up CatGenie binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        CatGenieBinarySensor(coordinator, manufacturer_id, description)
        for manufacturer_id in coordinator.data
        for description in BINARY_SENSORS
    )


class CatGenieBinarySensor(CatGenieEntity, BinarySensorEntity):
    """A CatGenie binary sensor."""

    entity_description: CatGenieBinarySensorDescription

    def __init__(
        self,
        coordinator: CatGenieCoordinator,
        manufacturer_id: str,
        description: CatGenieBinarySensorDescription,
    ) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator, manufacturer_id)
        self.entity_description = description
        self._attr_unique_id = f"{manufacturer_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return the state."""
        device = self.device
        return self.entity_description.is_on_fn(device) if device else None
