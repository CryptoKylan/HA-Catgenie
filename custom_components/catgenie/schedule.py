"""Schedule and Do Not Disturb contracts mirrored from the PetNovations app.

The Android app (com.petnovations 1.8.253/623) converts clock strings with
moment's phone-local zone, not ``configuration.timezone``:

* ``localTimeToUtcTime`` (function #12931) sets local hours on the current
  date, switches to UTC, and formats ``HH:mm:ss``.
* ``utcTimeToLocalTime`` (function #12930) is the display inverse.
* ``fixConfigurationSchedules`` (function #15556) maps every schedule entry
  through ``localTimeToUtcTime`` before ``setDeviceConfig``.
* Schedule display (function #20995) maps wire entries through
  ``utcTimeToLocalTime``. Display sorting uses ``stringTimeToSeconds``
  (function #12936) and must not be written back.
* A DND save object carries ``dndFrom``, ``dndTo`` and ``catDelay`` together
  (function #18377). The picker rejects an equal endpoint and a span above
  ten hours (function #18313). That ten-hour check is UI copy, not a proven
  server limit. Empty live fields do not prove a disable encoding.

* A schedule-list save (function #18484) PUTs only ``{schedule: [HH:MM:SS]}``
  after ``fixConfigurationSchedules``. The first-time mode-picker path
  (function #17991, ``switchToTimeActivationWhenDone``) also merges
  ``{manual: 0, mode: 1}``. A list edit must not do that. A populated schedule
  list alone is not time-cleaning activation.
* Add, edit, and delete mutate a local string list, then replace the whole
  array. Delete matches the clock string, not an index. An empty array is
  UI-saveable and would be PUT, but that is not a proven disable.
* Redux ``addScheduleToDevice`` / ``removeScheduleFromDevice`` update
  ``scheduleTimes`` only. They are not the HTTP write.

This pure preparation module does not itself register services or perform I/O.
The integration registers set_schedule and set_do_not_disturb through services.py
and their separate action modules. These older prepared fragments deliberately
stay ``sendable=False``; that flag does not describe the registered actions.
Ambiguous and missing civil times are rejected instead of folded. An empty
schedule list is refused rather than treated as disable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import re
from types import MappingProxyType
from typing import Any, Mapping
from zoneinfo import ZoneInfo

WRITABLE_HA_SERVICES: tuple[str, ...] = ("set_schedule", "set_do_not_disturb")
APP_UI_SCHEDULE_ROW_LIMIT = 8
APP_UI_DND_MAX = timedelta(hours=10)
APP_UI_DEFAULT_DND_HOURS = 6
_CLOCK = re.compile(r"^([01]\d|2[0-3]):([0-5]\d):([0-5]\d)$")
_OFFSET = re.compile(r"^([+-])(\d{2}):(\d{2})$")
_UNVERIFIED_WRITE_BLOCKERS = (
    "live_put_not_verified",
    "partial_configuration_put_preservation_not_verified",
    "wire_utc_basis_inferred_from_app_not_live_readback",
    "owner_schedule_readback_required",
)
SCHEDULE_EDIT_HTTP = MappingProxyType({
    "method": "PUT",
    "resource_uri": "device/management",
    "additional_path_template": "{manufacturerId}/configuration",
    "path_template": "device/management/{manufacturerId}/configuration",
    "edit_body_keys": ("schedule",),
    "forbidden_on_list_edit": ("mode", "manual"),
})
_SCHEDULE_OBSERVATION = (
    "Live acceptance requires an approved write. Record hass.config.time_zone "
    "and the phone IANA zone before writing. Do not write if those zones "
    "disagree on that civil date, and do not treat configuration.timezone "
    "-05:00 as America/New_York. Change one existing clock by a known local "
    "amount that does not cross midnight or a DST gap or overlap. PUT only "
    "{schedule: existing-length HH:MM:SS strings} to "
    "device/management/{id}/configuration. Do not include mode or manual. "
    "Read configuration back: the changed slot must equal localTimeToUtcTime "
    "for that zone and date, and mode, manual, volumeLevel, catDelay, "
    "dndFrom, dndTo, extraDry, and the other clocks must be unchanged. Do not "
    "combine this with an empty schedule list."
)


class ScheduleContractError(ValueError):
    """A schedule or DND value the preparation helpers refuse."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class PreparedConfiguration:
    """App-shaped configuration fragment. Not a permission to PUT."""

    configuration: Mapping[str, Any]
    sendable: bool
    registered_ha_service: bool
    blockers: tuple[str, ...]
    evidence: Mapping[str, Any]


def parse_wire_clock(value: Any) -> tuple[int, int, int]:
    """Accept only a zero-padded ``HH:MM:SS`` string."""
    if not isinstance(value, str) or _CLOCK.fullmatch(value) is None:
        raise ScheduleContractError(
            "invalid_clock",
            "Expected a zero-padded HH:MM:SS string. HH:MM, unpadded hours, "
            "and library day/hour/minute objects are not the observed wire form.",
        )
    hour, minute, second = (int(part) for part in value.split(":"))
    return hour, minute, second


def string_time_to_seconds(value: str) -> int:
    """App function #12936, restricted to an already valid clock."""
    hour, minute, second = parse_wire_clock(value)
    return hour * 3600 + minute * 60 + second


def local_time_to_utc_time(clock: str, zone: ZoneInfo, on_date: date) -> str:
    """Mirror function #12931 for one unambiguous civil time."""
    hour, minute, second = parse_wire_clock(clock)
    zone = _require_zone(zone)
    on_date = _require_date(on_date)
    matches = _matching_instants(on_date, hour, minute, second, zone)
    label = f"{hour:02d}:{minute:02d}:{second:02d}"
    if not matches:
        raise ScheduleContractError(
            "nonexistent_local_time",
            f"{label} does not exist in {zone.key} on {on_date.isoformat()}; "
            "not folded forward",
        )
    if len(matches) != 1:
        raise ScheduleContractError(
            "ambiguous_local_time",
            f"{label} occurs twice in {zone.key} on {on_date.isoformat()}; "
            "not folded",
        )
    return matches[0].strftime("%H:%M:%S")


def utc_time_to_local_time(clock: str, zone: ZoneInfo, on_date: date) -> str:
    """Mirror function #12930. The clock is the local wall time only."""
    return utc_time_to_local_detail(clock, zone, on_date)["local_clock"]


def utc_time_to_local_detail(clock: str, zone: ZoneInfo, on_date: date) -> dict[str, Any]:
    """Local display detail, including a date roll and an overlap flag."""
    hour, minute, second = parse_wire_clock(clock)
    zone = _require_zone(zone)
    on_date = _require_date(on_date)
    utc = datetime(on_date.year, on_date.month, on_date.day, hour, minute, second, tzinfo=timezone.utc)
    local = utc.astimezone(zone)
    local_clock = f"{local.hour:02d}:{local.minute:02d}:{local.second:02d}"
    ambiguous = len(_matching_instants(
        local.date(), local.hour, local.minute, local.second, zone
    )) > 1
    return {
        "wire": f"{hour:02d}:{minute:02d}:{second:02d}",
        "local_clock": local_clock,
        "local_date": local.date().isoformat(),
        "ambiguous_local_clock": ambiguous,
    }


def display_schedule(
    wire_times: list[str],
    *,
    zone: ZoneInfo,
    on_date: date,
    reported_offset: str | None = None,
) -> dict[str, Any]:
    """Read-only schedule view. Does not mutate or reorder the wire list."""
    zone = _require_zone(zone)
    on_date = _require_date(on_date)
    wire = list(wire_times)
    details = [utc_time_to_local_detail(item, zone, on_date) for item in wire]
    local_clocks = [item["local_clock"] for item in details]
    return {
        "wire_times": wire,
        "local_clocks": local_clocks,
        "sorted_local_clocks": sorted(local_clocks, key=string_time_to_seconds),
        "entries": details,
        "basis": "app_display_utc_to_local",
        "device_storage_verified": False,
        "zone": zone.key,
        "reference_date": on_date.isoformat(),
        "reference_date_role": "utc_calendar_date_for_moment_utc_hours",
        "reported_offset": reported_offset,
        "reported_offset_applied": False,
        "reported_offset_disagrees_with_zone": _offset_disagrees(
            zone, on_date, reported_offset
        ),
    }


def display_dnd(
    dnd_from: str | None,
    dnd_to: str | None,
    *,
    zone: ZoneInfo,
    on_date: date,
    reported_offset: str | None = None,
    cat_delay: int | None = None,
) -> dict[str, Any]:
    """Read-only DND view. One window, never two independent time entities."""
    if dnd_from == "" or dnd_to == "" or (dnd_from not in ("", None) and dnd_from == dnd_to):
        return {
            "status": "display_cleared",
            "disable_encoding_verified": False,
            "window": None,
            "cat_delay": cat_delay,
            "app_ui_default_hours_if_enabled": APP_UI_DEFAULT_DND_HOURS,
            "app_ui_default_applied": False,
            "reported_offset_applied": False,
        }
    if not isinstance(dnd_from, str) or not isinstance(dnd_to, str):
        raise ScheduleContractError(
            "invalid_clock",
            "Absent DND fields are not the same as empty-string display clearing.",
        )
    start = utc_time_to_local_detail(dnd_from, zone, on_date)
    end = utc_time_to_local_detail(dnd_to, zone, on_date)
    minutes = _clock_minutes(dnd_to, dnd_from)
    return {
        "status": "display_active",
        "disable_encoding_verified": False,
        "window": {
            "from": start["local_clock"],
            "to": end["local_clock"],
            "duration_minutes": minutes,
        },
        "wire_from": dnd_from,
        "wire_to": dnd_to,
        "cat_delay": cat_delay,
        "app_ui_exceeds_ten_hours": minutes > APP_UI_DND_MAX.total_seconds() / 60,
        "reported_offset": reported_offset,
        "reported_offset_applied": False,
        "reported_offset_disagrees_with_zone": _offset_disagrees(
            zone, on_date, reported_offset
        ),
    }


def prepare_schedule_configuration(
    local_times: list[Any],
    *,
    zone: ZoneInfo,
    on_date: date,
    existing_wire: list[Any],
) -> PreparedConfiguration:
    """Build the schedule fragment the app would PUT. Not sendable here."""
    _reject_library_shape(local_times, existing_wire)
    if len(local_times) != len(existing_wire):
        raise ScheduleContractError(
            "schedule_length_mismatch",
            "Refusing to drop or invent schedule slots. Pass the whole existing list.",
        )
    if not local_times:
        raise ScheduleContractError(
            "schedule_empty_disable_unverified",
            "The app can save selectedSchedule [] because an empty array is "
            "truthy in fixConfigurationSchedules. That would PUT {schedule: []}. "
            "Empty live fields do not prove the device treats that as disable.",
        )
    if len(local_times) > APP_UI_SCHEDULE_ROW_LIMIT:
        raise ScheduleContractError(
            "schedule_exceeds_app_ui_limit",
            "App SCHEDULE_OPTIONS_ROW_LIMIT is 8. A longer list is an unknown server range.",
        )
    for item in existing_wire:
        parse_wire_clock(item)
    utc_times = [local_time_to_utc_time(item, zone, on_date) for item in local_times]
    configuration = {"schedule": utc_times}
    reject_time_cleaning_activation(configuration)
    return PreparedConfiguration(
        configuration=MappingProxyType(configuration),
        sendable=False,
        registered_ha_service=False,
        blockers=_UNVERIFIED_WRITE_BLOCKERS,
        evidence=MappingProxyType({
            "conversion": "app_localTimeToUtcTime",
            "zone": _require_zone(zone).key,
            "reference_date": _require_date(on_date).isoformat(),
            "order": "caller_order_not_display_sort",
            "library_set_schedule": "rejected_dict_shape",
            "http": dict(SCHEDULE_EDIT_HTTP),
            "length_change": "app_replaces_whole_list_not_prepared_here",
        }),
    )


def prepare_schedule_disable() -> PreparedConfiguration:
    """Do not invent an empty-list schedule disable write."""
    raise ScheduleContractError(
        "schedule_empty_disable_unverified",
        "Function #18484 can PUT {schedule: []} after every row is removed. "
        "Function #12962 treats length 0 as no schedule for the mode picker, "
        "which is not the same as a proven device disable encoding.",
    )


def reject_time_cleaning_activation(configuration: Mapping[str, Any]) -> None:
    """List edits must not copy the mode-picker activation merge."""
    if not isinstance(configuration, Mapping):
        raise ScheduleContractError(
            "schedule_edit_must_not_activate_time_cleaning",
            "A schedule edit body is a mapping with schedule only.",
        )
    present = [key for key in ("mode", "manual") if key in configuration]
    if present:
        raise ScheduleContractError(
            "schedule_edit_must_not_activate_time_cleaning",
            "switchToTimeActivationWhenDone merges manual 0 and mode 1. "
            "That activates time cleaning. A list edit must omit "
            + " and ".join(present) + ".",
        )


def schedule_editor_hold() -> dict[str, Any]:
    """Why no Home Assistant schedule editor is registered."""
    return {
        "sendable": False,
        "registered_ha_service": False,
        "native_list_entity": False,
        "http": dict(SCHEDULE_EDIT_HTTP),
        "blockers": _UNVERIFIED_WRITE_BLOCKERS,
        "observation": _SCHEDULE_OBSERVATION,
        "reason": (
            "App edit shape is proven. Device acceptance, sibling preservation, "
            "and the phone-zone basis of the stored clocks are not. Home Assistant "
            "has no native variable-length time-list entity. A text box is not used."
        ),
    }


def prepare_dnd_configuration(
    *,
    local_from: str,
    local_to: str,
    cat_delay: int | None,
    zone: ZoneInfo,
    on_date: date,
) -> PreparedConfiguration:
    """Build one DND configuration object with the existing catDelay copied."""
    if cat_delay is None:
        raise ScheduleContractError(
            "dnd_requires_cat_delay",
            "The app save object includes dndFrom, dndTo and catDelay together. "
            "Delay choices belong to settings controls; this helper will not omit "
            "or invent catDelay.",
        )
    if type(cat_delay) is not int:
        raise ScheduleContractError(
            "dnd_cat_delay_not_integer",
            "catDelay must be the existing integer. Ranges are not defined here.",
        )
    if local_from == local_to:
        raise ScheduleContractError(
            "dnd_same_endpoint",
            "The app picker rejects equal DND endpoints (sameTimeError).",
        )
    utc_from = local_time_to_utc_time(local_from, zone, on_date)
    utc_to = local_time_to_utc_time(local_to, zone, on_date)
    if utc_from == utc_to:
        raise ScheduleContractError(
            "dnd_same_endpoint",
            "Converted DND endpoints are equal, so this is not a window.",
        )
    duration = _instant_duration(local_from, local_to, zone, on_date)
    if duration > APP_UI_DND_MAX:
        raise ScheduleContractError(
            "dnd_app_ui_over_ten_hours",
            "The app UI rejects a range higher than ten hours; that check is "
            "not a server limit, and the server range is unknown, so this helper "
            "does not prepare the payload.",
        )
    configuration = {"dndFrom": utc_from, "dndTo": utc_to, "catDelay": cat_delay}
    return PreparedConfiguration(
        configuration=MappingProxyType(configuration),
        sendable=False,
        registered_ha_service=False,
        blockers=_UNVERIFIED_WRITE_BLOCKERS,
        evidence=MappingProxyType({
            "conversion": "app_localTimeToUtcTime",
            "atomic_keys": ["dndFrom", "dndTo", "catDelay"],
            "ten_hour_check": "app_ui_only",
            "disable_encoding": "not_this_payload",
        }),
    )


def prepare_dnd_disable(*, cat_delay: int | None = None) -> PreparedConfiguration:
    """Do not invent an empty-string disable write."""
    del cat_delay
    raise ScheduleContractError(
        "dnd_disable_encoding_unverified",
        "Function #18377 puts empty dndFrom/dndTo when isDndOn is false, and "
        "function #12924 clears empty or equal endpoints for display. Empty "
        "live fields do not prove the device accepts that disable encoding.",
    )


def app_configuration_params(
    manufacturer_id: str, configuration: Mapping[str, Any]
) -> dict[str, Any]:
    """Wrap a prepared fragment the way configurationParams is shaped.

    Unrelated configuration keys are not copied. This is still not a request.
    """
    if not isinstance(manufacturer_id, str) or not manufacturer_id:
        raise ScheduleContractError(
            "invalid_clock", "manufacturerId must be the selected device id."
        )
    allowed = {"schedule", "dndFrom", "dndTo", "catDelay"}
    extra = set(configuration) - allowed
    if extra:
        raise ScheduleContractError(
            "invalid_clock",
            "Refusing to copy unrelated configuration fields: "
            + ", ".join(sorted(extra)),
        )
    if "schedule" in configuration and set(configuration) != {"schedule"}:
        raise ScheduleContractError(
            "invalid_clock",
            "A schedule fragment cannot share an object with DND fields.",
        )
    if "dndFrom" in configuration and set(configuration) != {"dndFrom", "dndTo", "catDelay"}:
        raise ScheduleContractError(
            "invalid_clock",
            "DND must travel with dndFrom, dndTo and catDelay, and nothing else.",
        )
    return {
        "manufacturerId": manufacturer_id,
        "configuration": dict(configuration),
    }


def _require_zone(zone: Any) -> ZoneInfo:
    if not isinstance(zone, ZoneInfo) or not zone.key:
        raise ScheduleContractError(
            "offset_is_not_a_zone",
            "Pass the explicit Home Assistant IANA zone. configuration.timezone "
            "and a fixed offset are not the app conversion input.",
        )
    return zone


def _require_date(on_date: Any) -> date:
    if isinstance(on_date, datetime) or not isinstance(on_date, date):
        raise ScheduleContractError(
            "reference_date_required",
            "Pass the calendar date used as moment's reference day. Do not "
            "default to now or to the device offset.",
        )
    return on_date


def _matching_instants(
    on_date: date, hour: int, minute: int, second: int, zone: ZoneInfo
) -> list[datetime]:
    found: list[datetime] = []
    seen: set[str] = set()
    for fold in (0, 1):
        local = datetime(
            on_date.year, on_date.month, on_date.day,
            hour, minute, second, tzinfo=zone, fold=fold,
        )
        utc = local.astimezone(timezone.utc)
        back = utc.astimezone(zone)
        if back.date() != on_date or (back.hour, back.minute, back.second) != (hour, minute, second):
            continue
        key = utc.strftime("%Y-%m-%dT%H:%M:%S")
        if key not in seen:
            seen.add(key)
            found.append(utc)
    return found


def _offset_disagrees(zone: ZoneInfo, on_date: date, reported_offset: str | None) -> bool:
    if reported_offset is None:
        return False
    parsed = _parse_offset(reported_offset)
    if parsed is None:
        return False
    noon = datetime(on_date.year, on_date.month, on_date.day, 12, 0, tzinfo=zone)
    return noon.utcoffset() != parsed


def _parse_offset(value: str) -> timedelta | None:
    match = _OFFSET.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        return None
    sign = 1 if match.group(1) == "+" else -1
    hours = int(match.group(2))
    minutes = int(match.group(3))
    if hours > 14 or minutes > 59:
        return None
    return timedelta(hours=sign * hours, minutes=sign * minutes)


def _clock_minutes(end: str, start: str) -> int:
    diff = string_time_to_seconds(end) - string_time_to_seconds(start)
    if diff < 0:
        diff += 86400
    if diff % 60:
        raise ScheduleContractError(
            "invalid_clock", "DND duration is not a whole number of minutes."
        )
    return diff // 60


def _instant_duration(local_from: str, local_to: str, zone: ZoneInfo, on_date: date) -> timedelta:
    start = _matching_instants(on_date, *parse_wire_clock(local_from), zone)[0]
    end = _matching_instants(on_date, *parse_wire_clock(local_to), zone)[0]
    if end <= start:
        end += timedelta(days=1)
    return end - start


def _reject_library_shape(*groups: list[Any]) -> None:
    for group in groups:
        if not isinstance(group, list) or any(isinstance(item, dict) for item in group):
            raise ScheduleContractError(
                "library_schedule_shape",
                "Library set_schedule dumps day/hour/minute/enabled objects. "
                "The observed unit and the app send HH:MM:SS strings. Do not use set_schedule.",
            )
