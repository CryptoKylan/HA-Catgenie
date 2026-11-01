"""Native schedule-list action registered by the shared service lifecycle.

The official app's ordinary list edit PUTs exactly ``{schedule: [HH:mm:ss]}``.
The time-activation picker is a different path and also sends ``manual: 0``
and ``mode: 1``. This action never sends those keys.

Each local clock is converted on one explicit IANA reference date, the way
``localTimeToUtcTime`` uses the phone's current date. An earlier clock is not
moved to the next day. Stored UTC clocks are not a promise that firmware
will keep the same wall time after DST; this module does not resave.

Home Assistant 2026.10.4 ``TimeSelector`` has no ``multiple`` flag. The
service form uses ``ObjectSelector`` rows with a ``time`` field. That is a
native action form, not a device-page calendar and not a JSON text box.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import date, datetime
import re
import threading
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from catgenie.models import Device, ScheduleEntry
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .configuration_lock import configuration_lock
from .schedule import (
    APP_UI_SCHEDULE_ROW_LIMIT,
    ScheduleContractError,
    local_time_to_utc_time,
)

SERVICE_SET_SCHEDULE = "set_schedule"
MANUFACTURER = "PetNovations"
APP_UI_MIN_SPACING_MINUTES = 120
_SPACING_SECONDS = APP_UI_MIN_SPACING_MINUTES * 60
_CLOCK = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9]):([0-5][0-9])$")
_DATE = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})$")
_DEVICE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_CALL_KEYS = frozenset({"device_id", "times", "zone", "reference_date"})
_ROW_KEYS = frozenset({"time"})
_IANA_ZONES: frozenset[str] | None = None
_IANA_LOCK = threading.Lock()
_LOAD_FUTURE: Any = None
_ZONE_MISSES: set[str] = set()

# Reference schema for the schedule action in services.yaml.
SERVICES_YAML_FRAGMENT = """\
set_schedule:
  name: Set cleaning schedule
  description: >
    Replace the cleaning schedule from a native action form.
    This is not a device-page calendar and not a JSON text box.
    Each row is one local wall clock. The action converts every
    clock on the reference date in the required IANA zone and
    PUTs only {schedule: [UTC HH:mm:ss]}. It does not send mode,
    manual, Do Not Disturb, cat delay, volume, or auto-lock.
    An empty list is refused. Stored UTC clocks do not guarantee
    the same wall time after a DST change; nothing here resaves.
  fields:
    device_id:
      name: Device
      description: One CatGenie device registry entry.
      required: true
      selector:
        device:
          integration: catgenie
          manufacturer: PetNovations
          multiple: false
      example: ""
    times:
      name: Local clocks
      description: >
        One to eight rows. Each row is an object with a time
        field, because TimeSelector has no multiple option.
        The value must be zero-padded HH:mm:ss, not HH:mm and
        not a day/hour/minute object. Clocks must be unique and
        at least 120 minutes apart in both directions, including
        across midnight. Seconds are required; they are not invented.
      required: true
      selector:
        object:
          multiple: true
          label_field: time
          fields:
            time:
              label: Local time
              required: true
              selector:
                time: {}
      example: '[{"time": "07:30:00"}, {"time": "19:30:00"}]'
    zone:
      name: IANA time zone
      description: >
        Explicit IANA zone used for conversion, such as
        America/New_York. Not configuration.timezone, not a
        fixed offset, and not the Home Assistant or device zone.
      required: true
      selector:
        text: {}
      example: America/New_York
    reference_date:
      name: Reference date
      description: >
        Calendar date in that IANA zone, YYYY-MM-DD. Defaults to
        today in the zone. Every clock uses this date. An earlier
        clock is not treated as the next day.
      required: false
      selector:
        date: {}
      example: "2026-10-31"
"""

# Reference registration contract for an injected, read-only target resolver.
REGISTRATION_FRAGMENT = """\
# resolve_target is async and must not call the vendor.
#     async def resolve_target(device_id: str) -> tuple[coordinator, device_entry]
# device_entry.id == device_id
# device_entry.manufacturer == "PetNovations"
# device_entry.identifiers has exactly one ("catgenie", manufacturer_id)
# coordinator.last_update_success is True when the cache is available
# coordinator.data maps manufacturer_id -> Device
# coordinator.client.get_devices() -> list[Device]
# coordinator.client.update_configuration(manufacturer_id, **body)
from .schedule_actions import register_schedule_service

def register_schedule_action(hass, resolve_target) -> None:
    register_schedule_service(hass, resolve_target)
"""

ResolveTarget = Callable[[str], Awaitable[tuple[Any, Any]]]


class ScheduleActionRefused(HomeAssistantError):
    """Local guard. The message is a code, never a serial or vendor body."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"CatGenie schedule was not changed ({code}).")


class ScheduleActionError(HomeAssistantError):
    """Vendor or resolver failure. Only the exception class name is kept."""

    def __init__(self, phase: str, exc: BaseException) -> None:
        self.code = phase
        self.cause_type = type(exc).__name__
        if phase == "write":
            message = f"CatGenie schedule write failed ({self.cause_type}); outcome unconfirmed, not retried or rolled back."
        elif phase == "refresh":
            message = f"CatGenie schedule refresh failed ({self.cause_type})."
        else:
            message = (
                f"CatGenie schedule {phase} failed ({self.cause_type}); "
                "schedule was not changed."
            )
        super().__init__(message)


class _SetScheduleSchema:
    """Framework schema passed to ``hass.services.async_register``.

    Built from ``homeassistant.helpers.config_validation`` (``probatio`` or
    ``vol``). Structural failures raise that backend's ``Invalid``, which is
    what the service call path catches. Clock spacing, IANA rules, and DST
    gaps are checked again in the handler before I/O and stay
    ``ScheduleActionRefused``.
    """

    def __init__(self) -> None:
        from .services import framework_validation_backend

        backend = framework_validation_backend()
        invalid = backend.Invalid

        def device_id(value: Any) -> str:
            if type(value) is not str or _DEVICE_ID.fullmatch(value) is None:
                raise invalid("invalid_device_id")
            return value

        def times(value: Any) -> list[dict[str, str]]:
            if type(value) is not list:
                raise invalid("invalid_times")
            rows: list[dict[str, str]] = []
            for item in value:
                if type(item) is not dict or set(item) != _ROW_KEYS:
                    raise invalid("invalid_times")
                clock = item["time"]
                if type(clock) is not str:
                    raise invalid("invalid_times")
                rows.append({"time": clock})
            return rows

        def zone(value: Any) -> str:
            if type(value) is not str:
                raise invalid("invalid_zone")
            return value

        self._schema = backend.Schema(
            {
                backend.Required("device_id"): device_id,
                backend.Required("times"): times,
                backend.Required("zone"): zone,
                backend.Optional("reference_date"): lambda value: value,
            },
            extra=backend.PREVENT_EXTRA,
        )
        self.invalid = invalid

    def __call__(self, data: Any) -> dict[str, Any]:
        parsed = self._schema(data)
        if type(parsed) is not dict:
            raise ScheduleActionRefused("invalid_service_data")
        return parsed


SET_SCHEDULE_SCHEMA = _SetScheduleSchema()


def register_schedule_service(hass: Any, resolve_target: ResolveTarget) -> None:
    """Register the schedule service. Caller supplies resolve_target.

    ``async_register`` matches Home Assistant 2026.10.4 ServiceRegistry:
    domain, service, service_func, schema. Supports-response is omitted so
    the registry default NONE applies. This function does not attach itself
    to a config entry and does not remove a service.
    """
    if not callable(resolve_target):
        raise TypeError("resolve_target must be callable")

    async def _handle(call: Any) -> None:
        await async_handle_set_schedule(call, resolve_target)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SCHEDULE,
        _handle,
        SET_SCHEDULE_SCHEMA,
    )


async def async_handle_set_schedule(call: Any, resolve_target: ResolveTarget) -> None:
    """Validate, read one fresh device list, PUT schedule clocks only."""
    from .action_permissions import async_check_device_control

    raw_data = getattr(call, "data", None)
    device_id = raw_data.get("device_id") if isinstance(raw_data, Mapping) else None
    await async_check_device_control(call, device_id)
    await async_iana_zones(getattr(call, "hass", None))
    retained_zone = await _warm_schedule_zone(getattr(call, "data", None))
    prepared = _prepare(getattr(call, "data", None))
    # The local above is the strong reference during _prepare, including
    # ScheduleActionRefused. Drop it only after that call returns.
    if retained_zone is not None:
        retained_zone = None
    try:
        resolved = resolve_target(prepared["device_id"])
        if not hasattr(resolved, "__await__"):
            raise ScheduleActionRefused("resolve_target_not_async")
        coordinator, entry = await resolved
    except ScheduleActionRefused:
        raise
    except Exception as err:
        raise ScheduleActionError("resolve", err) from None
    manufacturer_id = _manufacturer_id(prepared["device_id"], entry)
    async with configuration_lock(coordinator, manufacturer_id):
        await _apply_schedule_locked(coordinator, manufacturer_id, prepared["utc_clocks"])


async def _apply_schedule_locked(coordinator: Any, manufacturer_id: str, clocks: list[str]) -> None:
    """Hold the same device lock as entity and DND configuration writers."""
    _require_cache(coordinator, manufacturer_id)
    fresh = await _fresh_device(coordinator, manufacturer_id)
    _require_safe_current_schedule(fresh)
    await _put_schedule(coordinator, manufacturer_id, clocks)


def _prepare(data: Any) -> dict[str, Any]:
    """Strict local validation. No registry, cache, or vendor call."""
    parsed = SET_SCHEDULE_SCHEMA(data)
    clocks = [_parse_clock(item["time"]) for item in parsed["times"]]
    if not clocks:
        raise ScheduleActionRefused("empty_schedule")
    if len(clocks) > APP_UI_SCHEDULE_ROW_LIMIT:
        raise ScheduleActionRefused("too_many_clocks")
    if len(set(clocks)) != len(clocks):
        raise ScheduleActionRefused("duplicate_clock")
    _require_spacing(clocks)
    zone = _require_zone(parsed["zone"])
    on_date = _reference_date(parsed.get("reference_date"), zone)
    utc_clocks = [_convert(clock, zone, on_date) for clock in clocks]
    return {
        "device_id": parsed["device_id"],
        "utc_clocks": utc_clocks,
        "zone": zone.key,
        "reference_date": on_date.isoformat(),
    }


def _parse_clock(value: Any) -> str:
    if type(value) is not str or not value.isascii() or _CLOCK.fullmatch(value) is None:
        raise ScheduleActionRefused("invalid_clock")
    return value


def _require_spacing(clocks: list[str]) -> None:
    """App #18449: both directions of #12935 must be at least 120 minutes."""
    for index, left in enumerate(clocks):
        for right in clocks[index + 1 :]:
            if (
                _forward_seconds(left, right) < _SPACING_SECONDS
                or _forward_seconds(right, left) < _SPACING_SECONDS
            ):
                raise ScheduleActionRefused("spacing")


def _forward_seconds(start: str, end: str) -> int:
    diff = _seconds(end) - _seconds(start)
    if diff < 0:
        diff += 86400
    return diff


def _seconds(clock: str) -> int:
    hour, minute, second = (int(part) for part in clock.split(":"))
    return hour * 3600 + minute * 60 + second


def _load_iana_zones() -> frozenset[str]:
    """Walk tzdata off the event loop and cache the IANA names."""
    global _IANA_ZONES
    cached = _IANA_ZONES
    if cached is not None:
        return cached
    with _IANA_LOCK:
        if _IANA_ZONES is None:
            _IANA_ZONES = frozenset(available_timezones())
        return _IANA_ZONES


def _drop_cancelled_loader() -> None:
    """A cancelled shared Future is not a load in progress."""
    global _LOAD_FUTURE
    future = _LOAD_FUTURE
    cancelled = getattr(future, "cancelled", None)
    if future is not None and callable(cancelled) and cancelled():
        _LOAD_FUTURE = None


def prime_iana_zones(hass: Any | None) -> None:
    """Schedule the tzdata walk on the executor. This function does no file I/O."""
    global _LOAD_FUTURE
    _drop_cancelled_loader()
    if _IANA_ZONES is not None or hass is None or _LOAD_FUTURE is not None:
        return
    schedule = getattr(hass, "async_add_executor_job", None)
    if not callable(schedule):
        return
    scheduled = schedule(_load_iana_zones)
    if scheduled is not None:
        _LOAD_FUTURE = scheduled


async def async_iana_zones(hass: Any | None = None) -> frozenset[str]:
    """Return the IANA set, loading it off the loop when it is not cached."""
    global _LOAD_FUTURE
    if _IANA_ZONES is not None:
        return _IANA_ZONES
    _drop_cancelled_loader()
    prime_iana_zones(hass)
    future = _LOAD_FUTURE
    if future is not None:
        try:
            # HA returns one shared Future. Awaiting it binds this waiter's
            # cancellation to that Future and to the queued loader. shield
            # keeps the loader running for every other entry.
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            if _LOAD_FUTURE is future and getattr(future, "cancelled", lambda: False)():
                _LOAD_FUTURE = None
            raise
        except Exception:
            if _LOAD_FUTURE is future:
                _LOAD_FUTURE = None
            raise
    return await asyncio.get_running_loop().run_in_executor(None, _load_iana_zones)


def _schedule_zone_candidate(data: Any) -> str | None:
    """Name ``_require_zone`` would pass to ZoneInfo. No filesystem access."""
    if type(data) is not dict:
        return None
    value = data.get("zone")
    if type(value) is not str or not value.isascii():
        return None
    zones = _IANA_ZONES
    if zones is None or value not in zones:
        return None
    return value


def _construct_zone(value: str) -> ZoneInfo | None:
    """Build one ZoneInfo off the loop. None means the name cannot be built."""
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None


async def _warm_schedule_zone(data: Any) -> ZoneInfo | None:
    """Return the off-loop ZoneInfo so the handler can retain it."""
    value = _schedule_zone_candidate(data)
    if value is None or value in _ZONE_MISSES:
        return None
    zone = await asyncio.get_running_loop().run_in_executor(None, _construct_zone, value)
    if zone is None:
        _ZONE_MISSES.add(value)
        return None
    _ZONE_MISSES.discard(value)
    return zone


def _require_zone(value: Any) -> ZoneInfo:
    zones = _IANA_ZONES
    if zones is None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            zones = _load_iana_zones()
        else:
            raise RuntimeError("IANA zone list was not loaded off the event loop")
    if type(value) is not str or not value.isascii() or value not in zones:
        raise ScheduleActionRefused("invalid_zone")
    if value in _ZONE_MISSES:
        raise ScheduleActionRefused("invalid_zone")
    zone = ZoneInfo(value)
    if zone.key != value:
        raise ScheduleActionRefused("invalid_zone")
    return zone


def _reference_date(value: Any, zone: ZoneInfo) -> date:
    if value is None:
        return datetime.now(zone).date()
    if isinstance(value, datetime) or not (
        isinstance(value, date) or type(value) is str
    ):
        raise ScheduleActionRefused("invalid_reference_date")
    if isinstance(value, date):
        return value
    if _DATE.fullmatch(value) is None:
        raise ScheduleActionRefused("invalid_reference_date")
    year, month, day = (int(part) for part in value.split("-"))
    try:
        parsed = date(year, month, day)
    except ValueError:
        raise ScheduleActionRefused("invalid_reference_date") from None
    if parsed.isoformat() != value:
        raise ScheduleActionRefused("invalid_reference_date")
    return parsed


def _convert(clock: str, zone: ZoneInfo, on_date: date) -> str:
    try:
        return local_time_to_utc_time(clock, zone, on_date)
    except ScheduleContractError as err:
        code = err.code
        if code not in {"nonexistent_local_time", "ambiguous_local_time", "invalid_clock"}:
            code = "invalid_clock"
        raise ScheduleActionRefused(code) from None


def _manufacturer_id(device_id: str, entry: Any) -> str:
    if getattr(entry, "id", None) != device_id:
        raise ScheduleActionRefused("unresolved")
    if getattr(entry, "manufacturer", None) != MANUFACTURER:
        raise ScheduleActionRefused("unresolved")
    identifiers = getattr(entry, "identifiers", None)
    if not isinstance(identifiers, (set, frozenset)):
        raise ScheduleActionRefused("unresolved")
    matches = [
        item[1]
        for item in identifiers
        if (
            isinstance(item, tuple)
            and len(item) == 2
            and item[0] == DOMAIN
            and type(item[1]) is str
            and item[1] != ""
        )
    ]
    if len(matches) != 1:
        raise ScheduleActionRefused("unresolved")
    return matches[0]


def _require_cache(coordinator: Any, manufacturer_id: str) -> None:
    if getattr(coordinator, "last_update_success", False) is not True:
        raise ScheduleActionRefused("unavailable")
    data = getattr(coordinator, "data", None)
    if not isinstance(data, dict):
        raise ScheduleActionRefused("unavailable")
    cached = data.get(manufacturer_id)
    if not isinstance(cached, Device):
        raise ScheduleActionRefused("unavailable")
    if not cached.is_online:
        raise ScheduleActionRefused("offline")
    client = getattr(coordinator, "client", None)
    if not callable(getattr(client, "get_devices", None)):
        raise ScheduleActionRefused("unavailable")
    if not callable(getattr(client, "update_configuration", None)):
        raise ScheduleActionRefused("unavailable")


async def _fresh_device(coordinator: Any, manufacturer_id: str) -> Device:
    try:
        devices = await coordinator.client.get_devices()
    except ScheduleActionRefused:
        raise
    except Exception as err:
        raise ScheduleActionError("read", err) from None
    if type(devices) is not list or any(not isinstance(item, Device) for item in devices):
        raise ScheduleActionRefused("fresh_shape")
    matches = [item for item in devices if item.manufacturer_id == manufacturer_id]
    if not matches:
        raise ScheduleActionRefused("fresh_missing")
    if len(matches) != 1:
        raise ScheduleActionRefused("fresh_ambiguous")
    fresh = matches[0]
    if fresh.is_online is not True:
        raise ScheduleActionRefused("offline")
    if "configuration" not in fresh.model_fields_set:
        raise ScheduleActionRefused("incomplete")
    return fresh


def _require_safe_current_schedule(fresh: Device) -> None:
    configuration = fresh.configuration
    if "schedule" not in configuration.model_fields_set:
        raise ScheduleActionRefused("schedule_not_explicit")
    schedule = configuration.schedule
    if type(schedule) is not list:
        raise ScheduleActionRefused("unsafe_schedule")
    for entry in schedule:
        if not isinstance(entry, ScheduleEntry):
            raise ScheduleActionRefused("unsafe_schedule")
        extra = entry.model_extra or {}
        if set(extra) != {"time"}:
            raise ScheduleActionRefused("unsafe_schedule")
        clock = extra["time"]
        if type(clock) is not str or not clock.isascii() or _CLOCK.fullmatch(clock) is None:
            raise ScheduleActionRefused("unsafe_schedule")
        # Pydantic also records the extra "time" key in model_fields_set.
        # The client normalizer sets hour and minute from the string and
        # does not set day or enabled. A library object does.
        declared = set(entry.model_fields_set) & set(ScheduleEntry.model_fields)
        if declared != {"hour", "minute"}:
            raise ScheduleActionRefused("unsafe_schedule")
        hour, minute, _second = (int(part) for part in clock.split(":"))
        if entry.hour != hour or entry.minute != minute:
            raise ScheduleActionRefused("unsafe_schedule")


async def _put_schedule(
    coordinator: Any, manufacturer_id: str, utc_clocks: list[str]
) -> None:
    payload = {"schedule": list(utc_clocks)}
    if set(payload) != {"schedule"}:
        raise ScheduleActionRefused("invalid_service_data")
    try:
        await coordinator.client.update_configuration(manufacturer_id, **payload)
    except Exception as err:
        raise ScheduleActionError("write", err) from None
    try:
        await coordinator.async_request_refresh()
    except Exception as err:
        raise ScheduleActionError("refresh", err) from None
