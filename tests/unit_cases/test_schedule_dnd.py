"""Schedule and DND contract tests. Synthetic clocks only; no device writes."""
from __future__ import annotations

import ast
import importlib.util
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "custom_components" / "catgenie"
MODULE_PATH = COMPONENT / "schedule.py"

OBSERVED_WIRE = [
    "05:00:00",
    "08:00:00",
    "11:00:00",
    "14:00:00",
    "17:00:00",
    "20:00:00",
    "23:00:00",
    "02:00:00",
]
EDT_DAY = date(2026, 10, 31)
EST_DAY = date(2026, 11, 2)
SPRING_GAP = date(2026, 3, 8)
FALL_OVERLAP = date(2026, 11, 1)


def load_schedule():
    spec = importlib.util.spec_from_file_location(
        "catgenie_schedule_contract", MODULE_PATH
    )
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ScheduleContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from zoneinfo import ZoneInfo

        cls.schedule = load_schedule()
        cls.ny = ZoneInfo("America/New_York")

    def test_module_does_not_import_home_assistant_or_the_client(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"), filename="schedule.py")
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertTrue(imported.isdisjoint({
            "homeassistant", "catgenie", "aiohttp", "curl_cffi", "requests", "socket",
        }))

    def test_no_writable_service_is_registered(self):
        init_tree = ast.parse((COMPONENT / "__init__.py").read_text(encoding="utf-8"))
        platforms = []
        for node in ast.walk(init_tree):
            if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
                continue
            if node.target.id != "PLATFORMS" or not isinstance(node.value, ast.List):
                continue
            platforms = [
                elt.attr.lower()
                for elt in node.value.elts
                if isinstance(elt, ast.Attribute)
            ]
        self.assertTrue({"binary_sensor", "button", "sensor", "switch"}.issubset(platforms))
        # Other feature tracks may register number/select controls. This guard
        # only forbids a schedule/DND time-control platform in this slice.
        self.assertNotIn("time", platforms)
        sensor_tree = ast.parse((COMPONENT / "sensor.py").read_text(encoding="utf-8"))
        keys = [
            keyword.value.value
            for node in ast.walk(sensor_tree)
            if isinstance(node, ast.Call)
            for keyword in node.keywords
            if keyword.arg == "key" and isinstance(keyword.value, ast.Constant)
        ]
        self.assertIn("scheduled_cycles", keys)
        self.assertNotIn("schedule_editor", keys)
        self.assertNotIn("dnd_window", keys)
        self.assertEqual(self.schedule.WRITABLE_HA_SERVICES, ("set_schedule", "set_do_not_disturb"))

    def test_local_to_utc_uses_explicit_zone_not_reported_offset(self):
        convert = self.schedule.local_time_to_utc_time
        self.assertEqual(convert("12:00:00", self.ny, EDT_DAY), "16:00:00")
        self.assertEqual(convert("00:00:00", self.ny, EDT_DAY), "04:00:00")
        self.assertEqual(convert("22:00:00", self.ny, EDT_DAY), "02:00:00")
        self.assertEqual(convert("05:00:00", self.ny, EDT_DAY), "09:00:00")
        self.assertEqual(convert("12:00:00", self.ny, EST_DAY), "17:00:00")
        self.assertNotEqual(convert("12:00:00", self.ny, EDT_DAY), "17:00:00")

    def test_raw_offset_and_fixed_timezone_are_rejected(self):
        with self.assertRaises(self.schedule.ScheduleContractError) as caught:
            self.schedule.local_time_to_utc_time("12:00:00", "-05:00", EDT_DAY)
        self.assertEqual(caught.exception.code, "offset_is_not_a_zone")
        with self.assertRaises(self.schedule.ScheduleContractError) as caught:
            self.schedule.local_time_to_utc_time(
                "12:00:00", timezone(timedelta(hours=-5)), EDT_DAY
            )
        self.assertEqual(caught.exception.code, "offset_is_not_a_zone")

    def test_reference_date_is_required_and_not_a_datetime(self):
        with self.assertRaises(TypeError):
            self.schedule.local_time_to_utc_time("12:00:00", self.ny)
        with self.assertRaises(self.schedule.ScheduleContractError) as caught:
            self.schedule.local_time_to_utc_time(
                "12:00:00", self.ny, datetime(2026, 10, 31, 12, 0)
            )
        self.assertEqual(caught.exception.code, "reference_date_required")

    def test_utc_to_local_matches_app_display_direction(self):
        convert = self.schedule.utc_time_to_local_time
        self.assertEqual(convert("05:00:00", self.ny, EDT_DAY), "01:00:00")
        self.assertEqual(convert("04:00:00", self.ny, EDT_DAY), "00:00:00")
        self.assertEqual(convert("02:00:00", self.ny, date(2026, 11, 1)), "22:00:00")
        round_trip = self.schedule.local_time_to_utc_time(
            convert("14:00:00", self.ny, EDT_DAY), self.ny, EDT_DAY
        )
        self.assertEqual(round_trip, "14:00:00")

    def test_spring_gap_is_not_rewritten(self):
        with self.assertRaises(self.schedule.ScheduleContractError) as caught:
            self.schedule.local_time_to_utc_time("02:30:00", self.ny, SPRING_GAP)
        self.assertEqual(caught.exception.code, "nonexistent_local_time")
        self.assertNotIn("03:30:00", str(caught.exception))
        self.assertEqual(
            self.schedule.local_time_to_utc_time("01:30:00", self.ny, SPRING_GAP),
            "06:30:00",
        )
        self.assertEqual(
            self.schedule.local_time_to_utc_time("03:30:00", self.ny, SPRING_GAP),
            "07:30:00",
        )

    def test_fall_overlap_is_not_folded(self):
        with self.assertRaises(self.schedule.ScheduleContractError) as caught:
            self.schedule.local_time_to_utc_time("01:30:00", self.ny, FALL_OVERLAP)
        self.assertEqual(caught.exception.code, "ambiguous_local_time")
        self.assertEqual(
            self.schedule.utc_time_to_local_time("05:30:00", self.ny, FALL_OVERLAP),
            "01:30:00",
        )
        self.assertEqual(
            self.schedule.utc_time_to_local_time("06:30:00", self.ny, FALL_OVERLAP),
            "01:30:00",
        )
        displayed = self.schedule.utc_time_to_local_detail(
            "05:30:00", self.ny, FALL_OVERLAP
        )
        self.assertTrue(displayed["ambiguous_local_clock"])
        self.assertEqual(displayed["local_clock"], "01:30:00")

    def test_invalid_clocks_are_rejected(self):
        for value in ("5:00:00", "05:00", "24:00:00", "05:60:00", "05:00:60",
                      "05:00:00.0", " 05:00:00", "", None, {"hour": 5}):
            with self.subTest(value=value):
                with self.assertRaises(self.schedule.ScheduleContractError) as caught:
                    self.schedule.parse_wire_clock(value)
                self.assertEqual(caught.exception.code, "invalid_clock")

    def test_display_preserves_wire_list_and_ignores_reported_offset(self):
        original = list(OBSERVED_WIRE)
        view = self.schedule.display_schedule(
            original,
            zone=self.ny,
            on_date=EDT_DAY,
            reported_offset="-05:00",
        )
        self.assertEqual(original, OBSERVED_WIRE)
        self.assertEqual(view["wire_times"], OBSERVED_WIRE)
        self.assertEqual(view["local_clocks"][0], "01:00:00")
        self.assertNotEqual(view["local_clocks"][0], "00:00:00")
        self.assertNotEqual(view["local_clocks"][0], "05:00:00")
        self.assertFalse(view["reported_offset_applied"])
        self.assertTrue(view["reported_offset_disagrees_with_zone"])
        self.assertFalse(view["device_storage_verified"])
        self.assertEqual(view["basis"], "app_display_utc_to_local")
        self.assertEqual(view["zone"], "America/New_York")

    def test_display_sort_does_not_become_write_order(self):
        wire = ["23:00:00", "02:00:00", "11:00:00"]
        view = self.schedule.display_schedule(wire, zone=self.ny, on_date=EDT_DAY)
        self.assertEqual(view["wire_times"], wire)
        self.assertNotEqual(view["sorted_local_clocks"], view["local_clocks"])
        self.assertEqual(
            view["sorted_local_clocks"],
            sorted(view["local_clocks"], key=self.schedule.string_time_to_seconds),
        )

    def test_empty_dnd_is_display_cleared_not_proven_disabled(self):
        for start, end in (("", ""), ("", "02:00:00"), ("05:00:00", "05:00:00")):
            with self.subTest(start=start, end=end):
                view = self.schedule.display_dnd(
                    start, end, zone=self.ny, on_date=EDT_DAY, cat_delay=1800
                )
                self.assertEqual(view["status"], "display_cleared")
                self.assertFalse(view["disable_encoding_verified"])
                self.assertNotEqual(view["status"], "disabled")
                self.assertIsNone(view["window"])
                self.assertEqual(view["cat_delay"], 1800)

    def test_dnd_window_is_one_object_and_crosses_midnight(self):
        view = self.schedule.display_dnd(
            "02:00:00",
            "06:00:00",
            zone=self.ny,
            on_date=EDT_DAY,
            reported_offset="-05:00",
            cat_delay=1800,
        )
        self.assertEqual(view["status"], "display_active")
        self.assertEqual(set(view["window"]), {"from", "to", "duration_minutes"})
        self.assertEqual(view["window"]["duration_minutes"], 240)
        self.assertLessEqual(view["window"]["duration_minutes"], 600)
        self.assertFalse(view["app_ui_exceeds_ten_hours"])
        self.assertIn("cat_delay", view)
        self.assertNotIn("from_entity", view)
        self.assertNotIn("to_entity", view)

    def test_library_schedule_dicts_are_rejected(self):
        with self.assertRaises(self.schedule.ScheduleContractError) as caught:
            self.schedule.prepare_schedule_configuration(
                [{"day": 0, "hour": 5, "minute": 0, "enabled": True}],
                zone=self.ny,
                on_date=EDT_DAY,
                existing_wire=OBSERVED_WIRE,
            )
        self.assertEqual(caught.exception.code, "library_schedule_shape")

    def test_schedule_replace_preserves_length_order_and_excludes_other_fields(self):
        local = [
            "01:00:00",
            "04:00:00",
            "07:00:00",
            "10:00:00",
            "13:00:00",
            "16:00:00",
            "19:00:00",
            "22:00:00",
        ]
        prepared = self.schedule.prepare_schedule_configuration(
            local,
            zone=self.ny,
            on_date=EDT_DAY,
            existing_wire=OBSERVED_WIRE,
        )
        self.assertEqual(set(prepared.configuration), {"schedule"})
        self.assertEqual(prepared.configuration["schedule"], OBSERVED_WIRE)
        self.assertFalse(prepared.sendable)
        self.assertFalse(prepared.registered_ha_service)
        self.assertIn("live_put_not_verified", prepared.blockers)
        self.assertIn("partial_configuration_put_preservation_not_verified", prepared.blockers)
        with self.assertRaises(self.schedule.ScheduleContractError) as caught:
            self.schedule.prepare_schedule_configuration(
                local[:7],
                zone=self.ny,
                on_date=EDT_DAY,
                existing_wire=OBSERVED_WIRE,
            )
        self.assertEqual(caught.exception.code, "schedule_length_mismatch")

    def test_dst_gap_blocks_the_whole_schedule_payload(self):
        local = ["01:30:00"] * 7 + ["02:30:00"]
        with self.assertRaises(self.schedule.ScheduleContractError) as caught:
            self.schedule.prepare_schedule_configuration(
                local,
                zone=self.ny,
                on_date=SPRING_GAP,
                existing_wire=OBSERVED_WIRE,
            )
        self.assertEqual(caught.exception.code, "nonexistent_local_time")
        self.assertFalse(hasattr(caught.exception, "configuration"))

    def test_dnd_prepare_keeps_cat_delay_and_is_not_sendable(self):
        prepared = self.schedule.prepare_dnd_configuration(
            local_from="22:00:00",
            local_to="02:00:00",
            cat_delay=1800,
            zone=self.ny,
            on_date=EDT_DAY,
        )
        self.assertEqual(
            prepared.configuration,
            {"dndFrom": "02:00:00", "dndTo": "06:00:00", "catDelay": 1800},
        )
        self.assertEqual(
            set(prepared.configuration), {"dndFrom", "dndTo", "catDelay"}
        )
        self.assertFalse(prepared.sendable)
        self.assertFalse(prepared.registered_ha_service)
        self.assertIn("live_put_not_verified", prepared.blockers)
        params = self.schedule.app_configuration_params("unit-1", prepared.configuration)
        self.assertEqual(set(params), {"manufacturerId", "configuration"})
        self.assertNotIn("schedule", params["configuration"])
        self.assertNotIn("mode", params["configuration"])

    def test_dnd_rejects_missing_delay_same_time_over_ten_hours_and_disable(self):
        with self.assertRaises(self.schedule.ScheduleContractError) as caught:
            self.schedule.prepare_dnd_configuration(
                local_from="22:00:00",
                local_to="02:00:00",
                cat_delay=None,
                zone=self.ny,
                on_date=EDT_DAY,
            )
        self.assertEqual(caught.exception.code, "dnd_requires_cat_delay")
        with self.assertRaises(self.schedule.ScheduleContractError) as caught:
            self.schedule.prepare_dnd_configuration(
                local_from="08:00:00",
                local_to="08:00:00",
                cat_delay=1800,
                zone=self.ny,
                on_date=EDT_DAY,
            )
        self.assertEqual(caught.exception.code, "dnd_same_endpoint")
        with self.assertRaises(self.schedule.ScheduleContractError) as caught:
            self.schedule.prepare_dnd_configuration(
                local_from="08:00:00",
                local_to="18:00:01",
                cat_delay=1800,
                zone=self.ny,
                on_date=EDT_DAY,
            )
        self.assertEqual(caught.exception.code, "dnd_app_ui_over_ten_hours")
        self.assertIn("not a server limit", str(caught.exception))
        prepared = self.schedule.prepare_dnd_configuration(
            local_from="08:00:00",
            local_to="18:00:00",
            cat_delay=1800,
            zone=self.ny,
            on_date=EDT_DAY,
        )
        self.assertEqual(prepared.configuration["catDelay"], 1800)
        self.assertFalse(prepared.sendable)
        with self.assertRaises(self.schedule.ScheduleContractError) as caught:
            self.schedule.prepare_dnd_disable(cat_delay=1800)
        self.assertEqual(caught.exception.code, "dnd_disable_encoding_unverified")
        self.assertFalse(hasattr(caught.exception, "configuration"))

    def test_bool_and_unknown_delay_are_not_invented(self):
        with self.assertRaises(self.schedule.ScheduleContractError) as caught:
            self.schedule.prepare_dnd_configuration(
                local_from="22:00:00",
                local_to="02:00:00",
                cat_delay=True,
                zone=self.ny,
                on_date=EDT_DAY,
            )
        self.assertEqual(caught.exception.code, "dnd_cat_delay_not_integer")
        self.assertFalse(hasattr(self.schedule, "DEFAULT_CAT_DELAY"))

    def test_empty_schedule_is_not_a_proven_disable(self):
        with self.assertRaises(self.schedule.ScheduleContractError) as caught:
            self.schedule.prepare_schedule_configuration(
                [],
                zone=self.ny,
                on_date=EDT_DAY,
                existing_wire=[],
            )
        self.assertEqual(caught.exception.code, "schedule_empty_disable_unverified")
        self.assertFalse(hasattr(caught.exception, "configuration"))
        with self.assertRaises(self.schedule.ScheduleContractError) as caught:
            self.schedule.prepare_schedule_disable()
        self.assertEqual(caught.exception.code, "schedule_empty_disable_unverified")

    def test_list_edit_must_not_activate_time_cleaning_or_register_a_service(self):
        hold = self.schedule.schedule_editor_hold()
        self.assertFalse(hold["sendable"])
        self.assertFalse(hold["registered_ha_service"])
        self.assertFalse(hold["native_list_entity"])
        self.assertEqual(self.schedule.WRITABLE_HA_SERVICES, ("set_schedule", "set_do_not_disturb"))
        self.assertEqual(
            hold["http"]["path_template"],
            "device/management/{manufacturerId}/configuration",
        )
        self.assertEqual(hold["http"]["method"], "PUT")
        self.assertEqual(hold["http"]["edit_body_keys"], ("schedule",))
        self.assertEqual(hold["http"]["forbidden_on_list_edit"], ("mode", "manual"))
        self.assertIn("owner_schedule_readback_required", hold["blockers"])
        self.assertIn("America/New_York", hold["observation"])
        self.assertIn("mode", hold["observation"])
        with self.assertRaises(self.schedule.ScheduleContractError) as caught:
            self.schedule.reject_time_cleaning_activation(
                {"schedule": ["16:00:00"], "mode": 1, "manual": 0}
            )
        self.assertEqual(
            caught.exception.code, "schedule_edit_must_not_activate_time_cleaning"
        )
        self.assertFalse(hasattr(caught.exception, "configuration"))
