"""SYNTHETIC activity-history contract.

Red cases lock interpretations the cloud payload does not support: the
public statistics getter has no startTime, flush length is not completed
cleanings, uncertain timestamps are not replaced with now, and pet profiles
are not visit owners. Green cases check the parser and activity sensors
against real dependency models. No cloud or Home Assistant process is used.
"""

from __future__ import annotations

import importlib.util
import inspect
import os
import sys
import unittest
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch as mock_patch
from zoneinfo import ZoneInfo

CANDIDATE = Path(__file__).resolve().parents[2]


def _load(name: str, relative: str):
    """Load a module file without executing the integration package init."""
    spec = importlib.util.spec_from_file_location(name, CANDIDATE / relative)
    if spec is None or spec.loader is None:
        raise ImportError(relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_history = _load(
    "catgenie_activity_history_under_test",
    "custom_components/catgenie/history.py",
)
_const = _load(
    "catgenie_activity_const_under_test",
    "custom_components/catgenie/const.py",
)
HISTORY_SCAN_INTERVAL = _history.HISTORY_SCAN_INTERVAL
HISTORY_WINDOW_DAYS = _history.HISTORY_WINDOW_DAYS
LOCAL_COUNTER_KEYS = _history.LOCAL_COUNTER_KEYS
STATISTICS_PATH = _history.STATISTICS_PATH
DeviceFilter = _history.DeviceFilter
fetch_statistics = _history.fetch_statistics
format_start_time = _history.format_start_time
parse_account_history = _history.parse_account_history
statistics_request = _history.statistics_request
window_bounds = _history.window_bounds
load_window = _history.load_window
SCAN_INTERVAL_ACTIVE = _const.SCAN_INTERVAL_ACTIVE
SCAN_INTERVAL_IDLE = _const.SCAN_INTERVAL_IDLE

TZ = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 31, 1, 30, tzinfo=TZ)
START = datetime(2026, 10, 29, 0, 0, tzinfo=TZ)
FROZEN_NOW = datetime(2026, 10, 31, 5, 30, tzinfo=timezone.utc)
# Invented timestamps, not owner activity. Preserve the observed clock shapes.
VISIT_RTC = "2026-10-30T06:00:02"
VISIT_MACHINE_TS = "2026-10-30T02:00:00-04:00"
VISIT_EPOCH_MS = 1793340000000
FLUSH_RTC = "2026-10-30T20:00:00"
FLUSH_MACHINE_TS = "2026-10-30T16:00:03-04:00"
FLUSH_EPOCH_MS = 1793390403000


def iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def visit(
    when: datetime,
    *,
    device: str | None = "dev-a",
    serial: str | None = "SER-A",
    duration: object = 90,
    pet_id: str | None = None,
    rtc: object | None = None,
    omit_rtc: bool = False,
) -> dict:
    fields: dict = {}
    if not omit_rtc:
        fields["rtcStart"] = iso(when) if rtc is None else rtc
    if serial is not None:
        fields["serialNumber"] = serial
    if device is not None:
        fields["deviceId"] = device
    if duration is not None:
        fields["durationSeconds"] = duration
    if pet_id is not None:
        fields["petId"] = pet_id
    return {
        "timestamp": int(when.timestamp()),
        "type": "visit",
        "machineTS": iso(when),
        "fields": fields,
    }


def flush(
    when: datetime,
    *,
    serial: str | None = "SER-A",
    aborted: object = 0,
    omit_aborted: bool = False,
    device: str | None = None,
) -> dict:
    fields: dict = {}
    fields["rtcEnd"] = iso(when)
    if serial is not None:
        fields["serialNumber"] = serial
    if device is not None:
        fields["deviceId"] = device
    if not omit_aborted:
        fields["aborted"] = aborted
    return {
        "timestamp": int(when.timestamp()),
        "type": "flush",
        "machineTS": iso(when),
        "fields": fields,
    }


def _synthetic_visit(
    *,
    device: str | None = "MAC",
    serial: str | None = "SER-A",
    duration: object = 77,
    machine_ts: str = VISIT_MACHINE_TS,
    epoch_ms: int = VISIT_EPOCH_MS,
    rtc: str = VISIT_RTC,
) -> dict:
    """Synthetic visit with naive RTC, offset machineTS, integer epoch."""
    fields: dict = {"rtcStart": rtc, "durationSeconds": duration}
    if serial is not None:
        fields["serialNumber"] = serial
    if device is not None:
        fields["deviceId"] = device
    return {
        "timestamp": epoch_ms,
        "type": "visit",
        "machineTS": machine_ts,
        "fields": fields,
    }


def _synthetic_flush(
    *,
    serial: str | None = "SER-A",
    aborted: object = 1,
    machine_ts: str = FLUSH_MACHINE_TS,
    epoch_ms: int = FLUSH_EPOCH_MS,
    rtc: str = FLUSH_RTC,
    omit_aborted: bool = False,
) -> dict:
    """Synthetic flush with naive rtcEnd, offset machineTS, no deviceId."""
    fields: dict = {"rtcEnd": rtc}
    if serial is not None:
        fields["serialNumber"] = serial
    if not omit_aborted:
        fields["aborted"] = aborted
    return {
        "timestamp": epoch_ms,
        "type": "flush",
        "machineTS": machine_ts,
        "fields": fields,
    }


def payload(*records: dict, pets: list | None = None, omit: tuple[str, ...] = ()) -> dict:
    visits = [item for item in records if item.get("type") == "visit"]
    flushes = [item for item in records if item.get("type") == "flush"]
    body = {
        "visitResponses": visits,
        "flushResponses": flushes,
        "petResponses": [] if pets is None else pets,
    }
    for key in omit:
        body.pop(key, None)
    return body


def activity(body: dict, *, device: str = "dev-a", serial: str = "SER-A", start=START, end=NOW):
    parsed = parse_account_history(body, window_start=start, window_end=end, tz=TZ)
    return parsed.for_device(DeviceFilter(frozenset({device}), frozenset({serial})))


class ActivityHistoryRedContract(unittest.TestCase):
    """Interpretations that must stay rejected."""

    def test_red_public_getter_cannot_express_start_time(self):
        dependency = os.environ.get("CATGENIE_TEST_DEPENDENCY")
        inserted = bool(dependency) and dependency not in sys.path
        if inserted:
            sys.path.insert(0, dependency)
        try:
            from catgenie.client import CatGenieClient
            from catgenie.const import ENDPOINT_PET_STATS
        finally:
            if inserted and sys.path and sys.path[0] == dependency:
                sys.path.pop(0)
        signature = inspect.signature(CatGenieClient.get_pet_statistics)
        self.assertEqual(list(signature.parameters), ["self"])
        self.assertEqual(ENDPOINT_PET_STATS, STATISTICS_PATH)
        spec = statistics_request(START)
        self.assertEqual(spec["helper"], "CatGenieClient._request")
        self.assertEqual(spec["not_used"], "CatGenieClient.get_pet_statistics")
        self.assertEqual(set(spec["params"]), {"startTime"})
        self.assertNotIn("page", spec["params"])
        self.assertNotIn("pageSize", spec["params"])

    def test_red_fetch_does_not_call_the_public_getter(self):
        class FakeClient:
            def __init__(self) -> None:
                self.calls = []
                self.public = 0

            async def _request(self, method, path, params=None):
                self.calls.append((method, path, params))
                return {"visitResponses": [], "flushResponses": [], "petResponses": []}

            async def get_pet_statistics(self, *args, **kwargs):
                self.public += 1
                raise AssertionError("public getter must not be used")

        client = FakeClient()
        parsed = asyncio.run(load_window(client, now=NOW, tz=TZ, days=3))
        self.assertEqual(client.public, 0)
        self.assertEqual(client.calls[0][0], "GET")
        self.assertEqual(client.calls[0][1], STATISTICS_PATH)
        self.assertEqual(client.calls[0][2]["startTime"], format_start_time(window_bounds(NOW, TZ, 3)[0]))
        self.assertEqual(parsed.request_start_time, client.calls[0][2]["startTime"])
        self.assertFalse(parsed.for_device(DeviceFilter(frozenset({"dev-a"}), frozenset())).complete_history)

    def test_red_flush_length_is_not_completed_cleanings(self):
        when = datetime(2026, 10, 31, 0, 30, tzinfo=TZ)
        reading = activity(
            payload(
                flush(when, aborted=1),
                flush(when + timedelta(minutes=5), aborted=0),
                flush(when + timedelta(minutes=10), omit_aborted=True),
                flush(when + timedelta(minutes=5), aborted=0),
            )
        )
        self.assertEqual(reading.flush_record_count, 3)
        self.assertIsNone(reading.aborted_count)
        self.assertIsNone(reading.not_aborted_count)
        self.assertEqual(reading.aborted_unknown_count, 1)
        self.assertEqual(reading.aborted_confidence, "partial")
        self.assertNotEqual(reading.flush_record_count, reading.not_aborted_count)
        self.assertFalse(reading.replaces_local_completed_cleanings)
        self.assertNotIn("completed_cleanings", reading.sensor_attributes())
        self.assertNotIn("recovery_runs", reading.sensor_attributes())

    def test_unrepresentable_timestamp_preserves_valid_peers_and_coverage(self):
        # Deliberately malformed, synthetic boundaries, not vendor observations.
        for invalid in (10**1000, -(10**1000),
                        "0001-01-01T00:00:00+01:00",
                        "9999-12-31T23:59:59-01:00",
                        "0001-01-01T00:00:00Z"):
            with self.subTest(boundary=type(invalid).__name__, sign=str(invalid)[:4]):
                bad = visit(FROZEN_NOW, omit_rtc=True)
                bad.pop("machineTS")
                bad["timestamp"] = invalid
                good = visit(FROZEN_NOW)
                account = parse_account_history(
                    payload(good, bad), window_start=START, window_end=NOW, tz=TZ
                )
                self.assertEqual(len(account.visits), 1)
                self.assertEqual(account.visits[0].when, FROZEN_NOW)
                self.assertEqual(len(account.skipped), 1)
                self.assertEqual(account.skipped[0].reason, "uncertain_timestamp")
                reading = account.for_device(DeviceFilter(
                    frozenset({"dev-a"}), frozenset({"SER-A"})
                ))
                self.assertEqual(reading.last_visit, FROZEN_NOW)
                self.assertEqual(reading.skipped_uncertain_timestamps, 1)
                self.assertEqual(reading.today_basis, "uncertain")
                self.assertIsNone(reading.visits_today)

    def test_timestamp_normalization_keeps_supported_epochs_and_offsets(self):
        for value in (int(FROZEN_NOW.timestamp()), int(FROZEN_NOW.timestamp() * 1000),
                      "2026-10-31T01:30:00-04:00"):
            self.assertEqual(_history._parse_time(value), FROZEN_NOW)
        # Only normalization failures are classified as malformed timestamps.
        with mock_patch.object(_history, "_epoch_seconds", side_effect=RuntimeError("synthetic")):
            with self.assertRaises(RuntimeError):
                _history._parse_time(123)

    def test_red_uncertain_timestamp_is_not_replaced_with_now(self):
        bad = visit(FROZEN_NOW, rtc="not-a-date")
        self.assertTrue(bad["machineTS"])
        # Standalone naive ISO has no aware machineTS and no integer timestamp.
        # The same RTC plus a valid machineTS is a fallback, not now().
        naive = visit(FROZEN_NOW, rtc="2026-10-31T12:00:00")
        naive["machineTS"] = ""
        naive["timestamp"] = ""
        epoch = visit(FROZEN_NOW, omit_rtc=True)
        epoch["machineTS"] = ""
        epoch["timestamp"] = 0
        boolean = visit(FROZEN_NOW, omit_rtc=True)
        boolean["machineTS"] = ""
        boolean["timestamp"] = True
        reading = activity(payload(bad, naive, epoch, boolean))
        self.assertIsNone(reading.last_visit)
        self.assertIsNone(reading.visits_today)
        self.assertEqual(reading.today_basis, "uncertain")
        self.assertEqual(reading.skipped_uncertain_timestamps, 4)
        self.assertEqual(reading.visit_diary, ())

    def test_red_pet_profile_is_not_visit_ownership(self):
        when = datetime(2026, 10, 31, 0, 15, tzinfo=TZ)
        pets = [
            {
                "name": "WhiskersNotAVisit",
                "id": "pet-secret-id",
                "weight": 9.87,
                "lastVisitTime": "2026-10-31T04:00:00.000Z",
                "userId": "user-secret",
            }
        ]
        reading = activity(payload(visit(when), pets=pets))
        text = str(reading.sensor_attributes())
        self.assertEqual(reading.pet_attribution, "unavailable")
        self.assertEqual(reading.pet_profile_count, 1)
        self.assertNotIn("WhiskersNotAVisit", text)
        self.assertNotIn("pet-secret-id", text)
        self.assertNotIn("9.87", text)
        self.assertNotIn("user-secret", text)
        self.assertNotIn("per_cat", text)
        self.assertNotIn("weight", reading.sensor_attributes())


class ActivityHistoryGreenContract(unittest.TestCase):
    """Window, dedup, device, abort and coverage behavior."""

    def test_timezone_day_boundary_uses_explicit_local_date(self):
        before = datetime(2026, 10, 31, 3, 59, 59, tzinfo=timezone.utc)
        at_midnight = datetime(2026, 10, 31, 4, 0, tzinfo=timezone.utc)
        reading = activity(payload(visit(before, duration=10), visit(at_midnight, duration=20)))
        self.assertEqual(before.astimezone(TZ).date().isoformat(), "2026-10-30")
        self.assertEqual(at_midnight.astimezone(TZ).date().isoformat(), "2026-10-31")
        self.assertEqual(reading.visits_today, 1)
        self.assertEqual(reading.today_basis, "counted")
        self.assertEqual(reading.last_visit, at_midnight)
        self.assertEqual(reading.last_visit_duration_seconds, 20)
        self.assertNotIn("2026-10-30", reading.visit_day_zeros)
        self.assertIn("2026-10-29", reading.uncovered_dates)

    def test_dst_repeated_hour_is_two_visits_not_a_duplicate(self):
        fall_now = datetime(2026, 11, 1, 3, 0, tzinfo=TZ)
        start = datetime(2026, 11, 1, 0, 0, tzinfo=TZ)
        first = datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)
        second = datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)
        reading = activity(
            payload(visit(first, duration=11), visit(second, duration=12)),
            start=start,
            end=fall_now,
        )
        self.assertEqual(first.astimezone(TZ).strftime("%H:%M"), "01:30")
        self.assertEqual(second.astimezone(TZ).strftime("%H:%M"), "01:30")
        self.assertEqual(reading.visits_today, 2)
        self.assertEqual(reading.duplicate_dropped, 0)
        self.assertEqual(reading.last_visit_duration_seconds, 12)

    def test_duplicate_events_collapse_and_distinct_duration_does_not(self):
        when = datetime(2026, 10, 31, 0, 10, tzinfo=TZ)
        collapsed = activity(payload(visit(when, duration=40), visit(when, duration=40)))
        distinct = activity(payload(visit(when, duration=40), visit(when, duration=41)))
        self.assertEqual(collapsed.visit_record_count, 1)
        self.assertEqual(collapsed.duplicate_dropped, 1)
        self.assertEqual(collapsed.visits_today, 1)
        again = activity(payload(visit(when, duration=40), visit(when, duration=40)))
        self.assertEqual(collapsed.visit_diary[0]["event_id"], again.visit_diary[0]["event_id"])
        self.assertEqual(distinct.visit_record_count, 2)
        self.assertEqual(distinct.duplicate_dropped, 0)

    def test_unverifiable_identifiers_and_malformed_arrays_remain_unknown(self):
        when = datetime(2026, 10, 31, 0, 20, tzinfo=TZ)
        parsed = parse_account_history(payload(flush(when, serial="SER-A", aborted=1)),
                                       window_start=START, window_end=NOW, tz=TZ)
        unresolved = parsed.for_device(DeviceFilter(frozenset({"dev-a"}), frozenset()))
        self.assertIsNone(unresolved.aborted_count)
        self.assertEqual(unresolved.aborted_confidence, "uncertain")
        self.assertEqual(unresolved.other_device, 0)
        malformed = activity({"visitResponses": {}, "flushResponses": {}})
        self.assertIsNone(malformed.visit_record_count)
        self.assertIsNone(malformed.flush_record_count)

    def test_multi_device_isolation_and_uncomparable_serial_stays_unknown(self):
        """Explicit filters still isolate units and refuse an uncomparable serial.

        This is not the live device mapping. A filter with device ids and no
        serial candidates cannot attribute a flush serial, and must not call
        that flush another device. manufacturerId/macAddress mapping is
        covered by the dependency-backed sensor test.
        """
        when = datetime(2026, 10, 31, 0, 20, tzinfo=TZ)
        body = payload(
            visit(when, device="dev-a", serial="SER-A", duration=15),
            visit(when + timedelta(minutes=1), device="dev-b", serial="SER-B", duration=16),
            flush(when, serial="SER-A", aborted=1),
            flush(when, serial="SER-B", aborted=1),
            flush(when, serial="dev-a", aborted=9),
        )
        ours = activity(body)
        other = activity(body, device="dev-b", serial="SER-B")
        self.assertEqual(ours.visits_today, 1)
        self.assertEqual(ours.aborted_count, 1)
        self.assertEqual(ours.other_device, 3)
        self.assertEqual(other.visits_today, 1)
        self.assertEqual(other.last_visit_duration_seconds, 16)
        serial_only = parse_account_history(
            body, window_start=START, window_end=NOW, tz=TZ
        ).for_device(DeviceFilter(frozenset({"dev-a"}), frozenset()))
        self.assertIsNone(serial_only.aborted_count)
        self.assertEqual(serial_only.visits_today, 1)

    def test_other_device_bad_timestamp_does_not_blank_this_device(self):
        when = datetime(2026, 10, 31, 0, 5, tzinfo=TZ)
        bad = visit(when, device="dev-b", serial="SER-B", rtc="nope")
        good = visit(when, device="dev-a", serial="SER-A", duration=8)
        reading = activity(payload(bad, good))
        self.assertEqual(reading.visits_today, 1)
        self.assertEqual(reading.today_basis, "counted")
        self.assertEqual(reading.skipped_uncertain_timestamps, 0)

    def test_aborted_missing_and_nonzero_stay_separate(self):
        when = datetime(2026, 10, 31, 0, 40, tzinfo=TZ)
        reading = activity(
            payload(
                flush(when, aborted=2),
                flush(when + timedelta(minutes=1), aborted=0),
                flush(when + timedelta(minutes=2), aborted="1"),
                flush(when + timedelta(minutes=3), aborted=True),
                flush(when + timedelta(minutes=4), aborted=0.0),
            )
        )
        self.assertIsNone(reading.aborted_count)
        self.assertIsNone(reading.not_aborted_count)
        self.assertEqual(reading.aborted_unknown_count, 3)
        self.assertEqual(reading.aborted_confidence, "partial")
        # Diary is newest first: bool, string, and float are not integer codes.
        self.assertEqual([row["outcome"] for row in reading.flush_diary],
                         ["unknown", "unknown", "unknown", "not_aborted", "aborted"])

    def test_unknown_attribution_and_zero_denominator(self):
        when = datetime(2026, 10, 31, 0, 50, tzinfo=TZ)
        owned = visit(when, duration=30)
        anonymous = visit(when + timedelta(minutes=1), device=None, serial=None, duration=31)
        with_pet = visit(
            when + timedelta(minutes=2),
            device=None,
            serial=None,
            pet_id="pet-secret-id",
        )
        reading = activity(
            payload(
                owned,
                anonymous,
                with_pet,
                flush(when, aborted=4),
            )
        )
        self.assertIsNone(reading.visits_today)
        self.assertEqual(reading.today_basis, "uncertain")
        self.assertGreater(reading.unknown_attribution, 0)
        self.assertIsNone(reading.visits_per_not_aborted_flush)
        self.assertEqual(reading.not_aborted_count, 0)
        self.assertEqual(reading.pet_attribution, "unavailable")
        clean = activity(payload(owned, visit(when + timedelta(minutes=3), duration=32)))
        self.assertIsNone(clean.visits_per_not_aborted_flush)
        self.assertEqual(clean.visit_record_count, 2)
        ratio = activity(
            payload(owned, visit(when + timedelta(minutes=3), duration=32), flush(when, aborted=0))
        )
        self.assertEqual(ratio.visits_per_not_aborted_flush, 2.0)

    def test_missing_empty_partial_and_day_zero(self):
        missing = activity({})
        self.assertEqual(missing.coverage, "missing")
        self.assertIsNone(missing.visits_today)
        self.assertEqual(missing.today_basis, "missing")
        self.assertIsNone(missing.aborted_count)

        empty = activity(payload())
        self.assertEqual(empty.coverage, "empty")
        self.assertEqual(empty.visits_today, 0)
        self.assertEqual(empty.today_basis, "empty_response")
        self.assertEqual(empty.visit_day_zeros, ())
        self.assertTrue(empty.uncovered_dates)
        self.assertFalse(empty.complete_history)

        early = datetime(2026, 10, 29, 12, 0, tzinfo=TZ)
        later = datetime(2026, 10, 31, 0, 15, tzinfo=TZ)
        spanned = activity(payload(visit(early, duration=5), visit(later, duration=6)))
        self.assertEqual(spanned.visits_today, 1)
        self.assertIn("2026-10-30", spanned.visit_day_zeros)
        self.assertEqual(spanned.coverage, "window_observed")
        self.assertFalse(spanned.complete_history)

        gap_only = activity(payload(visit(early, duration=5)))
        self.assertIsNone(gap_only.visits_today)
        self.assertEqual(gap_only.today_basis, "uncovered")
        self.assertNotIn("2026-10-31", gap_only.visit_day_zeros)
        self.assertEqual(gap_only.coverage, "partial")

    def test_primary_bad_clock_does_not_fall_back_or_use_now(self):
        when = datetime(2026, 10, 31, 0, 12, tzinfo=TZ)
        record = visit(when, rtc="bogus")
        self.assertTrue(record["machineTS"])
        self.assertIsInstance(record["timestamp"], int)
        reading = activity(payload(record))
        self.assertIsNone(reading.last_visit)
        self.assertEqual(reading.skipped_uncertain_timestamps, 1)
        self.assertEqual(reading.visit_diary, ())

    def test_aware_rtc_precedes_offset_machine_ts(self):
        """An aware primary clock wins and keeps its own source label."""
        visit_rtc = datetime(2026, 10, 30, 5, 0, tzinfo=timezone.utc)
        flush_rtc = datetime(2026, 10, 30, 21, 10, tzinfo=timezone.utc)
        machine = datetime.fromisoformat(VISIT_MACHINE_TS).astimezone(timezone.utc)
        visit_row = visit(machine, rtc="2026-10-30T05:00:00+00:00", duration=15)
        visit_row["machineTS"] = VISIT_MACHINE_TS
        visit_row["timestamp"] = VISIT_EPOCH_MS
        flush_row = flush(machine, aborted=0)
        flush_row["fields"]["rtcEnd"] = "2026-10-30T21:10:00+00:00"
        flush_row["machineTS"] = FLUSH_MACHINE_TS
        flush_row["timestamp"] = FLUSH_EPOCH_MS
        parsed = parse_account_history(
            payload(visit_row, flush_row),
            window_start=START,
            window_end=NOW,
            tz=TZ,
        )
        self.assertEqual(parsed.visits[0].time_source, "rtcStart")
        self.assertEqual(parsed.visits[0].when, visit_rtc)
        self.assertNotEqual(parsed.visits[0].when, machine)
        self.assertEqual(parsed.flushes[0].time_source, "rtcEnd")
        self.assertEqual(parsed.flushes[0].when, flush_rtc)

    def test_naive_rtc_uses_aware_machine_ts_for_visit_and_flush(self):
        """Naive RTC uses offset machineTS. It is not labeled UTC or local.

        Invented values: machineTS equals the integer epoch.
        Reading the naive RTC digits as UTC is 2s later for the visit
        and 3s earlier for the flush. That is not the same instant and
        not proof a cycle completed.
        """
        visit_machine = datetime.fromisoformat(VISIT_MACHINE_TS).astimezone(timezone.utc)
        flush_machine = datetime.fromisoformat(FLUSH_MACHINE_TS).astimezone(timezone.utc)
        visit_rtc_as_utc = datetime.fromisoformat(VISIT_RTC).replace(tzinfo=timezone.utc)
        flush_rtc_as_utc = datetime.fromisoformat(FLUSH_RTC).replace(tzinfo=timezone.utc)
        visit_rtc_as_local = datetime.fromisoformat(VISIT_RTC).replace(tzinfo=TZ)
        flush_rtc_as_local = datetime.fromisoformat(FLUSH_RTC).replace(tzinfo=TZ)
        self.assertEqual(
            visit_rtc_as_utc - visit_machine,
            timedelta(seconds=2),
        )
        self.assertEqual(
            flush_machine - flush_rtc_as_utc,
            timedelta(seconds=3),
        )
        self.assertEqual(
            datetime.fromtimestamp(VISIT_EPOCH_MS / 1000, timezone.utc),
            visit_machine,
        )
        self.assertEqual(
            datetime.fromtimestamp(FLUSH_EPOCH_MS / 1000, timezone.utc),
            flush_machine,
        )
        parsed = parse_account_history(
            payload(_synthetic_visit(device="dev-a", duration=77), _synthetic_flush(aborted=0)),
            window_start=START,
            window_end=NOW,
            tz=TZ,
        )
        self.assertEqual(parsed.visits[0].time_source, "machineTS")
        self.assertEqual(parsed.visits[0].when, visit_machine)
        self.assertNotEqual(parsed.visits[0].when, visit_rtc_as_utc)
        self.assertNotEqual(parsed.visits[0].when, visit_rtc_as_local)
        self.assertEqual(parsed.flushes[0].time_source, "machineTS")
        self.assertEqual(parsed.flushes[0].when, flush_machine)
        self.assertNotEqual(parsed.flushes[0].when, flush_rtc_as_utc)
        self.assertNotEqual(parsed.flushes[0].when, flush_rtc_as_local)
        reading = parsed.for_device(DeviceFilter(frozenset({"dev-a"}), frozenset({"SER-A"})))
        self.assertEqual(reading.last_visit, visit_machine)
        self.assertEqual(reading.last_visit_duration_seconds, 77)
        self.assertEqual(reading.skipped_uncertain_timestamps, 0)

    def test_naive_rtc_uses_unix_timestamp_only_when_machine_ts_is_missing(self):
        """Integer epoch is the fallback only when machineTS is absent."""
        when = datetime.fromtimestamp(VISIT_EPOCH_MS / 1000, timezone.utc)
        missing = visit(when, rtc=VISIT_RTC, duration=41)
        missing["machineTS"] = ""
        missing["timestamp"] = VISIT_EPOCH_MS
        parsed = parse_account_history(
            payload(missing), window_start=START, window_end=NOW, tz=TZ
        )
        self.assertEqual(parsed.visits[0].time_source, "timestamp")
        self.assertEqual(parsed.visits[0].when, when)
        self.assertNotEqual(
            parsed.visits[0].when,
            datetime.fromisoformat(VISIT_RTC).replace(tzinfo=timezone.utc),
        )
        absent = visit(when, rtc=VISIT_RTC, duration=41)
        absent.pop("machineTS")
        absent["timestamp"] = VISIT_EPOCH_MS
        absent_parsed = parse_account_history(
            payload(absent), window_start=START, window_end=NOW, tz=TZ
        )
        self.assertEqual(absent_parsed.visits[0].time_source, "timestamp")
        self.assertEqual(absent_parsed.visits[0].when, when)

        blocked = visit(when, rtc=VISIT_RTC, duration=41)
        blocked["machineTS"] = "2026-10-30T00:56:57"
        blocked["timestamp"] = VISIT_EPOCH_MS
        blocked_reading = activity(payload(blocked))
        self.assertIsNone(blocked_reading.last_visit)
        self.assertNotEqual(blocked_reading.last_visit, when)
        self.assertGreaterEqual(blocked_reading.skipped_uncertain_timestamps, 1)

    def test_naive_or_malformed_clocks_without_a_trusted_fallback_stay_unknown(self):
        naive_all = visit(FROZEN_NOW, rtc=VISIT_RTC)
        naive_all["machineTS"] = "2026-10-30T00:56:57"
        naive_all["timestamp"] = str(VISIT_EPOCH_MS)
        malformed = visit(FROZEN_NOW, rtc="not-a-date")
        self.assertTrue(malformed["machineTS"])
        date_only = visit(FROZEN_NOW, rtc="2026-10-30")
        date_only["machineTS"] = ""
        date_only["timestamp"] = VISIT_EPOCH_MS
        bad_epoch = visit(FROZEN_NOW, rtc=VISIT_RTC)
        bad_epoch["machineTS"] = ""
        bad_epoch["timestamp"] = 0
        boolean = visit(FROZEN_NOW, rtc=VISIT_RTC)
        boolean["machineTS"] = ""
        boolean["timestamp"] = True
        reading = activity(payload(naive_all, malformed, date_only, bad_epoch, boolean))
        self.assertIsNone(reading.last_visit)
        self.assertIsNone(reading.visits_today)
        self.assertEqual(reading.skipped_uncertain_timestamps, 5)
        self.assertEqual(reading.visit_diary, ())

    def test_explicit_window_is_seven_local_dates_including_today(self):
        start, end = window_bounds(NOW, TZ)
        self.assertEqual(HISTORY_WINDOW_DAYS, 7)
        self.assertEqual(end, NOW)
        self.assertEqual((end.date() - start.date()).days, 6)
        self.assertEqual(start.timetz().replace(tzinfo=None), datetime.min.time())
        self.assertEqual(format_start_time(start), "2026-10-25T04:00:00.000Z")
        self.assertGreater(HISTORY_SCAN_INTERVAL, SCAN_INTERVAL_IDLE)
        self.assertGreater(HISTORY_SCAN_INTERVAL, SCAN_INTERVAL_ACTIVE)

    def test_naive_window_is_rejected(self):
        with self.assertRaises(ValueError):
            format_start_time(datetime(2026, 10, 31, 0, 0))
        with self.assertRaises(ValueError):
            window_bounds(datetime(2026, 10, 31, 0, 0), TZ)


class ActivitySensorContract(unittest.TestCase):
    """Real device model and unchanged device-sensor keys."""

    @classmethod
    def setUpClass(cls) -> None:
        import tests.unit_cases.test_unknown_operation_state as harness

        dependency = os.environ.get("CATGENIE_TEST_DEPENDENCY")
        paths = [str(CANDIDATE), *([dependency] if dependency else []), *sys.path]
        with mock_patch.dict(sys.modules), mock_patch.object(sys, "path", paths):
            for name in tuple(sys.modules):
                if name == "custom_components" or name.startswith("custom_components.catgenie"):
                    del sys.modules[name]
            harness._install_import_seams()
            from custom_components.catgenie.activity import (
                ACTIVITY_SENSORS,
                CatGenieActivitySensor,
                activity_filter,
            )
            from custom_components.catgenie.history_coordinator import history_failure
            from homeassistant.exceptions import ConfigEntryAuthFailed
            from homeassistant.helpers.update_coordinator import UpdateFailed
            from custom_components.catgenie.operation_state import TolerantDevice
            from custom_components.catgenie.sensor import SENSORS
            import catgenie.models as pinned_models
        cls.harness = harness
        cls.activity_sensors = ACTIVITY_SENSORS
        cls.sensor_cls = CatGenieActivitySensor
        cls.activity_filter = activity_filter
        cls.history_failure = history_failure
        cls.auth_failure_type = ConfigEntryAuthFailed
        cls.update_failure_type = UpdateFailed
        cls.device_cls = TolerantDevice
        cls.pinned_device_cls = pinned_models.Device
        cls.pinned_device_file = pinned_models.__file__
        cls.device_sensors = SENSORS

    def test_existing_sensor_keys_and_local_counters_stay_separate(self):
        keys = tuple(item.key for item in self.device_sensors)
        activity_keys = tuple(item.key for item in self.activity_sensors)
        self.assertEqual(keys, self.harness.SENSOR_KEYS)
        self.assertFalse(set(activity_keys) & set(keys))
        self.assertFalse(set(activity_keys) & set(LOCAL_COUNTER_KEYS))
        self.assertEqual(
            activity_keys,
            ("visits_today", "last_visit", "last_visit_duration", "aborted_cycles"),
        )
        setup = (CANDIDATE / "custom_components/catgenie/__init__.py").read_text()
        self.assertIn("entry.runtime_data = coordinator", setup)
        self.assertNotIn("entry.runtime_data = history", setup)
        self.assertIn("bind_history(coordinator, history)", setup)
        self.assertNotIn("Platform.CALENDAR", setup)
        coordinator = (CANDIDATE / "custom_components/catgenie/history_coordinator.py").read_text()
        self.assertNotIn("raise ConfigEntryAuthFailed", coordinator)
        self.assertIn("update_interval=None", coordinator)

    def test_live_shaped_device_identity_attributes_visits_and_flushes(self):
        """Attribute the observed manufacturerId/macAddress field mapping.

        2026-10-31 readonly join counts, with no identifiers stored here:
        all 20 unparameterized visits had fields.serialNumber equal to
        manufacturerId and fields.deviceId equal to macAddress, not
        manufacturerId. All 21 flushes had fields.serialNumber equal to
        manufacturerId. The raw device had no serialNumber or deviceId
        extras. bleConnectionId also equaled visit deviceId on that unit
        and is not treated as a second device id.
        """
        payload = self.harness.thing("SER-A", 0)
        payload["macAddress"] = "MAC"
        payload["bleConnectionId"] = "BLE-OTHER"
        payload.pop("serialNumber", None)
        payload.pop("deviceId", None)
        self.assertNotIn("serialNumber", payload)
        self.assertNotIn("deviceId", payload)
        pinned_cls = type(self).pinned_device_cls
        source = Path(type(self).pinned_device_file).resolve()
        self.assertTrue(source.is_file())
        dependency = os.environ.get("CATGENIE_TEST_DEPENDENCY")
        if dependency:
            self.assertTrue(source.is_relative_to(Path(dependency).resolve()))
        self.assertEqual(pinned_cls.__module__, "catgenie.models")
        device = self.device_cls.model_validate(payload)
        pinned = pinned_cls.model_validate(payload)
        self.assertIsInstance(pinned, pinned_cls)
        self.assertIsInstance(device, pinned_cls)
        self.assertEqual(pinned.manufacturer_id, "SER-A")
        self.assertEqual(pinned.mac_address, "MAC")
        self.assertNotIn("serialNumber", pinned_cls.model_fields)
        self.assertNotIn("deviceId", pinned_cls.model_fields)
        self.assertNotIn("serialNumber", pinned.model_extra or {})
        self.assertNotIn("deviceId", pinned.model_extra or {})

        chosen = type(self).activity_filter(pinned)
        integration = type(self).activity_filter(device)
        with self.subTest("mapped filter"):
            self.assertEqual(integration, chosen)
            self.assertIn("SER-A", chosen.serial_numbers)
            self.assertNotIn("SER-A", chosen.device_ids)
            self.assertIn("MAC", chosen.device_ids)
            self.assertNotIn("MAC", chosen.serial_numbers)
            self.assertNotIn("BLE-OTHER", chosen.device_ids)
            self.assertNotIn("BLE-OTHER", chosen.serial_numbers)

        early = datetime(2026, 10, 31, 0, 10, tzinfo=TZ)
        late = datetime(2026, 10, 31, 0, 40, tzinfo=TZ)
        other_when = datetime(2026, 10, 31, 0, 50, tzinfo=TZ)
        matched = {
            "visitResponses": [
                visit(early, device="MAC", serial="SER-A", duration=12),
                visit(late, device="MAC", serial="SER-A", duration=45),
                visit(other_when, device="OTHER-MAC", serial="SER-OTHER", duration=99),
            ],
            "flushResponses": [
                flush(late, serial="SER-A", aborted=1),
                flush(other_when, serial="SER-OTHER", aborted=9),
            ],
            "petResponses": [],
        }
        parsed = parse_account_history(
            matched, window_start=START, window_end=NOW, tz=TZ
        )
        reading = parsed.for_device(chosen)
        history = type("History", (), {"data": parsed})()
        devices = type("Devices", (), {"data": {device.manufacturer_id: device}})()
        sensors = [
            type(self).sensor_cls(history, devices, "SER-A", description)
            for description in type(self).activity_sensors
        ]
        with self.subTest("attributed visits and abort"):
            self.assertEqual(sensors[0]._filter, chosen)
            self.assertEqual(reading.visits_today, 2)
            self.assertEqual(reading.last_visit, late)
            self.assertEqual(reading.last_visit_duration_seconds, 45)
            self.assertEqual(reading.aborted_count, 1)
            self.assertEqual(reading.other_device, 2)
            self.assertEqual(reading.conflict_attribution, 0)
            self.assertEqual(reading.unknown_attribution, 0)
            self.assertEqual(sensors[0].native_value, 2)
            self.assertEqual(sensors[1].native_value, late)
            self.assertEqual(sensors[2].native_value, 45)
            self.assertEqual(sensors[3].native_value, 1)
            self.assertNotEqual(reading.last_visit_duration_seconds, 99)

        conflict_body = {
            "visitResponses": [
                visit(late, device="MAC", serial="SER-OTHER", duration=7),
                visit(early, device="OTHER-MAC", serial="SER-A", duration=8),
            ],
            "flushResponses": [flush(late, serial="SER-A", aborted=1)],
            "petResponses": [],
        }
        conflict = parse_account_history(
            conflict_body, window_start=START, window_end=NOW, tz=TZ
        ).for_device(chosen)
        with self.subTest("conflicting identifiers stay unknown"):
            self.assertEqual(conflict.conflict_attribution, 2)
            self.assertIsNone(conflict.visits_today)
            self.assertEqual(conflict.today_basis, "uncertain")
            self.assertIsNone(conflict.last_visit)
            self.assertEqual(conflict.aborted_count, 1)
            self.assertEqual(conflict.other_device, 0)

        unknown_body = {
            "visitResponses": [
                visit(late, device="MAC", serial="SER-A", duration=45),
                visit(early, device=None, serial=None, duration=3),
            ],
            "flushResponses": [
                flush(late, serial="SER-A", aborted=1),
                flush(early, serial=None, aborted=4),
            ],
            "petResponses": [],
        }
        unknown = parse_account_history(
            unknown_body, window_start=START, window_end=NOW, tz=TZ
        ).for_device(chosen)
        with self.subTest("unknown records are not a false zero"):
            self.assertGreater(unknown.unknown_attribution, 0)
            self.assertEqual(unknown.other_device, 0)
            self.assertIsNone(unknown.visits_today)
            self.assertEqual(unknown.today_basis, "uncertain")
            self.assertIsNone(unknown.aborted_count)
            self.assertEqual(unknown.aborted_confidence, "uncertain")

        ble_only = parse_account_history(
            {
                "visitResponses": [
                    visit(late, device="BLE-OTHER", serial="SER-A", duration=45)
                ],
                "flushResponses": [],
                "petResponses": [],
            },
            window_start=START,
            window_end=NOW,
            tz=TZ,
        ).for_device(chosen)
        with self.subTest("bleConnectionId is not an independent device id"):
            self.assertEqual(ble_only.visits_today, None)
            self.assertNotEqual(ble_only.today_basis, "counted")
            self.assertEqual(ble_only.conflict_attribution, 1)

    def test_contradictory_extra_does_not_override_observed_identity(self):
        """A disagreeing extra is not a second identity.

        manufacturerId is the cloud serial and macAddress is the cloud
        deviceId. An extra serial that differs is ignored. A visit whose
        deviceId is the manufacturer id is not this unit. Another device
        stays rejected, and local counters stay untouched.
        """
        payload = self.harness.thing("SER-A", 0)
        payload["macAddress"] = "MAC"
        payload["serialNumber"] = "SER-OTHER"
        payload.pop("deviceId", None)
        device = self.device_cls.model_validate(payload)
        chosen = type(self).activity_filter(device)
        self.assertEqual(chosen.serial_numbers, frozenset({"SER-A"}))
        self.assertEqual(chosen.device_ids, frozenset({"MAC"}))
        self.assertNotIn("SER-OTHER", chosen.serial_numbers)
        self.assertNotIn(device.manufacturer_id, chosen.device_ids)
        agreed = self.harness.thing("SER-A", 0)
        agreed["macAddress"] = "MAC"
        agreed["serialNumber"] = "SER-A"
        agreed["deviceId"] = "MAC"
        same = type(self).activity_filter(self.device_cls.model_validate(agreed))
        self.assertEqual(same, chosen)
        when = datetime(2026, 10, 31, 0, 25, tzinfo=TZ)
        later = when + timedelta(minutes=5)
        parsed = parse_account_history(
            {
                "visitResponses": [
                    visit(when, device="MAC", serial="SER-A", duration=45),
                    visit(later, device="SER-A", serial="SER-OTHER", duration=9),
                    visit(later + timedelta(minutes=1), device="OTHER-MAC", serial="SER-B", duration=8),
                ],
                "flushResponses": [
                    flush(when, serial="SER-A", aborted=1),
                    flush(later, serial="SER-OTHER", aborted=9),
                ],
                "petResponses": [],
            },
            window_start=START,
            window_end=NOW,
            tz=TZ,
        )
        history = type("History", (), {"data": parsed})()
        devices = type("Devices", (), {"data": {device.manufacturer_id: device}})()
        visits_today = type(self).sensor_cls(history, devices, "SER-A", type(self).activity_sensors[0])
        duration = type(self).sensor_cls(history, devices, "SER-A", type(self).activity_sensors[2])
        aborted = type(self).sensor_cls(history, devices, "SER-A", type(self).activity_sensors[3])
        self.assertEqual(visits_today._attr_unique_id, "SER-A_visits_today")
        self.assertEqual(visits_today._filter, chosen)
        self.assertEqual(visits_today.native_value, 1)
        self.assertEqual(duration.native_value, 45)
        self.assertEqual(aborted.native_value, 1)
        self.assertEqual(aborted.entity_description.entity_category, "diagnostic")
        attrs = visits_today.extra_state_attributes
        self.assertEqual(attrs["other_device"], 3)
        self.assertEqual(attrs["conflict_attribution"], 0)
        self.assertFalse(attrs["replaces_local_completed_cleanings"])
        self.assertTrue(attrs["record_count_is_not_completed_cleanings"])
        self.assertNotIn("completed_cleanings", attrs)
        self.assertTrue(visits_today.available)

    def test_unknown_record_does_not_publish_false_zero(self):
        """Missing record ids stay unknown. Another device is not an abort."""
        payload = self.harness.thing("SER-A", 0)
        payload["macAddress"] = "MAC"
        payload.pop("serialNumber", None)
        payload.pop("deviceId", None)
        device = self.device_cls.model_validate(payload)
        chosen = type(self).activity_filter(device)
        self.assertEqual(chosen.serial_numbers, frozenset({"SER-A"}))
        self.assertEqual(chosen.device_ids, frozenset({"MAC"}))
        when = datetime(2026, 10, 31, 0, 25, tzinfo=TZ)
        unknown_parsed = parse_account_history(
            {
                "visitResponses": [visit(when, device=None, serial=None, duration=45)],
                "flushResponses": [flush(when, serial=None, aborted=1)],
                "petResponses": [],
            },
            window_start=START,
            window_end=NOW,
            tz=TZ,
        )
        history = type("History", (), {"data": unknown_parsed})()
        devices = type("Devices", (), {"data": {device.manufacturer_id: device}})()
        visit_entity = type(self).sensor_cls(history, devices, "SER-A", type(self).activity_sensors[0])
        aborted_entity = type(self).sensor_cls(history, devices, "SER-A", type(self).activity_sensors[3])
        self.assertIsNone(visit_entity.native_value)
        self.assertIsNone(aborted_entity.native_value)
        self.assertEqual(aborted_entity.extra_state_attributes["aborted_confidence"], "uncertain")
        self.assertEqual(aborted_entity.extra_state_attributes["other_device"], 0)
        self.assertGreater(aborted_entity.extra_state_attributes["unknown_attribution"], 0)
        other = parse_account_history(
            {
                "visitResponses": [
                    visit(when, device="OTHER-MAC", serial="SER-OTHER", duration=9)
                ],
                "flushResponses": [flush(when, serial="SER-OTHER", aborted=9)],
                "petResponses": [],
            },
            window_start=START,
            window_end=NOW,
            tz=TZ,
        ).for_device(chosen)
        self.assertEqual(other.visits_today, 0)
        self.assertEqual(other.aborted_count, 0)
        self.assertEqual(other.other_device, 2)
        self.assertEqual(other.unknown_attribution, 0)
        self.assertEqual(other.today_basis, "no_attributed_records")

    def test_live_shaped_naive_rtc_matches_one_unit_via_machine_ts(self):
        """Naive RTC plus aware machineTS attributes one unit, not the other.

        Identifier namespace stays manufacturerId -> serialNumber and
        macAddress -> deviceId. Clocks are the sanitized 2026-10-31 shapes:
        naive rtcStart/rtcEnd, offset machineTS, integer millisecond epoch.
        Synthetic ids and a synthetic duration only. The other unit is one
        hour later so a swapped match would change last visit and duration.
        """
        source_file = type(self).pinned_device_file
        assert source_file is not None, "real catgenie model source is required"
        source = Path(source_file).resolve()
        self.assertTrue(source.is_file(), "real catgenie model source is required")
        dependency = os.environ.get("CATGENIE_TEST_DEPENDENCY")
        if dependency:
            self.assertTrue(source.is_relative_to(Path(dependency).resolve()))
        self.assertEqual(type(self).pinned_device_cls.__module__, "catgenie.models")
        self.assertTrue(issubclass(self.device_cls, type(self).pinned_device_cls))
        payload_device = self.harness.thing("SER-A", 0)
        payload_device["macAddress"] = "MAC"
        payload_device["bleConnectionId"] = "BLE-OTHER"
        payload_device.pop("serialNumber", None)
        payload_device.pop("deviceId", None)
        device = self.device_cls.model_validate(payload_device)
        chosen = type(self).activity_filter(device)
        self.assertEqual(chosen.serial_numbers, frozenset({"SER-A"}))
        self.assertEqual(chosen.device_ids, frozenset({"MAC"}))
        self.assertNotIn("SER-A", chosen.device_ids)
        self.assertNotIn("BLE-OTHER", chosen.device_ids)

        visit_when = datetime.fromisoformat(VISIT_MACHINE_TS).astimezone(timezone.utc)
        flush_when = datetime.fromisoformat(FLUSH_MACHINE_TS).astimezone(timezone.utc)
        other_visit = visit_when + timedelta(hours=1)
        other_flush = flush_when + timedelta(hours=1)
        pets = [{"name": "WhiskersNotAVisit", "id": "pet-secret-id", "weight": 9.87}]
        body = {
            "visitResponses": [
                _synthetic_visit(device="MAC", serial="SER-A", duration=77),
                _synthetic_visit(
                    device="OTHER-MAC",
                    serial="SER-OTHER",
                    duration=99,
                    machine_ts=other_visit.isoformat(),
                    epoch_ms=VISIT_EPOCH_MS + 3_600_000,
                    rtc="2026-10-30T05:56:59",
                ),
            ],
            "flushResponses": [
                _synthetic_flush(serial="SER-A", aborted=1),
                _synthetic_flush(
                    serial="SER-OTHER",
                    aborted=9,
                    machine_ts=other_flush.isoformat(),
                    epoch_ms=FLUSH_EPOCH_MS + 3_600_000,
                    rtc="2026-10-30T22:00:38",
                ),
            ],
            "petResponses": pets,
        }
        day_start = datetime(2026, 10, 30, 0, 0, tzinfo=TZ)
        day_end = datetime(2026, 10, 30, 22, 0, tzinfo=TZ)
        parsed = parse_account_history(
            body, window_start=day_start, window_end=day_end, tz=TZ
        )
        ours = [event for event in parsed.visits if event.serial_number == "SER-A"]
        our_flush = [event for event in parsed.flushes if event.serial_number == "SER-A"]
        self.assertEqual(len(ours), 1)
        self.assertEqual(ours[0].time_source, "machineTS")
        self.assertEqual(ours[0].when, visit_when)
        self.assertEqual(len(our_flush), 1)
        self.assertEqual(our_flush[0].time_source, "machineTS")
        self.assertEqual(our_flush[0].when, flush_when)
        self.assertNotEqual(
            ours[0].when,
            datetime.fromisoformat(VISIT_RTC).replace(tzinfo=timezone.utc),
        )
        self.assertNotEqual(
            our_flush[0].when,
            datetime.fromisoformat(FLUSH_RTC).replace(tzinfo=timezone.utc),
        )

        reading = parsed.for_device(chosen)
        history = type("History", (), {"data": parsed})()
        devices = type("Devices", (), {"data": {device.manufacturer_id: device}})()
        sensors = [
            type(self).sensor_cls(history, devices, "SER-A", description)
            for description in type(self).activity_sensors
        ]
        self.assertEqual(reading.visit_record_count, 1)
        self.assertEqual(reading.flush_record_count, 1)
        self.assertEqual(reading.visits_today, 1)
        self.assertEqual(reading.today_basis, "counted")
        self.assertEqual(reading.last_visit, visit_when)
        self.assertEqual(reading.last_visit_duration_seconds, 77)
        self.assertNotEqual(reading.last_visit_duration_seconds, 99)
        self.assertEqual(reading.aborted_count, 1)
        self.assertNotEqual(reading.aborted_count, 9)
        self.assertEqual(reading.other_device, 2)
        self.assertEqual(reading.unknown_attribution, 0)
        self.assertEqual(reading.conflict_attribution, 0)
        self.assertEqual(reading.skipped_uncertain_timestamps, 0)
        self.assertEqual(reading.pet_attribution, "unavailable")
        self.assertEqual(sensors[0].native_value, 1)
        self.assertEqual(sensors[1].native_value, visit_when)
        self.assertEqual(sensors[2].native_value, 77)
        self.assertEqual(sensors[3].native_value, 1)
        text = str(sensors[0].extra_state_attributes)
        self.assertNotIn("WhiskersNotAVisit", text)
        self.assertNotIn("pet-secret-id", text)
        self.assertFalse(sensors[0].extra_state_attributes["replaces_local_completed_cleanings"])

        later = parse_account_history(
            body, window_start=START, window_end=NOW, tz=TZ
        ).for_device(chosen)
        self.assertEqual(later.last_visit, visit_when)
        self.assertEqual(later.last_visit_duration_seconds, 77)
        self.assertEqual(later.visit_record_count, 1)
        self.assertEqual(later.flush_record_count, 1)
        self.assertEqual(later.skipped_uncertain_timestamps, 0)
        self.assertIsNone(later.visits_today)
        self.assertEqual(later.today_basis, "uncovered")

        missing_ids = {
            "visitResponses": [_synthetic_visit(device=None, serial=None, duration=77)],
            "flushResponses": [_synthetic_flush(serial=None, aborted=1)],
            "petResponses": [],
        }
        blank = parse_account_history(
            missing_ids, window_start=day_start, window_end=day_end, tz=TZ
        ).for_device(chosen)
        self.assertIsNone(blank.visits_today)
        self.assertIsNone(blank.last_visit)
        self.assertIsNone(blank.aborted_count)
        self.assertGreater(blank.unknown_attribution, 0)
        self.assertEqual(blank.other_device, 0)

    def test_history_failure_does_not_request_reauth(self):
        failure = type(self).history_failure(RuntimeError("history down"))
        self.assertIsInstance(failure, self.update_failure_type)
        self.assertNotIsInstance(failure, self.auth_failure_type)
        self.assertNotIn("history down", str(failure))
        self.assertIn("RuntimeError", str(failure))
        self.assertIn("unavailable", str(failure))


if __name__ == "__main__":
    unittest.main()
