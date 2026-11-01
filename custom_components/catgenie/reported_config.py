"""Reported cartridge, timezone, and Do Not Disturb diagnostics.

Values come from the device already on the coordinator. This module does not
poll, write configuration, or convert schedule clocks. Local schedule display
stays on hold: ``display_schedule`` needs an explicit IANA zone, and the
reported offset is not that zone.
"""
from __future__ import annotations

from typing import Any

from catgenie import Device

from .schedule import ScheduleContractError, parse_wire_clock

SCHEDULE_DISPLAY_HOLD = {
    "status": "hold",
    "reason": (
        "Local schedule display is hold: wire UTC basis is unverified, "
        "and a reported UTC offset is not a trusted conversion zone."
    ),
}

_TAG_LABELS = {0: "missing", 1: "regular", 3: "maintenance"}
_MISSING = object()


def _explicit(model: Any, key: str) -> Any:
    """Return a field only when the payload set it.

    Declared defaults such as timezone ``+00:00`` and extra-field absence are
    both missing. A present zero or empty string is not missing.
    """
    if key not in getattr(model, "model_fields_set", ()):
        return _MISSING
    extra_map = getattr(model, "model_extra", None) or {}
    if key in extra_map:
        return extra_map[key]
    return getattr(model, key)


def _configuration(device: Device) -> Any | None:
    if "configuration" not in device.model_fields_set:
        return None
    return device.configuration


def measurement_snapshot(data: Any) -> dict[str, Any]:
    """Keep only allowlisted scalar measurement provenance, never identity/auth.

    Private on the adapter Device; excluded by Pydantic serialization. Container
    values and overlong strings become invalid (None), not retained payloads.
    """
    result: dict[str, Any] = {}

    def keep(source: Any, wire: str, key: str) -> None:
        if isinstance(source, dict) and wire in source:
            value = source[wire]
            result[key] = value if (value is None or type(value) in (bool, int, float)
                                    or (type(value) is str and len(value) <= 64)) else None

    if not isinstance(data, dict):
        return result
    keep(data, 'remainingSaniSolution', 'remaining_sani_solution')
    config = data.get('configuration')
    if isinstance(config, dict):
        for wire, key in (('catDelay', 'cat_delay'), ('autoLock', 'auto_lock'),
                          ('catSense', 'cat_sense'), ('volumeLevel', 'volume_level'),
                          ('mode', 'mode'), ('manual', 'manual')):
            keep(config, wire, key)
        keep(config.get('activation'), 'count', 'total_cycles')
        schedule = config.get('schedule')
        if 'schedule' in config:
            # A scalar validity bit only: never duplicate the unbounded list.
            result['schedule_valid'] = isinstance(schedule, list) and all(
                isinstance(e, dict) and (type(e.get('enabled')) is bool or
                    ('enabled' not in e and _wire_clock(e.get('time')) is not None))
                for e in schedule)
    return result


def reported_measurement(device: Device, key: str) -> Any:
    """Read one allowlisted pre-coercion scalar, with explicit stock-model fallback."""
    raw = getattr(device, '_reported_measurements', None)
    if raw is not None:
        return raw.get(key, _MISSING)
    # Compatibility with explicit stock-model callers. Only the integration's
    # adapter can prove pre-coercion types; actual polls always use that adapter.
    if key == 'remaining_sani_solution':
        return _explicit(device, key)
    config = _configuration(device)
    if config is None:
        return _MISSING
    if key == 'total_cycles':
        activation = _explicit(config, 'activation')
        return _explicit(activation, 'count')
    return _explicit(config, key)


def reported_integer(device: Device, key: str) -> int | None:
    """Explicit real integer only; no coercion, defaults, or invented totals."""
    value = reported_measurement(device, key)
    return value if type(value) is int and value >= 0 else None


def reported_setting(device: Device, key: str) -> int | None:
    """Use the verified app choices, without rounding reported values."""
    from .configuration import AUTO_LOCK_SECONDS, CAT_DELAY_SECONDS, VOLUME_MIN, VOLUME_MAX
    value = reported_integer(device, key)
    if key == 'cat_delay' and value not in CAT_DELAY_SECONDS:
        return None
    if key == 'auto_lock' and value not in AUTO_LOCK_SECONDS:
        return None
    if key == 'volume_level' and (value is None or not VOLUME_MIN <= value <= VOLUME_MAX):
        return None
    return value


def reported_activation_mode(device: Device) -> str | None:
    """Shared reader semantics: both wire mode and manual must be known ints."""
    from catgenie import CleaningMode
    config = _configuration(device)
    if config is None or _explicit(config, 'mode') not in (CleaningMode.AUTOMATIC, CleaningMode.MANUAL):
        return None
    mode = reported_measurement(device, 'mode')
    manual = reported_measurement(device, 'manual')
    # Stock models retain IntEnums; raw snapshots retain actual JSON ints.
    if type(mode) not in (int, CleaningMode) or mode not in (0, 1):
        return None
    if type(manual) is not int or manual not in (0, 1):
        return None
    return 'manual' if manual else ('cat' if mode == 0 else 'time')


def reported_schedule_count(device: Device) -> int | None:
    config = _configuration(device)
    if config is None or 'schedule' not in config.model_fields_set:
        return None
    raw = getattr(device, '_reported_measurements', None)
    if raw is not None and raw.get('schedule_valid') is not True:
        return None
    if any(('enabled' not in e.model_fields_set and _wire_clock(_explicit(e, 'time')) is None)
           or type(e.enabled) is not bool for e in config.schedule):
        return None
    return sum(e.enabled for e in config.schedule)


def cartridge_type_value(device: Device) -> str | None:
    """Map an explicit integer tagType. Absent and mistyped values stay unknown."""
    tag = _explicit(device, "tagType")
    if tag is _MISSING or type(tag) is not int:
        return None
    return _TAG_LABELS.get(tag, "unknown")


def cartridge_type_attributes(device: Device) -> dict[str, Any]:
    """Keep the raw code when the app enum does not name it."""
    tag = _explicit(device, "tagType")
    attributes: dict[str, Any] = {
        "tag_type_present": tag is not _MISSING,
        "mapping": "app_tag_type_enum",
    }
    if tag is _MISSING:
        return attributes
    if type(tag) is int and tag in _TAG_LABELS:
        attributes["tag_type"] = tag
        return attributes
    attributes["raw_tag_type"] = tag
    return attributes


def reported_timezone_value(device: Device) -> str | None:
    """Return the reported timezone string. Do not replace it with an HA zone."""
    config = _configuration(device)
    if config is None:
        return None
    value = _explicit(config, "timezone")
    if type(value) is not str or value == "" or len(value) > 255:
        return None
    return value


def reported_timezone_attributes(device: Device) -> dict[str, Any]:
    """Label the offset as reported metadata. Do not claim DST or a conversion."""
    attributes: dict[str, Any] = {
        "source": "device_configuration",
        "ha_zone_applied": False,
        "dst_claimed": False,
        "offset_trusted_for_schedule_conversion": False,
    }
    config = _configuration(device)
    if config is None:
        attributes["timezone_present"] = False
        return attributes
    value = _explicit(config, "timezone")
    attributes["timezone_present"] = value is not _MISSING
    if type(value) is str and value:
        attributes["reported_timezone"] = value
    elif value is not _MISSING:
        attributes["raw_timezone"] = value
    dst_from = _explicit(config, "dstFrom")
    dst_to = _explicit(config, "dstTo")
    if dst_from is not _MISSING or dst_to is not _MISSING:
        attributes["dst_semantics"] = "unverified"
        if dst_from is not _MISSING:
            attributes["raw_dst_from"] = dst_from
        if dst_to is not _MISSING:
            attributes["raw_dst_to"] = dst_to
    return attributes


def _wire_clock(value: Any) -> str | None:
    if type(value) is not str:
        return None
    try:
        parse_wire_clock(value)
    except ScheduleContractError:
        return None
    return value


def reported_dnd_value(device: Device) -> str | None:
    """Show DND as reported. Empty or equal strings are not a proven disable."""
    config = _configuration(device)
    if config is None:
        return None
    start = _explicit(config, "dndFrom")
    end = _explicit(config, "dndTo")
    if start is _MISSING or end is _MISSING:
        return None
    if start == "" or end == "" or (type(start) is str and start == end):
        return "not set"
    if _wire_clock(start) is None or _wire_clock(end) is None:
        return None
    return f"{start} to {end}"


def reported_dnd_attributes(device: Device) -> dict[str, Any]:
    """Clock entries are the reported strings. They are not local conversions."""
    attributes: dict[str, Any] = {
        "basis": "reported_configuration_string",
        "clock_basis": "unverified",
        "converted": False,
        "reported_offset_applied": False,
        "disable_encoding_verified": False,
        "ha_zone_applied": False,
    }
    config = _configuration(device)
    if config is None:
        attributes["dnd_present"] = False
        return attributes
    start = _explicit(config, "dndFrom")
    end = _explicit(config, "dndTo")
    if start is _MISSING or end is _MISSING:
        attributes["dnd_present"] = False
        if start is not _MISSING:
            attributes["raw_dnd_from"] = start
        if end is not _MISSING:
            attributes["raw_dnd_to"] = end
        return attributes
    attributes["dnd_present"] = True
    if reported_dnd_value(device) == "not set":
        attributes["reported_from"] = start
        attributes["reported_to"] = end
        return attributes
    if _wire_clock(start) is None or _wire_clock(end) is None:
        attributes["raw_dnd_from"] = start
        attributes["raw_dnd_to"] = end
        return attributes
    attributes["reported_from"] = start
    attributes["reported_to"] = end
    attributes["clock_entries"] = [start, end]
    return attributes
