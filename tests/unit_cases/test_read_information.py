"""SYNTHETIC parser contracts for the read-only notification and firmware lane.

Fixtures are labeled SYNTHETIC. They are not a live feed, not a type-24
acceptance sample, and not a latest-firmware display. The Home Assistant
startup, entity, and coordinator checks run in a subprocess against the
actual Home Assistant environment. This file does not call the vendor.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PARSER_PATH = ROOT / "custom_components" / "catgenie" / "read_information.py"
HA_CONTRACT = Path(__file__).resolve().parents[1].joinpath("read_information_ha_contract.py")
FIXTURE = "SYNTHETIC"

EXPECTED_TYPES = {
    "MISSING_LIGHT": 1,
    "LOW_WATER_PRESSURE": 2,
    "DRAINAGE_PROBLEM": 3,
    "BI_METAL": 4,
    "MISSING_CARTRIDGE": 5,
    "EMPTY_CARTRIDGE": 6,
    "CARTRIDGE_LOW_LEVEL": 7,
    "INCORRECT_CARTRIDGE": 8,
    "CLEAN_LIGHT_GUIDE": 9,
    "LIGHT_GUIDE_DIRTY": 10,
    "EWI_W_WATER_IDIOPATHIC": 11,
    "CYCLE_POSTPONDED": 17,
    "PET_VISITED": 20,
    "SYSTEM_MESSAGE": 21,
    "FW_FAILED": 22,
    "FW_UPDATE": 24,
    "FW_SUCCESS": 25,
    "CG_CONNECTION_CHANGE": 29,
    "DEVICE_DETAILS_CHANGED": 30,
    "RESET_NOTIFICATIONS": 31,
    "E_TEMP_MISSING": 51,
    "EWI_E_TEMP_OUTLET_MISSING": 52,
    "E_TEMP_SHORT": 61,
    "EWI_E_TEMP_OUTLET_SHORT": 62,
    "EWI_W_HEATER_CLOG": 91,
    "INVITE_TO_SHARE_ACCOUNT": 101,
    "USER_ACCEPTED_INVITATION": 102,
    "USER_REJECTED_INVITATION": 103,
    "USER_REMOVED_FROM_ACCOUNT": 104,
    "ADMIN_CHANGED": 105,
    "USER_LEFT_ACCOUNT": 106,
    "AIRWAY_CLOGGED": 1002,
}
STRING_KEYS = (
    "CG_MALFUNCTION",
    "CG_NOT_CONNECTED_TO_WIFI",
    "CG_NOT_CONNECTED",
    "PET_NOT_VISITED",
    "NEW_MARKETING_FEED",
    "UNKNOWN_ERROR",
)
KNOWN = frozenset({"UNIT-A", "UNIT-B"})


def _load():
    spec = importlib.util.spec_from_file_location(
        "catgenie_read_information_under_test", PARSER_PATH
    )
    if spec is None or spec.loader is None:
        raise AssertionError(f"missing parser module: {PARSER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _item(
    type_value,
    *,
    parent=None,
    device=None,
    creation="2026-10-31T15:04:05Z",
    version=None,
    name="SYNTHETIC-name",
    extra=None,
):
    payload = {"_fixture": FIXTURE}
    if type_value is not _OMIT:
        payload["type"] = type_value
    if parent is not _OMIT:
        payload["parentDeviceId"] = parent
    if device is not _OMIT:
        payload["deviceId"] = device
    if name is not _OMIT:
        payload["deviceName"] = name
    if version is not _OMIT and version is not None:
        payload["version"] = version
    if extra:
        payload.update(extra)
    return {
        "_fixture": FIXTURE,
        "id": "synthetic-item",
        "creationTime": creation,
        "data": json.dumps(payload),
    }


class _OMIT:
    pass


class NotificationParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def parse(self, notifications, known=KNOWN):
        return self.mod.parse_feed(
            {"userId": "synthetic-user", "notifications": notifications},
            known,
        )

    def test_integer_table_matches_the_app_and_rejects_string_keys(self):
        table = self.mod.NOTIFICATION_TYPES
        self.assertEqual(table, {value: name for name, value in EXPECTED_TYPES.items()})
        self.assertEqual(table[17], "CYCLE_POSTPONDED")
        self.assertNotIn(12, table)
        self.assertNotIn(23, table)
        self.assertNotIn(0, table)
        for name in STRING_KEYS:
            self.assertNotIn(name, table)
            self.assertNotIn(name, table.values())

    def test_substring_and_string_types_are_not_named_events(self):
        feed = self.parse(
            [
                _item("firmware update available", parent="UNIT-A"),
                _item("stop", parent="UNIT-A"),
                _item("low cartridge", parent="UNIT-A"),
                _item("cat visited", parent="UNIT-A"),
                _item("CG_MALFUNCTION", parent="UNIT-A"),
                _item("24", parent="UNIT-A"),
            ]
        )
        self.assertEqual(feed.response_count, 6)
        self.assertEqual(len(feed.notices), 6)
        for notice in feed.notices:
            self.assertIsNone(notice.type_code)
            self.assertIsNone(notice.type_name)
            self.assertEqual(notice.manufacturer_id, "UNIT-A")
        self.assertEqual(feed.unparsed_count, 0)

    def test_missing_type_is_not_zero_and_missing_id_is_not_empty(self):
        omitted = _item(_OMIT, parent=_OMIT, device=_OMIT, name=_OMIT)
        blank = _item(None, parent="", device="", name="")
        zero = _item(0, parent=0, device=0, name=0)
        boolean = _item(True, parent=True, device=False)
        feed = self.parse([omitted, blank, zero, boolean])
        self.assertEqual(feed.response_count, 4)
        self.assertEqual(feed.unattributed_count, 4)
        self.assertEqual(feed.notices[0].type_code, None)
        self.assertNotEqual(feed.notices[0].type_code, 0)
        self.assertIsNone(feed.notices[0].type_name)
        self.assertIsNone(feed.notices[1].manufacturer_id)
        self.assertIsNone(feed.notices[2].manufacturer_id)
        self.assertEqual(feed.notices[2].type_code, 0)
        self.assertIsNone(feed.notices[2].type_name)
        self.assertIsNone(feed.notices[3].type_code)
        self.assertNotIn("", [notice.manufacturer_id for notice in feed.notices])

    def test_exact_manufacturer_id_match_and_conflict(self):
        feed = self.parse(
            [
                _item(20, parent="UNIT-A"),
                _item(20, device="UNIT-B"),
                _item(20, parent="UNIT-A", device="UNIT-A"),
                _item(20, parent="UNIT-A", device="UNIT-B"),
                _item(20, parent="OTHER", device="UNIT-A"),
                _item(20, parent="UNIT-A", name="UNIT-B", device=_OMIT),
                _item(20, parent="nope", device="also-nope", name="UNIT-A"),
            ]
        )
        ids = [notice.manufacturer_id for notice in feed.notices]
        self.assertEqual(ids, ["UNIT-A", "UNIT-B", "UNIT-A", None, None, "UNIT-A", None])
        self.assertEqual(feed.unattributed_count, 3)
        self.assertEqual(feed.conflict_count, 3)
        self.assertEqual([notice.type_name for notice in feed.notices], ['PET_VISITED'] * 7)
        self.assertEqual([notice.attribution for notice in feed.notices],
                         ['attributed', 'attributed', 'attributed', 'conflict', 'conflict', 'attributed', 'conflict'])
        self.assertEqual(feed.response_count, 7)

    def test_sharing_types_are_counted_and_bodies_are_discarded(self):
        secret = "invitee@example.test"
        feed = self.parse(
            [
                _item(
                    101,
                    parent="UNIT-A",
                    extra={"email": secret, "invitationText": "join me"},
                ),
                _item(106, device="UNIT-B", extra={"userName": "synthetic-person"}),
                _item(20, parent="UNIT-A"),
            ]
        )
        self.assertEqual(feed.response_count, 3)
        self.assertEqual(feed.sharing_discarded_count, 2)
        self.assertEqual(len(feed.notices), 1)
        dumped = json.dumps(feed.notices[0].__dict__, default=str)
        self.assertNotIn(secret, dumped)
        self.assertNotIn("join me", dumped)
        self.assertNotIn("synthetic-person", json.dumps(feed.__dict__, default=str))
        self.assertNotIn("synthetic-user", json.dumps(feed.__dict__, default=str))

    def test_creation_time_parses_only_offset_aware_strings(self):
        aware = self.parse([_item(20, parent="UNIT-A", creation="2026-10-31T15:04:05Z")])
        offset = self.parse(
            [_item(20, parent="UNIT-A", creation="2026-10-31T11:04:05-04:00")]
        )
        compact = self.parse(
            [_item(20, parent="UNIT-A", creation="2026-10-31T11:04:05-0400")]
        )
        naive = self.parse(
            [_item(20, parent="UNIT-A", creation="2026-10-31T15:04:05")]
        )
        missing = self.parse([_item(20, parent="UNIT-A", creation=None)])
        self.assertEqual(
            aware.notices[0].creation_time,
            datetime(2026, 10, 31, 15, 4, 5, tzinfo=timezone.utc),
        )
        self.assertEqual(aware.notices[0].creation_time_raw, "2026-10-31T15:04:05Z")
        self.assertEqual(offset.notices[0].creation_time.utcoffset(), timedelta(hours=-4))
        self.assertEqual(offset.notices[0].creation_time.hour, 11)
        self.assertEqual(compact.notices[0].creation_time.utcoffset(), timedelta(hours=-4))
        self.assertIsNone(naive.notices[0].creation_time)
        self.assertEqual(naive.notices[0].creation_time_raw, "2026-10-31T15:04:05")
        self.assertNotIn("+00:00", naive.notices[0].creation_time_raw)
        self.assertIsNone(missing.notices[0].creation_time)
        self.assertIsNone(missing.notices[0].creation_time_raw)

    def test_empty_list_is_this_response_not_a_complete_history(self):
        feed = self.parse([])
        self.assertEqual(feed.response_count, 0)
        self.assertFalse(feed.complete_history)
        self.assertIsNone(getattr(feed, "has_more", None))
        missing = self.mod.parse_feed({"userId": "synthetic-user"}, KNOWN)
        self.assertIsNone(missing.response_count)
        self.assertNotEqual(missing.response_count, 0)
        self.assertEqual(missing.notifications_shape, "missing")

    def test_invalid_data_increments_unparsed_and_is_not_type_zero(self):
        feed = self.parse(
            [
                {"id": "bad", "creationTime": "2026-10-31T15:04:05Z", "data": "{"},
                {"id": "list", "creationTime": "2026-10-31T15:04:05Z", "data": "[1]"},
                {"id": "obj", "creationTime": "2026-10-31T15:04:05Z", "data": {"type": 24}},
                {"id": "blank", "creationTime": "2026-10-31T15:04:05Z", "data": ""},
                _item(20, parent="UNIT-A"),
            ]
        )
        self.assertEqual(feed.response_count, 5)
        self.assertEqual(feed.unparsed_count, 4)
        self.assertEqual(len(feed.notices), 1)
        self.assertEqual(feed.notices[0].type_code, 20)
        self.assertNotEqual(feed.unparsed_count, 0)
        self.assertFalse(any(notice.type_code == 0 for notice in feed.notices))

    def test_comments_require_a_non_empty_string_and_name_query(self):
        self.assertEqual(self.mod.parse_comments({"comments": "SYNTHETIC notes"}), "SYNTHETIC notes")
        self.assertIsNone(self.mod.parse_comments({"comments": ""}))
        self.assertIsNone(self.mod.parse_comments({"comments": None}))
        self.assertIsNone(self.mod.parse_comments({"comments": 12}))
        self.assertIsNone(self.mod.parse_comments({}))
        self.assertIsNone(self.mod.parse_comments(["comments"]))
        versions = self.mod.versions_in_hand(
            (self.mod.KnownDevice("UNIT-A", "8.7.205R"), self.mod.KnownDevice("UNIT-B", "8.7.205R")),
            self.parse([_item(24, parent="UNIT-A", version="SYNTHETIC-9.9.9")]),
        )
        self.assertEqual(versions, ("8.7.205R", "SYNTHETIC-9.9.9"))
        self.assertNotIn("version", self.mod.notes_query("8.7.205R"))
        self.assertEqual(self.mod.notes_query("8.7.205R"), {"name": "8.7.205R"})

    def test_no_item_is_not_an_announced_version(self):
        feed = self.parse([])
        notice, reason = self.mod.announced_notice(feed, "UNIT-A")
        self.assertIsNone(notice)
        self.assertEqual(reason, "absent")
        self.assertIsNone(self.mod.announced_version(feed, "UNIT-A"))
        other = self.parse([_item(24, parent="UNIT-B", version="SYNTHETIC-9.9.9")])
        self.assertIsNone(self.mod.announced_version(other, "UNIT-A"))
        self.assertEqual(self.mod.announced_version(other, "UNIT-B"), "SYNTHETIC-9.9.9")
        self.assertNotEqual(self.mod.announced_version(other, "UNIT-A"), "8.7.205R")

    def _selected(self, notifications):
        feed = self.parse(notifications)
        notice, reason = self.mod.select_latest(
            notice for notice in feed.notices if notice.manufacturer_id == "UNIT-A"
        )
        announced, announced_reason = self.mod.announced_notice(feed, "UNIT-A")
        return {
            "selection": reason,
            "version": None if notice is None else notice.version,
            "configuration_id": None if notice is None else notice.configuration_id,
            "announced_reason": announced_reason,
            "announced_version": self.mod.announced_version(feed, "UNIT-A"),
            "announced_configuration": None if announced is None else announced.configuration_id,
        }

    def test_equal_aware_time_conflict_is_ambiguous_in_either_order(self):
        clock = "2026-10-31T12:00:00Z"
        same_instant = "2026-10-31T13:00:00+01:00"
        first = _item(24, parent="UNIT-A", creation=clock, version="SYN-A")
        second = _item(24, parent="UNIT-A", creation=clock, version="SYN-B")
        shifted = _item(24, parent="UNIT-A", creation=same_instant, version="10.0.0")
        lower = _item(24, parent="UNIT-A", creation=clock, version="9.0.0")
        forward = self._selected([first, second])
        reverse = self._selected([second, first])
        self.assertEqual(forward, reverse)
        self.assertEqual(forward["selection"], "ambiguous")
        self.assertNotEqual(forward["selection"], "offset_aware_max")
        self.assertEqual(forward["announced_reason"], "ambiguous")
        self.assertIsNone(forward["version"])
        self.assertIsNone(forward["announced_version"])
        self.assertIsNone(forward["configuration_id"])
        self.assertNotIn(forward["announced_version"], {"SYN-A", "SYN-B", "9.0.0", "10.0.0"})
        crossed = self._selected([lower, shifted])
        crossed_reverse = self._selected([shifted, lower])
        self.assertEqual(crossed, crossed_reverse)
        self.assertEqual(crossed["selection"], "ambiguous")
        self.assertIsNone(crossed["announced_version"])

    def test_equal_aware_time_identical_announcement_keeps_that_version(self):
        clock = "2026-10-31T12:00:00Z"
        first = _item(
            24,
            parent="UNIT-A",
            creation=clock,
            version="SYN-A",
            extra={"configurationId": "CFG-1"},
        )
        second = _item(
            24,
            parent="UNIT-A",
            creation=clock,
            version="SYN-A",
            extra={"configurationId": "CFG-1"},
        )
        forward = self._selected([first, second])
        reverse = self._selected([second, first])
        self.assertEqual(forward, reverse)
        self.assertEqual(forward["selection"], "offset_aware_max")
        self.assertEqual(forward["announced_version"], "SYN-A")
        self.assertEqual(forward["announced_configuration"], "CFG-1")

    def test_equal_aware_time_configuration_conflict_is_not_authoritative(self):
        clock = "2026-10-31T12:00:00Z"
        first = _item(
            24,
            parent="UNIT-A",
            creation=clock,
            version="SYN-A",
            extra={"configurationId": "CFG-1"},
        )
        second = _item(
            24,
            parent="UNIT-A",
            creation=clock,
            version="SYN-A",
            extra={"configurationId": "CFG-2"},
        )
        forward = self._selected([first, second])
        reverse = self._selected([second, first])
        self.assertEqual(forward, reverse)
        self.assertEqual(forward["selection"], "ambiguous")
        self.assertIsNone(forward["announced_version"])
        self.assertIsNone(forward["configuration_id"])

    def test_only_the_maximal_aware_time_can_be_ambiguous(self):
        tied = "2026-10-31T12:00:00Z"
        later = "2026-10-31T13:00:00Z"
        older_a = _item(24, parent="UNIT-A", creation=tied, version="SYN-A")
        older_b = _item(24, parent="UNIT-A", creation=tied, version="SYN-B")
        newest = _item(24, parent="UNIT-A", creation=later, version="9.0.0")
        higher_text = _item(24, parent="UNIT-A", creation=tied, version="10.0.0")
        forward = self._selected([older_a, older_b, newest])
        reverse = self._selected([newest, older_b, older_a])
        self.assertEqual(forward, reverse)
        self.assertEqual(forward["selection"], "offset_aware_max")
        self.assertEqual(forward["announced_version"], "9.0.0")
        by_time = self._selected([higher_text, newest])
        by_time_reverse = self._selected([newest, higher_text])
        self.assertEqual(by_time, by_time_reverse)
        self.assertEqual(by_time["announced_version"], "9.0.0")
        self.assertNotEqual(by_time["announced_version"], "10.0.0")

    def test_naive_and_mixed_clocks_do_not_invent_version_precedence(self):
        naive_low = _item(24, parent="UNIT-A", creation="2026-10-31T12:00:00", version="9.0.0")
        naive_high = _item(24, parent="UNIT-A", creation="2026-10-31T12:00:00", version="10.0.0")
        aware = _item(24, parent="UNIT-A", creation="2026-10-31T12:00:00Z", version="9.0.0")
        for order in ([naive_low, naive_high], [naive_high, naive_low]):
            selected = self._selected(order)
            self.assertEqual(selected["selection"], "response_order")
            self.assertNotEqual(selected["selection"], "offset_aware_max")
            self.assertIsNotNone(selected["version"])
        mixed = self._selected([naive_high, aware])
        mixed_reverse = self._selected([aware, naive_high])
        self.assertEqual(mixed, mixed_reverse)
        self.assertEqual(mixed["selection"], "offset_aware_max")
        self.assertEqual(mixed["announced_version"], "9.0.0")
        self.assertNotEqual(mixed["announced_version"], "10.0.0")

    def test_latest_notification_selection_follows_the_same_ambiguity(self):
        clock = "2026-10-31T12:00:00Z"
        visited = _item(20, parent="UNIT-A", creation=clock)
        message = _item(21, parent="UNIT-A", creation=clock)
        repeated = _item(20, parent="UNIT-A", creation=clock)

        def latest(order):
            feed = self.parse(order)
            notice, reason = self.mod.select_latest(
                item for item in feed.notices if item.manufacturer_id == "UNIT-A"
            )
            return (
                reason,
                None if notice is None else notice.type_code,
                None if notice is None else notice.type_name,
            )

        conflict = latest([visited, message])
        reverse = latest([message, visited])
        self.assertEqual(conflict, reverse)
        self.assertEqual(conflict, ("ambiguous", None, None))
        identical = latest([visited, repeated])
        identical_reverse = latest([repeated, visited])
        self.assertEqual(identical, identical_reverse)
        self.assertEqual(identical, ("offset_aware_max", 20, "PET_VISITED"))

    def test_latest_prefers_offset_aware_time_and_does_not_use_host_zone(self):
        older = _item(20, parent="UNIT-A", creation="2026-10-31T15:00:00Z")
        newer = _item(21, parent="UNIT-A", creation="2026-10-31T16:00:00+00:00")
        naive = _item(22, parent="UNIT-A", creation="2026-10-31T23:59:59")
        feed = self.parse([older, naive, newer])
        notice, reason = self.mod.select_latest(
            [item for item in feed.notices if item.manufacturer_id == "UNIT-A"]
        )
        self.assertEqual(reason, "offset_aware_max")
        self.assertEqual(notice.type_code, 21)
        self.assertNotEqual(notice.type_code, 22)
        only_naive = self.parse([naive])
        selected, fallback = self.mod.select_latest(list(only_naive.notices))
        self.assertEqual(fallback, "response_order")
        self.assertEqual(selected.type_code, 22)
        self.assertIsNone(selected.creation_time)

    def test_module_has_no_write_or_pydantic_notification_model(self):
        text = PARSER_PATH.read_text(encoding="utf-8")
        self.assertNotIn("NotificationList", text)
        self.assertNotIn("NotificationData", text)
        self.assertNotIn("get_notifications", text)
        self.assertNotIn("get_firmware_info", text)
        self.assertNotIn("get_notification_settings", text)
        self.assertNotIn("UpdateEntity", text)
        self.assertNotIn("push/settings", text)
        self.assertNotIn("forUserByType", text)
        self.assertNotIn("approve", text.lower())
        self.assertIn("not a vendor limit", text)
        self.assertGreater(
            self.mod.READ_INFORMATION_INTERVAL, timedelta(minutes=15)
        )


class ReadInformationHaContractTests(unittest.TestCase):
    def test_real_ha_startup_entity_and_coordinator_contract(self):
        from tests.process_harness import require_dependencies
        require_dependencies(self, "homeassistant.core", "catgenie")
        self.assertTrue(HA_CONTRACT.is_file(), HA_CONTRACT)
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            [str(ROOT), env.get("CATGENIE_TEST_DEPENDENCY", ""), env.get("PYTHONPATH", "")]
        )
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["CATGENIE_READ_INFORMATION_ROOT"] = str(ROOT)
        completed = subprocess.run(
            [sys.executable, "-B", str(HA_CONTRACT)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )
        self.assertIn("HA_CONTRACT_OK", completed.stdout)
        self.assertIn("STARTUP_LOADED", completed.stdout)
        self.assertIn("ENTITIES_REGISTERED", completed.stdout)
        self.assertIn("COORDINATOR_ISOLATED", completed.stdout)
        self.assertIn("AMBIGUOUS_SELECTION_NOT_AUTHORITATIVE", completed.stdout)
        self.assertIn("FIRMWARE_CHANGE_DROPPED_OLD_NOTES", completed.stdout)
        self.assertIn("DEVICE_LISTENER_REMOVED", completed.stdout)
        self.assertNotIn("up_to_date", completed.stdout)


if __name__ == "__main__":
    unittest.main()
