"""Do Not Disturb action writes shaped like the official app save.

The picker path stores ``startTime.utc().format('HH:mm:ss')`` for the phone's
current zone and the current local date. Both ends of an overnight window use
that same date. This is not a recurring wall-clock guarantee: firmware use of
``timezone`` / ``dstFrom`` / ``dstTo`` is unverified, and nothing here resaves
clocks when the offset changes.

``prepare_dnd_configuration`` stays nonsendable. This module is the separate
write path. It does not register a Home Assistant service by itself.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, time
import math
import re
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .const import DOMAIN
from .configuration_lock import configuration_lock
from .schedule import ScheduleContractError, local_time_to_utc_time

SERVICE_SET_DO_NOT_DISTURB = "set_do_not_disturb"
DND_ACTION_ENTRIES = "catgenie_dnd_action_entries"
_FIELDS = frozenset(
    {"device_id", "enabled", "start_time", "end_time", "timezone", "reference_date"}
)
_CLOCK = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9]):([0-5][0-9])$", re.ASCII)
_CLOCK_HM = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$", re.ASCII)
_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$", re.ASCII)
_OFFSET = re.compile(r"^[+-]\d{2}:\d{2}$", re.ASCII)
_PUT_KEYS = ("dndFrom", "dndTo", "catDelay")
_MANUFACTURER = "PetNovations"
_ZONE_MISSES: set[str] = set()


class DndActionRefused(Exception):
    """Local refusal. ``reason`` is a stable class, not a vendor payload."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class DndIoError(Exception):
    """Vendor I/O failed. Only the exception class name is retained."""

    def __init__(self, stage: str, class_name: str) -> None:
        self.stage = stage
        self.class_name = class_name
        super().__init__(stage)


@dataclass(frozen=True)
class ResolvedTarget:
    """One coordinator and the manufacturer id from its device registry entry."""

    coordinator: Any
    manufacturer_id: str
    cached: Any
    entry_id: str


@dataclass(frozen=True)
class PreparedDndWrite:
    """UTC clocks already checked. ``catDelay`` is filled from the fresh GET."""

    device_id: str
    enabled: bool
    dnd_from: str
    dnd_to: str
    zone_key: str | None
    reference_date: str | None


def _now(zone: ZoneInfo) -> datetime:
    """Clock used only for the default reference date. Tests replace this."""
    return datetime.now(zone)


def _absent(value: Any) -> bool:
    return value is None or value == ""


def _reject_nonfinite(value: Any, reason: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise DndActionRefused(reason)
    if isinstance(value, complex):
        raise DndActionRefused(reason)


def normalize_local_clock(value: Any) -> str:
    """Accept ASCII ``HH:MM:SS`` or ``HH:MM``. Time-selector values are the former."""
    _reject_nonfinite(value, "invalid_time")
    if type(value) is time:
        if value.microsecond:
            raise DndActionRefused("invalid_time")
        return f"{value.hour:02d}:{value.minute:02d}:{value.second:02d}"
    if type(value) is not str or _CLOCK.fullmatch(value) is None and _CLOCK_HM.fullmatch(value) is None:
        raise DndActionRefused("invalid_time")
    if len(value) == 5:
        return value + ":00"
    return value


def require_iana_zone(value: Any) -> ZoneInfo:
    """Explicit IANA name. Offsets and the host zone are not accepted."""
    _reject_nonfinite(value, "invalid_zone")
    if type(value) is not str or not value or _OFFSET.fullmatch(value) is not None:
        raise DndActionRefused("invalid_zone")
    if any(ord(char) > 127 or char.isspace() for char in value):
        raise DndActionRefused("invalid_zone")
    if value in _ZONE_MISSES:
        raise DndActionRefused("invalid_zone")
    try:
        zone = ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        raise DndActionRefused("invalid_zone") from None
    if not zone.key:
        raise DndActionRefused("invalid_zone")
    return zone


def require_reference_date(value: Any) -> date:
    """Calendar date only. A datetime would pick an instant, not a civil day."""
    _reject_nonfinite(value, "invalid_date")
    if type(value) is date:
        return value
    if type(value) is not str or _DATE.fullmatch(value) is None:
        raise DndActionRefused("invalid_date")
    year, month, day = (int(part) for part in value.split("-"))
    try:
        parsed = date(year, month, day)
    except ValueError:
        raise DndActionRefused("invalid_date") from None
    if parsed.isoformat() != value:
        raise DndActionRefused("invalid_date")
    return parsed


def validate_call(data: Mapping[str, Any] | Any, *, now: Any = None) -> PreparedDndWrite:
    """Reject bad fields before registry lookup or vendor I/O."""
    if not isinstance(data, Mapping) or any(type(key) is not str for key in data):
        raise DndActionRefused("injected")
    unknown = set(data) - _FIELDS
    if unknown:
        raise DndActionRefused("injected")
    for value in data.values():
        _reject_nonfinite(value, "injected")
    device_id = data.get("device_id")
    if type(device_id) is not str or not device_id or device_id.strip() != device_id:
        raise DndActionRefused("missing")
    enabled = data.get("enabled")
    if type(enabled) is not bool:
        raise DndActionRefused("invalid_enabled")
    if not enabled:
        for key in ("start_time", "end_time", "timezone", "reference_date"):
            if key in data and not _absent(data.get(key)):
                if key == "timezone":
                    require_iana_zone(data[key])
                elif key == "reference_date":
                    require_reference_date(data[key])
                else:
                    normalize_local_clock(data[key])
        return PreparedDndWrite(device_id, False, "", "", None, None)
    start = normalize_local_clock(data.get("start_time"))
    end = normalize_local_clock(data.get("end_time"))
    if start == end:
        raise DndActionRefused("same_endpoint")
    zone = require_iana_zone(data.get("timezone"))
    if _absent(data.get("reference_date")):
        clock = now or _now
        current = clock(zone)
        if not isinstance(current, datetime) or current.tzinfo is None:
            raise DndActionRefused("invalid_date")
        on_date = current.date()
    else:
        on_date = require_reference_date(data.get("reference_date"))
    try:
        utc_from = local_time_to_utc_time(start, zone, on_date)
        utc_to = local_time_to_utc_time(end, zone, on_date)
    except ScheduleContractError as err:
        code = err.code if err.code in {"nonexistent_local_time", "ambiguous_local_time"} else "invalid_time"
        raise DndActionRefused(code) from None
    if utc_from == utc_to:
        raise DndActionRefused("same_endpoint")
    return PreparedDndWrite(
        device_id, True, utc_from, utc_to, zone.key, on_date.isoformat()
    )


def _linked_entry_ids(device: Any) -> list[str]:
    """2026 uses one ``config_entry_id``. 2025.1.0 uses a ``config_entries`` set.

    Do not read ``config_entries`` when the single id is present. On 2026 that
    property is deprecated and logs for a non-composite device. A legacy shared
    device may also list a foreign entry; callers keep only CatGenie matches.
    """
    single = getattr(device, "config_entry_id", None)
    if type(single) is str and single:
        return [single]
    legacy = getattr(device, "config_entries", None)
    if isinstance(legacy, (set, frozenset)) and legacy:
        ids = [item for item in legacy if type(item) is str and item]
        if len(ids) == len(legacy):
            return ids
    raise DndActionRefused("foreign")


def _matching_entries(hass: Any, device: Any) -> list[Any]:
    matches = []
    for entry_id in _linked_entry_ids(device):
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or getattr(entry, "domain", None) != DOMAIN:
            continue
        matches.append(entry)
    if not matches:
        raise DndActionRefused("foreign")
    if len(matches) != 1:
        raise DndActionRefused("ambiguous")
    return matches


def resolve_target(hass: Any, device_id: str) -> ResolvedTarget:
    """Map one HA device id to one CatGenie coordinator.

    2026.10.4 devices have a single ``config_entry_id``. 2025.1.0 devices have
    ``config_entries`` as a set. Exactly one of those entries must be this
    integration. A foreign entry on a legacy shared device is ignored. Two
    CatGenie entries are refused before any vendor I/O. Composite devices are
    refused. There is no device map in ``hass.data[DOMAIN]`` and no fallback
    to entry data or a raw vendor id.
    """
    from homeassistant.helpers.device_registry import async_get

    registry = async_get(hass)
    device = registry.async_get(device_id)
    if device is None or getattr(device, "disabled_by", None) is not None:
        raise DndActionRefused("missing")
    if getattr(device, "is_composite_device", False):
        raise DndActionRefused("ambiguous")
    entry = _matching_entries(hass, device)[0]
    entry_id = getattr(entry, "entry_id", None)
    if type(entry_id) is not str or not entry_id:
        raise DndActionRefused("foreign")
    identifiers = tuple(getattr(device, "identifiers", ()) or ())
    ours = [
        item
        for item in identifiers
        if isinstance(item, tuple) and len(item) == 2 and item[0] == DOMAIN
    ]
    if len(identifiers) != 1 or len(ours) != 1:
        raise DndActionRefused("ambiguous" if ours else "foreign")
    manufacturer_id = ours[0][1]
    if type(manufacturer_id) is not str or not manufacturer_id:
        raise DndActionRefused("ambiguous")
    if getattr(device, "manufacturer", None) != _MANUFACTURER:
        raise DndActionRefused("foreign")
    coordinator = getattr(entry, "runtime_data", None)
    if getattr(coordinator, "last_update_success", True) is not True:
        raise DndActionRefused("unavailable")
    data = getattr(coordinator, "data", None)
    cached = data.get(manufacturer_id) if isinstance(data, dict) else None
    if cached is None:
        raise DndActionRefused("missing")
    return ResolvedTarget(coordinator, manufacturer_id, cached, entry_id)


def exact_fresh_device(devices: Any, manufacturer_id: str) -> Any:
    """Return the one fresh ``Device`` instance. Do not fall back to the cache."""
    from catgenie import Device

    if type(devices) is not list or any(not isinstance(item, Device) for item in devices):
        raise DndActionRefused("unexpected")
    matches = [item for item in devices if item.manufacturer_id == manufacturer_id]
    if len(matches) != 1:
        raise DndActionRefused("ambiguous" if matches else "missing")
    return matches[0]


def guard_fresh_snapshot(device: Any) -> int:
    """Copy a known catDelay and require a supported current DND pair.

    Supported pairs are both ``''`` or both ASCII ``HH:MM:SS``, the same
    guard the delay helper uses before it echoes DND. The integer is not snapped.
    """
    from .configuration import (
        CAT_DELAY_SECONDS,
        SettingsWriteRefused,
        _unchanged_dnd,
        stored_cat_delay_seconds,
    )

    if device is None or not getattr(device, "is_online", False):
        raise DndActionRefused("offline" if device is not None else "missing")
    configuration = getattr(device, "configuration", None)
    try:
        _unchanged_dnd(configuration)
    except SettingsWriteRefused as err:
        raise DndActionRefused(err.reason if err.reason == "dnd_unknown" else "incomplete") from None
    seconds = stored_cat_delay_seconds(device)
    if seconds not in CAT_DELAY_SECONDS:
        raise DndActionRefused("incomplete" if seconds is None else "not_a_choice")
    return seconds


def dnd_put_payload(prepared: PreparedDndWrite, cat_delay: int) -> dict[str, str | int]:
    """Exact app save object. No mode, schedule, timezone, or DST keys."""
    if type(cat_delay) is not int:
        raise DndActionRefused("not_a_choice")
    payload: dict[str, str | int] = {
        "dndFrom": prepared.dnd_from,
        "dndTo": prepared.dnd_to,
        "catDelay": cat_delay,
    }
    if tuple(payload) != _PUT_KEYS:
        raise DndActionRefused("injected")
    return payload


def _timezone_candidate(data: Any) -> str | None:
    """String ``require_iana_zone`` would pass to ZoneInfo. No filesystem access."""
    if not isinstance(data, Mapping):
        return None
    value = data.get("timezone")
    if type(value) is not str or not value or _OFFSET.fullmatch(value) is not None:
        return None
    if any(ord(char) > 127 or char.isspace() for char in value):
        return None
    return value


def _construct_zone(value: str) -> ZoneInfo | None:
    """Build one ZoneInfo off the loop. None means the name cannot be built."""
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None


async def _warm_dnd_zone(data: Any) -> ZoneInfo | None:
    """Return the off-loop ZoneInfo so the handler can retain it."""
    value = _timezone_candidate(data)
    if value is None or value in _ZONE_MISSES:
        return None
    zone = await asyncio.get_running_loop().run_in_executor(None, _construct_zone, value)
    if zone is None:
        # Mutated only on the event loop, after the executor await. Evict a
        # miss before insertion; never evict the just-added miss before the
        # immediately following synchronous validation can see it.
        if len(_ZONE_MISSES) >= 128:
            _ZONE_MISSES.pop()
        _ZONE_MISSES.add(value)
        return None
    _ZONE_MISSES.discard(value)
    return zone


async def async_apply_dnd(hass: Any, data: Mapping[str, Any] | Any, *, now: Any = None) -> dict[str, str | int]:
    """Validate, resolve, GET once, PUT once, refresh only after the PUT returns."""
    retained_zone = await _warm_dnd_zone(data)
    prepared = validate_call(data, now=now)
    # The local above is the strong reference during validate_call, including
    # DndActionRefused. Drop it only after that call returns.
    if retained_zone is not None:
        retained_zone = None
    target = resolve_target(hass, prepared.device_id)
    async with configuration_lock(target.coordinator, target.manufacturer_id):
        return await _apply_dnd_locked(target, prepared)


async def _apply_dnd_locked(target: ResolvedTarget, prepared: PreparedDndWrite) -> dict[str, str | int]:
    """Hold the shared device lock across fresh read, write, and refresh."""
    if not getattr(target.cached, "is_online", False):
        raise DndActionRefused("offline")
    try:
        devices = await target.coordinator.client.get_devices()
    except Exception as err:
        raise DndIoError("read", type(err).__name__) from None
    fresh = exact_fresh_device(devices, target.manufacturer_id)
    cat_delay = guard_fresh_snapshot(fresh)
    payload = dnd_put_payload(prepared, cat_delay)
    try:
        await target.coordinator.client.update_configuration(
            target.manufacturer_id, **payload
        )
    except Exception as err:
        raise DndIoError("write", type(err).__name__) from None
    try:
        await target.coordinator.async_request_refresh()
    except Exception as err:
        raise DndIoError("readback", type(err).__name__) from None
    return payload
