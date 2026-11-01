"""Read-only notification and firmware diagnostics for one CatGenie device.

These entities listen to the account reader. They also follow the device
coordinator so installed-note attribution uses the current firmware. That
listener only rewrites state. It does not GET the feed or notes, and it does
not change the device poll. Current firmware stays the device-page
``sw_version``. There is no second current-firmware sensor and no install
control.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CatGenieCoordinator
from .entity import device_connections
from .read_information import (
    FW_UPDATE_TYPE,
    FeedParse,
    NotesResult,
    ParsedNotice,
    ReadSnapshot,
    announced_notice,
    select_latest,
)

_ATTR_BLOCKLIST = (
    "userId",
    "user_id",
    "deviceName",
    "device_name",
    "email",
    "invitation",
    "payload",
    "token",
    "refresh_token",
)


@dataclass(frozen=True, kw_only=True)
class CatGenieReadSensorDescription(SensorEntityDescription):
    """Describe one read-only diagnostic."""


READ_SENSORS: tuple[CatGenieReadSensorDescription, ...] = (
    CatGenieReadSensorDescription(
        key="latest_notification",
        translation_key="latest_notification",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    CatGenieReadSensorDescription(
        key="announced_firmware",
        translation_key="announced_firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    CatGenieReadSensorDescription(
        key="firmware_release_notes",
        translation_key="firmware_release_notes",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


def _snapshot(coordinator: object) -> ReadSnapshot | None:
    data = getattr(coordinator, "data", None)
    return data if isinstance(data, ReadSnapshot) else None


def _installed_version(devices: CatGenieCoordinator, manufacturer_id: str) -> str | None:
    device = devices.data.get(manufacturer_id)
    firmware = getattr(device, "fw_version", None)
    if isinstance(firmware, str) and firmware:
        return firmware
    return None


def _notes_for(snapshot: ReadSnapshot, version: str | None) -> NotesResult | None:
    if not version:
        return None
    for row in snapshot.notes:
        if row.version == version:
            return row
    return None


def _counts(feed: FeedParse) -> dict[str, Any]:
    return {
        "response_count": feed.response_count,
        "complete_history": False,
        "notifications_shape": feed.notifications_shape,
        "unparsed_count": feed.unparsed_count,
        "malformed_count": feed.malformed_count,
        "unattributed_count": feed.unattributed_count,
        "conflict_count": feed.conflict_count,
        "sharing_discarded_count": feed.sharing_discarded_count,
    }


def _notice_attrs(notice: ParsedNotice, selection: str) -> dict[str, Any]:
    attrs: dict[str, Any] = {"latest_selection": selection}
    if notice.type_code is not None:
        attrs["type"] = notice.type_code
    if notice.type_name:
        attrs["type_name"] = notice.type_name
    if notice.creation_time_raw:
        attrs["creation_time"] = notice.creation_time_raw
    if notice.creation_time is not None:
        attrs["creation_time_aware"] = notice.creation_time.isoformat()
    return attrs


def latest_state(snapshot: ReadSnapshot, manufacturer_id: str) -> str:
    """Named type, raw integer, or unknown when no item is authoritative."""
    notice, _reason = select_latest(
        notice
        for notice in snapshot.feed.notices
        if notice.manufacturer_id == manufacturer_id
    )
    if notice is None:
        return "unknown"
    if notice.type_name:
        return notice.type_name
    if notice.type_code is not None:
        return str(notice.type_code)
    return "unknown"


def announced_state(snapshot: ReadSnapshot, manufacturer_id: str) -> str:
    """One type-24 version. No item, a missing version, or a tie is unknown."""
    notice, _reason = announced_notice(snapshot.feed, manufacturer_id)
    if notice is None or not notice.version:
        return "unknown"
    return notice.version


def notes_state(
    snapshot: ReadSnapshot,
    manufacturer_id: str,
    installed: str | None,
) -> str:
    """Available only when a fetched comments string is non-empty."""
    versions = []
    if installed:
        versions.append(installed)
    announced, _reason = announced_notice(snapshot.feed, manufacturer_id)
    if announced and announced.version and announced.version not in versions:
        versions.append(announced.version)
    for version in versions:
        row = _notes_for(snapshot, version)
        if row and row.comments:
            return "available"
    return "unknown"


def notes_available(
    snapshot: ReadSnapshot,
    manufacturer_id: str,
    installed: str | None,
) -> bool:
    """Unavailable when every relevant notes query failed and none can be shown."""
    versions = []
    if installed:
        versions.append(installed)
    announced, _reason = announced_notice(snapshot.feed, manufacturer_id)
    if announced and announced.version and announced.version not in versions:
        versions.append(announced.version)
    if not versions:
        return True
    rows = [_notes_for(snapshot, version) for version in versions]
    if any(row and row.comments for row in rows):
        return True
    if any(row and row.error for row in rows) and not any(
        row and row.comments for row in rows
    ):
        if all(row is None or row.error for row in rows):
            return False
    return True


def latest_attributes(snapshot: ReadSnapshot, manufacturer_id: str) -> dict[str, Any]:
    attrs = _counts(snapshot.feed)
    attributed = [
        notice
        for notice in snapshot.feed.notices
        if notice.manufacturer_id == manufacturer_id
    ]
    attrs["attributed_count"] = len(attributed)
    notice, reason = select_latest(attributed)
    if notice is None:
        attrs["latest_selection"] = reason
        return attrs
    attrs.update(_notice_attrs(notice, reason))
    return attrs


def announced_attributes(snapshot: ReadSnapshot, manufacturer_id: str) -> dict[str, Any]:
    notice, reason = announced_notice(snapshot.feed, manufacturer_id)
    ambiguous = reason == "ambiguous"
    attrs: dict[str, Any] = {
        "complete_history": False,
        "announcement": "ambiguous" if ambiguous else ("absent" if notice is None else "type_24"),
        "unknown_means_no_announcement": not ambiguous
        and (notice is None or not notice.version),
        "latest_selection": reason,
    }
    if notice is None:
        return attrs
    if notice.version:
        attrs["announced_version"] = notice.version
    else:
        attrs["announcement_without_version"] = True
    if notice.configuration_id:
        attrs["configuration_id"] = notice.configuration_id
    if notice.creation_time_raw:
        attrs["creation_time"] = notice.creation_time_raw
    if notice.creation_time is not None:
        attrs["creation_time_aware"] = notice.creation_time.isoformat()
    return attrs


def notes_attributes(
    snapshot: ReadSnapshot,
    manufacturer_id: str,
    installed: str | None,
) -> dict[str, Any]:
    attrs: dict[str, Any] = {
        "queried_name": list(snapshot.queried_versions),
        "query_key": "name",
    }
    if installed:
        attrs["installed_version"] = installed
        row = _notes_for(snapshot, installed)
        if row and row.comments:
            attrs["installed_notes"] = row.comments
        elif row and row.error:
            attrs["installed_notes_error"] = row.error
    announced, _reason = announced_notice(snapshot.feed, manufacturer_id)
    if announced and announced.version:
        attrs["announced_version"] = announced.version
        if announced.version != installed:
            row = _notes_for(snapshot, announced.version)
            if row and row.comments:
                attrs["announced_notes"] = row.comments
            elif row and row.error:
                attrs["announced_notes_error"] = row.error
    if not snapshot.queried_versions:
        attrs["notes_not_queried"] = True
    for forbidden in _ATTR_BLOCKLIST:
        attrs.pop(forbidden, None)
    return attrs


class CatGenieReadSensor(CoordinatorEntity, SensorEntity):
    """A diagnostic reading from the account feed or release-note GET."""

    _attr_has_entity_name = True
    # HA 2026.10 Entity contract: excluded from recorder, not from UI state.
    _unrecorded_attributes = frozenset({"installed_notes", "announced_notes"})
    entity_description: CatGenieReadSensorDescription

    def __init__(
        self,
        reader: object,
        devices: CatGenieCoordinator,
        manufacturer_id: str,
        description: CatGenieReadSensorDescription,
    ) -> None:
        """Initialise the sensor against the read coordinator."""
        super().__init__(reader)
        self._devices = devices
        self._manufacturer_id = manufacturer_id
        self.entity_description = description
        self._attr_unique_id = f"{manufacturer_id}_{description.key}"
        device = devices.data[manufacturer_id]
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

    async def async_added_to_hass(self) -> None:
        """Follow the reader and the device coordinator this state reads."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._devices.async_add_listener(self._handle_device_coordinator_update)
        )

    @callback
    def _handle_device_coordinator_update(self) -> None:
        """Recompute from current device data. Do not GET the feed or notes."""
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Unavailable when the feed failed or the device left the account.

        Device-sensor availability is independent. A feed failure does not
        mark the unit offline.
        """
        if not super().available or _snapshot(self.coordinator) is None:
            return False
        if self._manufacturer_id not in self._devices.data:
            return False
        snapshot = _snapshot(self.coordinator)
        if (
            snapshot is not None
            and self.entity_description.key == "firmware_release_notes"
            and not notes_available(
                snapshot,
                self._manufacturer_id,
                _installed_version(self._devices, self._manufacturer_id),
            )
        ):
            return False
        return True

    @property
    def native_value(self) -> str | None:
        """Return the diagnostic state. Unknown is not an installed version."""
        snapshot = _snapshot(self.coordinator)
        if snapshot is None:
            return None
        key = self.entity_description.key
        if key == "latest_notification":
            return latest_state(snapshot, self._manufacturer_id)
        if key == "announced_firmware":
            return announced_state(snapshot, self._manufacturer_id)
        if key == "firmware_release_notes":
            return notes_state(
                snapshot,
                self._manufacturer_id,
                _installed_version(self._devices, self._manufacturer_id),
            )
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return counts and notes. Never an account id or the raw payload."""
        snapshot = _snapshot(self.coordinator)
        if snapshot is None:
            return None
        key = self.entity_description.key
        if key == "latest_notification":
            attrs = latest_attributes(snapshot, self._manufacturer_id)
        elif key == "announced_firmware":
            attrs = announced_attributes(snapshot, self._manufacturer_id)
        else:
            attrs = notes_attributes(
                snapshot,
                self._manufacturer_id,
                _installed_version(self._devices, self._manufacturer_id),
            )
        for forbidden in _ATTR_BLOCKLIST:
            attrs.pop(forbidden, None)
        attrs.pop("user_id_present", None)
        return attrs


# Imported for a static check that type 24 is the only announcement source.
_TYPE_24 = FW_UPDATE_TYPE
