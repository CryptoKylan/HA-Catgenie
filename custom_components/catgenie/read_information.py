"""Read-only notification feed and firmware-note parsing.

The pinned client's list model defaults a missing type to 0. This module
parses the raw GET body instead. It does not open a connection by itself
except through ``load_read_information``, which calls the shared client
for two GET paths.

The app skips a refetch when notifications were updated within an
environment value (``app-index.hasm`` 780906: "Notifications already updated
in the last " plus that value plus " seconds"). That number was not
recovered. Thirty minutes is a local bound, slower than the 15-minute
history poll and the 15s/60s device poll. It is not a vendor limit.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

FEED_PATH = "notification/v1/push/user"
NOTES_PATH = "device/update/versions/comments"
FW_UPDATE_TYPE = 24
SHARING_TYPES = frozenset(range(101, 107))
READ_INFORMATION_INTERVAL = timedelta(minutes=30)

# Integer wire values from the app NOTIFICATION_TYPES object. Gaps are omitted.
# String-valued keys are not wire types and are not listed here.
NOTIFICATION_TYPES: dict[int, str] = {
    1: "MISSING_LIGHT",
    2: "LOW_WATER_PRESSURE",
    3: "DRAINAGE_PROBLEM",
    4: "BI_METAL",
    5: "MISSING_CARTRIDGE",
    6: "EMPTY_CARTRIDGE",
    7: "CARTRIDGE_LOW_LEVEL",
    8: "INCORRECT_CARTRIDGE",
    9: "CLEAN_LIGHT_GUIDE",
    10: "LIGHT_GUIDE_DIRTY",
    11: "EWI_W_WATER_IDIOPATHIC",
    17: "CYCLE_POSTPONDED",
    20: "PET_VISITED",
    21: "SYSTEM_MESSAGE",
    22: "FW_FAILED",
    24: "FW_UPDATE",
    25: "FW_SUCCESS",
    29: "CG_CONNECTION_CHANGE",
    30: "DEVICE_DETAILS_CHANGED",
    31: "RESET_NOTIFICATIONS",
    51: "E_TEMP_MISSING",
    52: "EWI_E_TEMP_OUTLET_MISSING",
    61: "E_TEMP_SHORT",
    62: "EWI_E_TEMP_OUTLET_SHORT",
    91: "EWI_W_HEATER_CLOG",
    101: "INVITE_TO_SHARE_ACCOUNT",
    102: "USER_ACCEPTED_INVITATION",
    103: "USER_REJECTED_INVITATION",
    104: "USER_REMOVED_FROM_ACCOUNT",
    105: "ADMIN_CHANGED",
    106: "USER_LEFT_ACCOUNT",
    1002: "AIRWAY_CLOGGED",
}

_OFFSET = re.compile(r"(?:Z|[+-]\d{2}:\d{2}|[+-]\d{4})$")
_MISSING = object()


@dataclass(frozen=True)
class KnownDevice:
    """A device identity already on the device coordinator."""

    manufacturer_id: str
    firmware_version: str | None


@dataclass(frozen=True)
class ParsedNotice:
    """One parsed, non-sharing notice. Bodies of types 101-106 are not kept."""

    type_code: int | None
    type_name: str | None
    manufacturer_id: str | None
    creation_time_raw: str | None
    creation_time: datetime | None
    version: str | None
    configuration_id: str | None
    attribution: str


@dataclass(frozen=True)
class FeedParse:
    """One feed response. ``response_count`` is this list, not a history."""

    response_count: int | None
    notifications_shape: str
    unparsed_count: int
    malformed_count: int
    unattributed_count: int
    conflict_count: int
    sharing_discarded_count: int
    notices: tuple[ParsedNotice, ...]
    complete_history: bool = False
    user_id_present: bool = False


@dataclass(frozen=True)
class NotesResult:
    """Release notes for one version already in hand."""

    version: str
    comments: str | None
    error: str | None


@dataclass(frozen=True)
class ReadSnapshot:
    """Account read. A notes error does not erase a successful feed."""

    feed: FeedParse
    notes: tuple[NotesResult, ...]
    queried_versions: tuple[str, ...]


def parse_creation_time(value: object) -> tuple[str | None, datetime | None]:
    """Keep the raw string. Parse only an offset or Z. Do not apply a host zone."""
    if not isinstance(value, str) or not value:
        return None, None
    if _OFFSET.search(value) is None:
        return value, None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    if re.search(r"[+-]\d{4}$", normalized):
        normalized = normalized[:-2] + ":" + normalized[-2:]
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return value, None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return value, None
    return value, parsed


def _identity(value: object) -> str | None:
    """Return an exact non-empty string id. Empty, zero, and other types are missing."""
    if isinstance(value, str) and value:
        return value
    return None


def _version(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _type_fields(parsed: Mapping[str, Any]) -> tuple[int | None, str | None]:
    if "type" not in parsed or parsed.get("type") is None:
        return None, None
    raw = parsed.get("type")
    if type(raw) is not int:
        return None, None
    return raw, NOTIFICATION_TYPES.get(raw)


def parse_feed(body: object, known_ids: Iterable[str]) -> FeedParse:
    """Parse one raw feed body. Do not default a missing type or device id."""
    known = {item for item in known_ids if isinstance(item, str) and item}
    user_id_present = isinstance(body, dict) and "userId" in body
    if not isinstance(body, dict):
        return FeedParse(
            None, "not_an_object", 0, 0, 0, 0, 0, (), user_id_present=user_id_present
        )
    raw_items = body.get("notifications", _MISSING)
    if raw_items is _MISSING:
        return FeedParse(
            None, "missing", 0, 0, 0, 0, 0, (), user_id_present=user_id_present
        )
    if not isinstance(raw_items, list):
        return FeedParse(
            None, "not_a_list", 0, 0, 0, 0, 0, (), user_id_present=user_id_present
        )

    notices: list[ParsedNotice] = []
    unparsed = malformed = unattributed = conflicts = sharing = 0
    for item in raw_items:
        if not isinstance(item, dict):
            malformed += 1
            continue
        raw_data = item.get("data", _MISSING)
        if not isinstance(raw_data, str) or not raw_data:
            unparsed += 1
            continue
        try:
            parsed = json.loads(raw_data)
        except (json.JSONDecodeError, TypeError, ValueError):
            unparsed += 1
            continue
        if not isinstance(parsed, dict):
            unparsed += 1
            continue
        type_code, type_name = _type_fields(parsed)
        if type_code in SHARING_TYPES:
            sharing += 1
            continue
        parent = _identity(parsed.get("parentDeviceId"))
        device = _identity(parsed.get("deviceId"))
        if parent is not None and device is not None and parent != device:
            attribution = "conflict"
            manufacturer_id = None
            conflicts += 1
            unattributed += 1
        elif parent in known:
            attribution = "attributed"
            manufacturer_id = parent
        elif device in known:
            attribution = "attributed"
            manufacturer_id = device
        else:
            attribution = "unattributed"
            manufacturer_id = None
            unattributed += 1
        raw_clock, aware = parse_creation_time(item.get("creationTime"))
        notices.append(
            ParsedNotice(
                type_code=type_code,
                type_name=type_name,
                manufacturer_id=manufacturer_id,
                creation_time_raw=raw_clock,
                creation_time=aware,
                version=_version(parsed.get("version")),
                configuration_id=_identity(parsed.get("configurationId")),
                attribution=attribution,
            )
        )
    return FeedParse(
        response_count=len(raw_items),
        notifications_shape="list",
        unparsed_count=unparsed,
        malformed_count=malformed,
        unattributed_count=unattributed,
        conflict_count=conflicts,
        sharing_discarded_count=sharing,
        notices=tuple(notices),
        user_id_present=user_id_present,
    )


def _publication_key(notice: ParsedNotice) -> tuple[object, ...]:
    """Identity a consumer would publish. This is not a version order."""
    return (
        notice.manufacturer_id,
        notice.type_code,
        notice.version,
        notice.configuration_id,
    )


def select_latest(
    notices: Iterable[ParsedNotice],
) -> tuple[ParsedNotice | None, str]:
    """Pick one offset-aware maximum. Disagreeing equal times are ambiguous.

    Naive clocks are not ordered by the host zone. A tie is not broken by
    response index or by version text.
    """
    rows = list(notices)
    if not rows:
        return None, "absent"
    aware: list[ParsedNotice] = []
    aware_times: list[datetime] = []
    for notice in rows:
        if notice.creation_time is not None:
            aware.append(notice)
            aware_times.append(notice.creation_time)
    if aware:
        latest_time = max(aware_times)
        maximal = [notice for notice in aware if notice.creation_time == latest_time]
        if len({_publication_key(notice) for notice in maximal}) != 1:
            return None, "ambiguous"
        return maximal[0], "offset_aware_max"
    return rows[-1], "response_order"


def _for_device(feed: FeedParse, manufacturer_id: str) -> tuple[ParsedNotice, ...]:
    return tuple(
        notice
        for notice in feed.notices
        if notice.manufacturer_id == manufacturer_id
    )


def announced_notice(
    feed: FeedParse, manufacturer_id: str
) -> tuple[ParsedNotice | None, str]:
    """Return one type-24 notice, or absent/ambiguous when none is authoritative."""
    matches = [
        notice
        for notice in _for_device(feed, manufacturer_id)
        if notice.type_code == FW_UPDATE_TYPE
    ]
    return select_latest(matches)


def announced_version(feed: FeedParse, manufacturer_id: str) -> str | None:
    """Version from one unambiguous type-24 item. A tie is not a version."""
    notice, _reason = announced_notice(feed, manufacturer_id)
    if notice is None:
        return None
    return notice.version


def parse_comments(body: object) -> str | None:
    """Return comments only when it is a non-empty string. '' is not notes."""
    if not isinstance(body, dict):
        return None
    comments = body.get("comments")
    if isinstance(comments, str) and comments:
        return comments
    return None


def notes_query(version: str) -> dict[str, str]:
    """The app and pinned client use query key ``name``, not ``version``."""
    return {"name": version}


def versions_in_hand(
    devices: Iterable[KnownDevice], feed: FeedParse
) -> tuple[str, ...]:
    """Versions already known. Do not invent one in order to fetch notes."""
    found: list[str] = []
    seen: set[str] = set()

    def add(value: str | None) -> None:
        if value and value not in seen:
            seen.add(value)
            found.append(value)

    for device in devices:
        add(device.firmware_version)
    for notice in feed.notices:
        if notice.type_code == FW_UPDATE_TYPE and notice.manufacturer_id:
            add(notice.version)
    return tuple(found)


def known_devices_from(device_coordinator: object) -> tuple[KnownDevice, ...]:
    """Read identities already polled. Do not copy names or account ids."""
    data = getattr(device_coordinator, "data", None) or {}
    found: list[KnownDevice] = []
    if not isinstance(data, Mapping):
        return ()
    for manufacturer_id, device in data.items():
        if not isinstance(manufacturer_id, str) or not manufacturer_id:
            continue
        firmware = getattr(device, "fw_version", None)
        found.append(
            KnownDevice(
                manufacturer_id,
                firmware if isinstance(firmware, str) and firmware else None,
            )
        )
    return tuple(found)


async def _allowed_get(client: object, path: str, params: dict[str, str] | None = None) -> Any:
    if path == FEED_PATH:
        if params:
            raise RuntimeError("notification feed takes no query")
        return await client._request("GET", path)  # type: ignore[attr-defined]
    if path == NOTES_PATH:
        if (
            not isinstance(params, dict)
            or set(params) != {"name"}
            or not isinstance(params.get("name"), str)
            or not params["name"]
        ):
            raise RuntimeError("release notes require query key name")
        return await client._request("GET", path, params={"name": params["name"]})  # type: ignore[attr-defined]
    raise RuntimeError("read-information refused a non-allowlisted request")


async def load_read_information(
    client: object, devices: Iterable[KnownDevice]
) -> ReadSnapshot:
    """GET the account feed once, then notes once per version already in hand."""
    device_rows = tuple(devices)
    feed = parse_feed(
        await _allowed_get(client, FEED_PATH),
        [device.manufacturer_id for device in device_rows],
    )
    versions = versions_in_hand(device_rows, feed)
    notes: list[NotesResult] = []
    for version in versions:
        try:
            body = await _allowed_get(client, NOTES_PATH, notes_query(version))
        except Exception as err:  # noqa: BLE001 - one notes failure must not erase the feed
            notes.append(NotesResult(version, None, type(err).__name__))
            continue
        notes.append(NotesResult(version, parse_comments(body), None))
    return ReadSnapshot(feed, tuple(notes), versions)
