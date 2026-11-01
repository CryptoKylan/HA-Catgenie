"""Read-only CatGenie activity/diary parsing.

The cloud statistics GET returns separate ``visitResponses``,
``flushResponses`` and ``petResponses`` arrays. Chart averages in the
official app are computed locally, and chart days use the device-local
calendar. This module does the same split without inventing per-cat
counts, liquid weight, or a complete-history guarantee.

The pinned client method ``get_pet_statistics()`` accepts no arguments, so
a windowed read cannot use it. ``statistics_request()`` documents the
private ``CatGenieClient._request`` call that can send ``startTime``.
Nothing in this module opens a network connection.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

# Slower than the device coordinator's 15s active / 60s idle polls.
HISTORY_SCAN_INTERVAL = timedelta(minutes=15)
# Explicit choice. The app chart-length slot is not a proven request operand,
# and the no-parameter response window is unverified. Seven local days,
# including today, is the window this integration asks for.
HISTORY_WINDOW_DAYS = 7
STATISTICS_PATH = "device/history/account/pet/statistics"
PRIVATE_STATISTICS_HELPER = "CatGenieClient._request"
UNUSED_PUBLIC_GETTER = "CatGenieClient.get_pet_statistics"

# Local Home Assistant helpers, not integration entities. History must not
# publish these keys or claim to replace their counts.
LOCAL_COUNTER_KEYS = ("completed_cleanings", "recovery_runs")

_EPOCH_MIN = 946684800  # 2000-01-01 UTC
_EPOCH_MAX = 4102444800  # 2100-01-01 UTC
_DIARY_LIMIT = 10


def format_start_time(start: datetime) -> str:
    """UTC ISO-8601 timestamp with millisecond precision and a Z suffix.

    Matches the shape ``moment.utc().toISOString()`` sends as ``startTime``.
    Naive datetimes are rejected so the window is never silently localized.
    """
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError("startTime requires an aware datetime")
    utc = start.astimezone(timezone.utc)
    millis = utc.microsecond // 1000
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def statistics_request(start: datetime) -> dict[str, Any]:
    """Describe the one bounded statistics GET. Does not perform I/O.

    ``get_pet_statistics()`` cannot accept ``startTime``. The no-parameter
    window is unverified, and no app pagination parameter was found, so the
    only query parameter sent is an explicit ``startTime``.
    """
    return {
        "method": "GET",
        "path": STATISTICS_PATH,
        "params": {"startTime": format_start_time(start)},
        "helper": PRIVATE_STATISTICS_HELPER,
        "not_used": UNUSED_PUBLIC_GETTER,
        "reason": (
            "Pinned catgenie get_pet_statistics() accepts no arguments and "
            "cannot send startTime. The unparameterized window is unverified."
        ),
    }


async def fetch_statistics(client: Any, start: datetime) -> Any:
    """Fetch one statistics window through the private request helper.

    Callers must pass a client whose ``_request`` already performs auth.
    This function does not call ``get_pet_statistics()``.
    """
    spec = statistics_request(start)
    return await client._request(spec["method"], spec["path"], params=spec["params"])


def window_bounds(
    now: datetime,
    tz: ZoneInfo,
    days: int = HISTORY_WINDOW_DAYS,
) -> tuple[datetime, datetime]:
    """Return ``[local midnight, now]`` covering ``days`` local dates.

    ``days`` includes today. The start is that local date's midnight in
    ``tz``, not a UTC truncation and not the device coordinator's clock.
    """
    if days < 1:
        raise ValueError("history window must cover at least one local day")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("history window requires an aware clock")
    end = now.astimezone(tz)
    start_day = end.date() - timedelta(days=days - 1)
    start = datetime.combine(start_day, time.min, tzinfo=tz)
    return start, end


def device_filter_from_identity(
    manufacturer_id: str,
    extra: Mapping[str, Any] | None = None,
    *,
    mac_address: str | None = None,
) -> DeviceFilter:
    """Build a device filter from the observed cloud field mapping.

    A 2026-10-31 readonly join, stored as counts only, showed every
    unparameterized visit and flush ``fields.serialNumber`` equaled
    ``manufacturerId``, and every visit ``fields.deviceId`` equaled
    ``macAddress``, not ``manufacturerId``. The raw device had no
    ``serialNumber`` or ``deviceId`` extras. ``bleConnectionId`` also
    equaled visit ``deviceId`` on that unit and is not a second candidate.

    Explicit extras are included only when they do not contradict those
    mapped values. A contradictory extra is ignored, not added as another
    identity.
    """
    extras = extra or {}
    serials: set[str] = set()
    device_ids: set[str] = set()
    mapped_serial = _text(manufacturer_id)
    mapped_device = _text(mac_address)
    extra_serial = _text(extras.get("serialNumber"))
    extra_device = _text(extras.get("deviceId"))
    if mapped_serial:
        serials.add(mapped_serial)
    if extra_serial and (mapped_serial is None or extra_serial == mapped_serial):
        serials.add(extra_serial)
    if mapped_device:
        device_ids.add(mapped_device)
    if extra_device and (mapped_device is None or _canonical_device_id(extra_device) == _canonical_device_id(mapped_device)):
        device_ids.add(extra_device)
    return DeviceFilter(
        device_ids=frozenset(device_ids),
        serial_numbers=frozenset(serials),
    )


@dataclass(frozen=True)
class DeviceFilter:
    """Identifiers that may attribute a history record to one unit."""

    device_ids: frozenset[str]
    serial_numbers: frozenset[str]


@dataclass(frozen=True)
class AccountHistory:
    """Parsed account payload. Device views are derived, not pre-assigned."""

    window_start: datetime
    window_end: datetime
    timezone: str
    timezone_source: str
    request_start_time: str
    visit_key: str
    flush_key: str
    pet_key: str
    pet_profile_count: int | None
    visits: tuple[ParsedEvent, ...]
    flushes: tuple[ParsedEvent, ...]
    skipped: tuple[SkippedRecord, ...]

    def for_device(self, device_filter: DeviceFilter) -> DeviceActivity:
        """Return one device's read-only slice. Does not invent owners."""
        return _activity_for_device(self, device_filter)


@dataclass(frozen=True)
class ParsedEvent:
    """One accepted visit or flush. Identity values stay off sensor state."""

    kind: str
    event_id: str
    when: datetime
    local_date: date
    in_window: bool
    device_id: str | None
    serial_number: str | None
    attribution: str
    duration_seconds: int | None
    aborted: int | None
    outcome: str | None
    pet_id_present: bool
    time_source: str


@dataclass(frozen=True)
class SkippedRecord:
    """A record that was not turned into an event time."""

    kind: str
    reason: str
    attribution: str
    device_id: str | None = None
    serial_number: str | None = None


@dataclass(frozen=True)
class DeviceActivity:
    """Modest read-only slice for one device and one explicit window."""

    coverage: str
    today_basis: str
    visits_today: int | None
    last_visit: datetime | None
    last_visit_duration_seconds: int | None
    aborted_count: int | None
    not_aborted_count: int | None
    aborted_unknown_count: int | None
    aborted_confidence: str
    flush_record_count: int | None
    visit_record_count: int | None
    visits_per_not_aborted_flush: float | None
    visit_day_zeros: tuple[str, ...]
    flush_day_zeros: tuple[str, ...]
    uncovered_dates: tuple[str, ...]
    pet_attribution: str
    pet_profile_count: int | None
    duplicate_dropped: int
    skipped_uncertain_timestamps: int
    unknown_attribution: int
    conflict_attribution: int
    other_device: int
    outside_window: int
    window_start: str
    window_end: str
    timezone: str
    timezone_source: str
    request_start_time: str
    complete_history: bool
    replaces_local_completed_cleanings: bool
    visit_diary: tuple[dict[str, Any], ...]
    flush_diary: tuple[dict[str, Any], ...]

    def sensor_attributes(self) -> dict[str, Any]:
        """Attributes safe to expose. No pet names, ids, weights or images."""
        return {
            "coverage": self.coverage,
            "today_basis": self.today_basis,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "timezone": self.timezone,
            "timezone_source": self.timezone_source,
            "request_start_time": self.request_start_time,
            "complete_history": self.complete_history,
            "replaces_local_completed_cleanings": self.replaces_local_completed_cleanings,
            "local_counter_keys_not_replaced": list(LOCAL_COUNTER_KEYS),
            "visit_record_count": self.visit_record_count,
            "flush_record_count": self.flush_record_count,
            "aborted_count": self.aborted_count,
            "cloud_not_aborted_flushes": self.not_aborted_count,
            "aborted_unknown_count": self.aborted_unknown_count,
            "aborted_confidence": self.aborted_confidence,
            "record_count_is_not_completed_cleanings": True,
            "visits_per_not_aborted_flush": self.visits_per_not_aborted_flush,
            "visit_day_zeros": list(self.visit_day_zeros),
            "flush_day_zeros": list(self.flush_day_zeros),
            "uncovered_dates": list(self.uncovered_dates),
            "pet_attribution": self.pet_attribution,
            "pet_profile_count": self.pet_profile_count,
            "duplicate_dropped": self.duplicate_dropped,
            "skipped_uncertain_timestamps": self.skipped_uncertain_timestamps,
            "unknown_attribution": self.unknown_attribution,
            "conflict_attribution": self.conflict_attribution,
            "other_device": self.other_device,
            "outside_window": self.outside_window,
            "visit_diary": list(self.visit_diary),
            "flush_diary": list(self.flush_diary),
            "statistics_path": STATISTICS_PATH,
            "statistics_helper": PRIVATE_STATISTICS_HELPER,
        }


def activity_sensor_state(activity: DeviceActivity, key: str) -> Any:
    """Map a sensor key to a state. Unknown stays None, never a fake zero."""
    if key == "visits_today":
        return activity.visits_today
    if key == "last_visit":
        return activity.last_visit
    if key == "last_visit_duration":
        return activity.last_visit_duration_seconds
    if key == "aborted_cycles":
        return activity.aborted_count
    raise KeyError(key)


def parse_account_history(
    payload: Any,
    *,
    window_start: datetime,
    window_end: datetime,
    tz: ZoneInfo,
    timezone_source: str = "explicit",
) -> AccountHistory:
    """Parse one statistics payload. Malformed records are skipped, not fatal."""
    if window_start.tzinfo is None or window_end.tzinfo is None:
        raise ValueError("history window requires aware bounds")
    start = window_start.astimezone(tz)
    end = window_end.astimezone(tz)
    if end < start:
        raise ValueError("history window end is before start")

    visit_key = "missing"
    flush_key = "missing"
    pet_key = "missing"
    pet_count: int | None = None
    visits: list[ParsedEvent] = []
    flushes: list[ParsedEvent] = []
    skipped: list[SkippedRecord] = []

    if isinstance(payload, dict):
        visit_key, raw_visits = _array(payload, "visitResponses")
        flush_key, raw_flushes = _array(payload, "flushResponses")
        pet_key, raw_pets = _array(payload, "petResponses")
        pet_count = _pet_profile_count(pet_key, raw_pets)
        _consume("visit", raw_visits, visit_key, start, end, tz, visits, skipped)
        _consume("flush", raw_flushes, flush_key, start, end, tz, flushes, skipped)
    return AccountHistory(
        window_start=start,
        window_end=end,
        timezone=str(tz),
        timezone_source=timezone_source,
        request_start_time=format_start_time(start),
        visit_key=visit_key,
        flush_key=flush_key,
        pet_key=pet_key,
        pet_profile_count=pet_count,
        visits=tuple(visits),
        flushes=tuple(flushes),
        skipped=tuple(skipped),
    )


async def load_window(
    client: Any,
    *,
    now: datetime,
    tz: ZoneInfo,
    days: int = HISTORY_WINDOW_DAYS,
    timezone_source: str = "explicit",
) -> AccountHistory:
    """Request and parse one explicit window. ``now`` is the caller's clock."""
    start, end = window_bounds(now, tz, days)
    payload = await fetch_statistics(client, start)
    return parse_account_history(
        payload,
        window_start=start,
        window_end=end,
        tz=tz,
        timezone_source=timezone_source,
    )


def _array(payload: dict[str, Any], key: str) -> tuple[str, list[Any] | None]:
    if key not in payload or payload[key] is None:
        return "missing", None
    value = payload[key]
    if isinstance(value, list):
        return ("empty" if not value else "present"), value
    return "malformed", None


def _pet_profile_count(status: str, raw: list[Any] | None) -> int | None:
    if status == "missing":
        return None
    if status == "malformed" or raw is None:
        return None
    return sum(1 for item in raw if isinstance(item, dict))


def _consume(
    kind: str,
    raw: list[Any] | None,
    status: str,
    start: datetime,
    end: datetime,
    tz: ZoneInfo,
    accepted: list[ParsedEvent],
    skipped: list[SkippedRecord],
) -> None:
    if status != "present" and status != "empty":
        return
    if not raw:
        return
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            skipped.append(SkippedRecord(kind, "malformed", "unknown"))
            continue
        device_id, serial = _identity(item)
        when, time_source, time_problem = _event_time(item, kind)
        local_day = None
        if when is not None:
            try:
                local_day = when.astimezone(tz).date()
            except (ValueError, OverflowError):
                time_problem = "uncertain_timestamp"
        if when is None or local_day is None:
            skipped.append(
                SkippedRecord(
                    kind,
                    time_problem or "uncertain_timestamp",
                    "pending",
                    device_id,
                    serial,
                )
            )
            continue
        duration = _duration(item) if kind == "visit" else None
        aborted = _aborted(item) if kind == "flush" else None
        event_id = _event_id(kind, when, device_id, serial, duration, aborted)
        if event_id in seen:
            skipped.append(SkippedRecord(kind, "duplicate", "pending", device_id, serial))
            continue
        seen.add(event_id)
        outcome = None
        if kind == "flush":
            if aborted is None:
                outcome = "unknown"
            elif aborted == 0:
                outcome = "not_aborted"
            else:
                outcome = "aborted"
        accepted.append(
            ParsedEvent(
                kind=kind,
                event_id=event_id,
                when=when,
                local_date=local_day,
                in_window=start <= when <= end,
                device_id=device_id,
                serial_number=serial,
                attribution="pending",
                duration_seconds=duration,
                aborted=aborted,
                outcome=outcome,
                pet_id_present=_pet_id_present(item),
                time_source=time_source or "unknown",
            )
        )


def _activity_for_device(account: AccountHistory, device_filter: DeviceFilter) -> DeviceActivity:
    visits = [_retag(event, device_filter) for event in account.visits]
    flushes = [_retag(event, device_filter) for event in account.flushes]
    skipped = [_retag_skip(item, device_filter) for item in account.skipped]

    attributed_visits = [event for event in visits if event.attribution == "attributed"]
    attributed_flushes = [event for event in flushes if event.attribution == "attributed"]
    in_visits = [event for event in attributed_visits if event.in_window]
    in_flushes = [event for event in attributed_flushes if event.in_window]

    uncertain_skips = [
        item
        for item in skipped
        if item.reason in {"uncertain_timestamp", "malformed", "invalid_timestamp"}
        and item.attribution in {"attributed", "unknown", "conflict", "pending"}
    ]
    duplicate_dropped = sum(
        1
        for item in skipped
        if item.reason == "duplicate" and item.attribution == "attributed"
    )
    unknown_attribution = sum(
        1
        for event in (*visits, *flushes)
        if event.attribution == "unknown"
    ) + sum(1 for item in skipped if item.attribution == "unknown")
    conflict_attribution = sum(
        1 for event in (*visits, *flushes) if event.attribution == "conflict"
    )
    other_device = sum(1 for event in (*visits, *flushes) if event.attribution == "other_device")
    outside_window = sum(1 for event in (*attributed_visits, *attributed_flushes) if not event.in_window)

    today = account.window_end.astimezone(ZoneInfo(account.timezone)).date()
    window_dates = _dates(account.window_start, account.window_end)
    def kind_uncertain(kind: str) -> bool:
        return any(item.kind == kind for item in uncertain_skips) or any(
            event.kind == kind and event.in_window
            and event.attribution in {"unknown", "conflict", "pending"}
            for event in (*visits, *flushes)
        )

    visit_uncertain = kind_uncertain("visit")
    flush_uncertain = kind_uncertain("flush")

    visits_today, today_basis = _today_count(
        in_visits,
        account.visit_key,
        today,
        visit_uncertain,
    )
    if attributed_visits and not in_visits and not visit_uncertain:
        # A server response outside the requested window proves no coverage,
        # not zero visits. Keep a genuine empty response distinct.
        visits_today, today_basis = None, "uncovered"
    aborted_count, not_aborted, aborted_unknown, aborted_confidence = _flush_counts(
        in_flushes,
        account.flush_key,
        flush_uncertain,
    )
    last = max(in_visits, key=lambda event: event.when, default=None)
    ratio = _ratio(
        None if account.visit_key == "missing" or visit_uncertain else len(in_visits),
        not_aborted,
    )
    visit_zeros, visit_uncovered = _day_coverage(
        [event.local_date for event in in_visits],
        window_dates,
    )
    flush_zeros, _flush_uncovered = _day_coverage(
        [event.local_date for event in in_flushes],
        window_dates,
    )
    coverage = _coverage(
        account,
        in_visits,
        in_flushes,
        visit_uncertain or flush_uncertain or bool(outside_window),
        window_dates,
        visit_uncovered,
    )
    pet_attribution = "unavailable"
    if any(event.pet_id_present for event in in_visits):
        pet_attribution = "present_unverified"

    return DeviceActivity(
        coverage=coverage,
        today_basis=today_basis,
        visits_today=visits_today,
        last_visit=None if last is None else last.when,
        last_visit_duration_seconds=None if last is None else last.duration_seconds,
        aborted_count=aborted_count,
        not_aborted_count=not_aborted,
        aborted_unknown_count=aborted_unknown,
        aborted_confidence=aborted_confidence,
        flush_record_count=None if account.flush_key in {"missing", "malformed"} else len(in_flushes),
        visit_record_count=None if account.visit_key in {"missing", "malformed"} else len(in_visits),
        visits_per_not_aborted_flush=ratio,
        visit_day_zeros=visit_zeros,
        flush_day_zeros=flush_zeros,
        uncovered_dates=visit_uncovered,
        pet_attribution=pet_attribution,
        pet_profile_count=account.pet_profile_count,
        duplicate_dropped=duplicate_dropped,
        skipped_uncertain_timestamps=len(uncertain_skips),
        unknown_attribution=unknown_attribution,
        conflict_attribution=conflict_attribution,
        other_device=other_device,
        outside_window=outside_window,
        window_start=account.window_start.isoformat(),
        window_end=account.window_end.isoformat(),
        timezone=account.timezone,
        timezone_source=account.timezone_source,
        request_start_time=account.request_start_time,
        complete_history=False,
        replaces_local_completed_cleanings=False,
        visit_diary=_diary(in_visits, "visit"),
        flush_diary=_diary(in_flushes, "flush"),
    )


def _retag(event: ParsedEvent, device_filter: DeviceFilter) -> ParsedEvent:
    attribution = _classify(event.device_id, event.serial_number, device_filter)
    if attribution == event.attribution:
        return event
    return ParsedEvent(
        kind=event.kind,
        event_id=event.event_id,
        when=event.when,
        local_date=event.local_date,
        in_window=event.in_window,
        device_id=event.device_id,
        serial_number=event.serial_number,
        attribution=attribution,
        duration_seconds=event.duration_seconds,
        aborted=event.aborted,
        outcome=event.outcome,
        pet_id_present=event.pet_id_present,
        time_source=event.time_source,
    )


def _retag_skip(item: SkippedRecord, device_filter: DeviceFilter) -> SkippedRecord:
    if item.attribution != "pending":
        return item
    return SkippedRecord(
        item.kind,
        item.reason,
        _classify(item.device_id, item.serial_number, device_filter),
        item.device_id,
        item.serial_number,
    )


def _today_count(
    visits: list[ParsedEvent],
    visit_key: str,
    today: date,
    uncertain: bool,
) -> tuple[int | None, str]:
    if visit_key in {"missing", "malformed"}:
        return None, "missing"
    if uncertain:
        return None, "uncertain"
    today_visits = [event for event in visits if event.local_date == today]
    if today_visits:
        return len(today_visits), "counted"
    if not visits:
        if visit_key == "empty":
            return 0, "empty_response"
        return 0, "no_attributed_records"
    span = {event.local_date for event in visits}
    first, last = min(span), max(span)
    if first <= today <= last:
        return 0, "day_zero"
    return None, "uncovered"


def _flush_counts(
    flushes: list[ParsedEvent],
    flush_key: str,
    uncertain: bool,
) -> tuple[int | None, int | None, int | None, str]:
    if flush_key in {"missing", "malformed"}:
        return None, None, None, "missing"
    if uncertain:
        return None, None, None, "uncertain"
    aborted = sum(1 for event in flushes if event.outcome == "aborted")
    not_aborted = sum(1 for event in flushes if event.outcome == "not_aborted")
    unknown = sum(1 for event in flushes if event.outcome == "unknown")
    if unknown:
        return None, None, unknown, "partial"
    return aborted, not_aborted, unknown, "exact"


def _ratio(visits: int | None, not_aborted: int | None) -> float | None:
    """Visits divided by not-aborted flushes. Zero denominator is unknown."""
    if visits is None or not_aborted is None or not_aborted == 0:
        return None
    return visits / not_aborted


def _coverage(
    account: AccountHistory,
    visits: list[ParsedEvent],
    flushes: list[ParsedEvent],
    uncertain: bool,
    window_dates: tuple[date, ...],
    uncovered: tuple[str, ...],
) -> str:
    if account.visit_key == "missing" and account.flush_key == "missing":
        return "missing"
    if account.visit_key == "missing" or account.flush_key == "missing":
        return "partial"
    if account.visit_key == "malformed" or account.flush_key == "malformed":
        return "partial"
    if uncertain:
        return "partial"
    if not visits and not flushes:
        if account.visit_key == "empty" and account.flush_key == "empty":
            return "empty"
        if not uncertain:
            return "no_attributed_records"
        return "partial"
    if uncovered:
        return "partial"
    if window_dates and not uncovered:
        return "window_observed"
    return "partial"


def _day_coverage(
    event_dates: list[date],
    window_dates: tuple[date, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not event_dates:
        return (), tuple(day.isoformat() for day in window_dates)
    first, last = min(event_dates), max(event_dates)
    present = set(event_dates)
    zeros = tuple(
        day.isoformat()
        for day in window_dates
        if first <= day <= last and day not in present
    )
    uncovered = tuple(
        day.isoformat() for day in window_dates if day < first or day > last
    )
    return zeros, uncovered


def _dates(start: datetime, end: datetime) -> tuple[date, ...]:
    day = start.date()
    last = end.date()
    found: list[date] = []
    while day <= last:
        found.append(day)
        day += timedelta(days=1)
    return tuple(found)


def _diary(events: list[ParsedEvent], kind: str) -> tuple[dict[str, Any], ...]:
    ordered = sorted(events, key=lambda event: event.when, reverse=True)[:_DIARY_LIMIT]
    rows: list[dict[str, Any]] = []
    for event in ordered:
        if kind == "visit":
            rows.append(
                {
                    "at": event.when.isoformat(),
                    "duration_seconds": event.duration_seconds,
                    "event_id": event.event_id,
                }
            )
        else:
            rows.append(
                {
                    "at": event.when.isoformat(),
                    "outcome": event.outcome,
                    "aborted": event.aborted,
                    "event_id": event.event_id,
                }
            )
    return tuple(rows)


def _fields(record: Mapping[str, Any]) -> dict[str, Any]:
    raw = record.get("fields")
    if isinstance(raw, dict):
        return raw
    return {}


def _identity(record: Mapping[str, Any]) -> tuple[str | None, str | None]:
    fields = _fields(record)
    return _text(fields.get("deviceId")), _text(fields.get("serialNumber"))


def _canonical_device_id(value: str | None) -> str | None:
    """Canonicalise only complete MAC spellings; all other IDs stay exact."""
    import re

    if value is None:
        return None
    if re.fullmatch(r"[0-9a-fA-F]{12}|(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}|(?:[0-9a-fA-F]{2}-){5}[0-9a-fA-F]{2}|(?:[0-9a-fA-F]{4}\.){2}[0-9a-fA-F]{4}", value):
        return value.replace(":", "").replace("-", "").replace(".", "").lower()
    return value


def _classify(
    device_id: str | None,
    serial: str | None,
    device_filter: DeviceFilter | None,
) -> str:
    if device_filter is None:
        if device_id or serial:
            return "pending"
        return "unknown"
    id_match = bool(device_id and _canonical_device_id(device_id) in {
        _canonical_device_id(value) for value in device_filter.device_ids
    })
    serial_match = bool(serial and serial in device_filter.serial_numbers)
    # Disagree only when both identifiers can be checked. A missing serial
    # in the filter is not evidence that the record's serial belongs elsewhere.
    if (
        device_id
        and serial
        and device_filter.device_ids
        and device_filter.serial_numbers
        and (id_match or serial_match)
        and not (id_match and serial_match)
    ):
        return "conflict"
    if id_match or serial_match:
        return "attributed"
    if not device_id and not serial:
        return "unknown"
    # Only a comparable, nonmatching identifier proves another device.
    if (device_id and device_filter.device_ids) or (serial and device_filter.serial_numbers):
        return "other_device"
    return "unknown"


def _event_time(
    record: Mapping[str, Any],
    kind: str,
) -> tuple[datetime | None, str | None, str | None]:
    fields = _fields(record)
    primary = "rtcStart" if kind == "visit" else "rtcEnd"
    if primary in fields and fields.get(primary) not in (None, ""):
        rtc_value = fields.get(primary)
        parsed = _parse_time(rtc_value)
        if parsed is not None:
            return parsed, primary, None
        # A well-formed naive ISO datetime is not UTC and not the HA zone.
        # Use another already-aware clock. Malformed text does not fall back.
        if _wellformed_naive_iso(rtc_value):
            return _fallback_time(record)
        return None, None, "uncertain_timestamp"
    return _fallback_time(record)


def _fallback_time(
    record: Mapping[str, Any],
) -> tuple[datetime | None, str | None, str | None]:
    """Aware machineTS, then integer timestamp. Never assigns a zone or now."""
    if record.get("machineTS") not in (None, ""):
        parsed = _parse_time(record.get("machineTS"))
        if parsed is None:
            return None, None, "uncertain_timestamp"
        return parsed, "machineTS", None
    if "timestamp" in record and record.get("timestamp") not in (None, ""):
        parsed = _parse_time(record.get("timestamp"))
        if parsed is None:
            return None, None, "uncertain_timestamp"
        return parsed, "timestamp", None
    return None, None, "uncertain_timestamp"


def _wellformed_naive_iso(value: Any) -> bool:
    """True for a timezone-naive ISO datetime. Does not assign a zone.

    A bare date has no clock and is not this case. Observed RTC values use
    a ``T`` separator and no offset.
    """
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text or "T" not in text or not _looks_naive(text):
        return False
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return False
    return parsed.tzinfo is None or parsed.utcoffset() is None


def _parse_time(value: Any) -> datetime | None:
    """Accept aware ISO strings and unix seconds/milliseconds. Never use now."""
    if type(value) is int:
        seconds = _epoch_seconds(value)
        if seconds is None:
            return None
        try:
            return datetime.fromtimestamp(seconds, timezone.utc)
        except (ValueError, OverflowError):
            return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or _looks_naive(text):
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    try:
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _looks_naive(text: str) -> bool:
    if text.endswith(("Z", "z")):
        return False
    if len(text) >= 6 and text[-6] in "+-" and text[-3] == ":":
        return False
    if len(text) >= 5 and text[-5] in "+-" and text[-4:].isdigit():
        return False
    return True


def _epoch_seconds(value: int) -> float | None:
    if _EPOCH_MIN <= value <= _EPOCH_MAX:
        return float(value)
    # Bound arbitrary-size integers before converting them to float.
    if _EPOCH_MIN * 1000 <= value <= _EPOCH_MAX * 1000:
        return value / 1000
    return None


def _duration(record: Mapping[str, Any]) -> int | None:
    fields = _fields(record)
    value = fields.get("durationSeconds")
    if type(value) is int and value >= 0:
        return value
    return None


def _aborted(record: Mapping[str, Any]) -> int | None:
    """Only a real int is an abort code. The app marks nonzero ints with '!'."""
    fields = _fields(record)
    value = fields.get("aborted")
    if type(value) is int:
        return value
    return None


def _pet_id_present(record: Mapping[str, Any]) -> bool:
    fields = _fields(record)
    for source in (fields, record):
        if isinstance(source, Mapping) and _text(source.get("petId")):
            return True
    return False


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _event_id(
    kind: str,
    when: datetime,
    device_id: str | None,
    serial: str | None,
    duration: int | None,
    aborted: int | None,
) -> str:
    if kind == "visit":
        disc = "missing" if duration is None else str(duration)
    else:
        disc = "missing" if aborted is None else str(aborted)
    canonical = "|".join(
        (
            kind,
            when.astimezone(timezone.utc).isoformat(),
            device_id or "",
            serial or "",
            disc,
        )
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]
