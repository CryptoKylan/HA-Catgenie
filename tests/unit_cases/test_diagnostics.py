"""Registered read-only diagnostics. Synthetic payloads only.

Cartridge type uses the app TAG_TYPE enum. Timezone and DND are reported
strings. Schedule local display stays on hold: the existing helper needs an
explicit IANA zone, and the reported offset is not that zone.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch as mock_patch

import tests.unit_cases.test_unknown_operation_state as harness

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "custom_components" / "catgenie"
FORBIDDEN_ATTR_KEYS = {
    "token",
    "refresh_token",
    "phone",
    "serial",
    "serial_number",
    "mac",
    "mac_address",
    "pet",
    "pet_name",
    "account",
    "password",
}


class RegisteredDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dependency = os.environ.get("CATGENIE_TEST_DEPENDENCY")
        paths = [str(harness.CANDIDATE), *([dependency] if dependency else []), *sys.path]
        with mock_patch.dict(sys.modules), mock_patch.object(sys, "path", paths):
            for name in tuple(sys.modules):
                if name == "custom_components" or name.startswith("custom_components.catgenie"):
                    del sys.modules[name]
            harness._install_import_seams()
            from custom_components.catgenie.client import _normalize_thing
            from custom_components.catgenie.reported_config import (
                SCHEDULE_DISPLAY_HOLD,
                cartridge_type_attributes,
                cartridge_type_value,
                reported_dnd_attributes,
                reported_dnd_value,
                reported_timezone_attributes,
                reported_timezone_value,
            )
            from custom_components.catgenie.sensor import SENSORS, CatGenieSensor
        cls.normalize = staticmethod(_normalize_thing)
        cls.hold = SCHEDULE_DISPLAY_HOLD
        cls.cartridge_type_value = staticmethod(cartridge_type_value)
        cls.cartridge_type_attributes = staticmethod(cartridge_type_attributes)
        cls.reported_timezone_value = staticmethod(reported_timezone_value)
        cls.reported_timezone_attributes = staticmethod(reported_timezone_attributes)
        cls.reported_dnd_value = staticmethod(reported_dnd_value)
        cls.reported_dnd_attributes = staticmethod(reported_dnd_attributes)
        cls.sensors = SENSORS
        cls.sensor_cls = CatGenieSensor
        cls.device_cls = harness.TolerantDevice

    def sensor_description(self, key):
        return next(item for item in self.sensors if item.key == key)

    def device(self, manufacturer_id="diag", **fields):
        payload = harness.thing(manufacturer_id, 0, progress=255)
        payload.update(fields)
        return self.device_cls.model_validate(self.normalize(payload))

    def entity(self, model, key):
        return self.sensor_cls(
            harness._Coordinator({model.manufacturer_id: model}),
            model.manufacturer_id,
            self.sensor_description(key),
        )

    def test_reported_timezone_state_length_boundary(self):
        for length in (255, 256):
            with self.subTest(length=length):
                text = "X" * length
                sensor = self.entity(self.device(configuration={"timezone": text}), "reported_timezone")
                self.assertEqual(sensor.native_value, text if length == 255 else None)
                self.assertEqual(sensor.extra_state_attributes["reported_timezone"], text)

    def test_cartridge_type_uses_app_enum_through_the_sensor_callback(self):
        expected = {0: "missing", 1: "regular", 3: "maintenance"}
        for tag, label in expected.items():
            with self.subTest(tag=tag):
                model = self.device(tagType=tag, configuration={"mode": 0, "manual": 0})
                sensor = self.entity(model, "cartridge_type")
                self.assertEqual(sensor.native_value, label)
                self.assertEqual(sensor.native_value, self.cartridge_type_value(model))
                attrs = sensor.extra_state_attributes
                self.assertIsNotNone(attrs)
                self.assertEqual(attrs["tag_type"], tag)
                self.assertNotIn("normal", attrs.values())

    def test_unknown_cartridge_code_stays_unknown_with_raw_attr(self):
        for tag in (2, 4, 99, -1):
            with self.subTest(tag=tag):
                sensor = self.entity(self.device(tagType=tag), "cartridge_type")
                self.assertEqual(sensor.native_value, "unknown")
                attrs = sensor.extra_state_attributes
                self.assertIsNotNone(attrs)
                self.assertEqual(attrs["raw_tag_type"], tag)
                self.assertNotEqual(sensor.native_value, "normal")
                self.assertNotEqual(sensor.native_value, "regular")

    def test_absent_or_mistyped_tag_is_not_missing_cartridge_zero(self):
        absent = self.device()
        self.assertIsNone(self.entity(absent, "cartridge_type").native_value)
        absent_attrs = self.cartridge_type_attributes(absent)
        self.assertFalse(absent_attrs["tag_type_present"])
        self.assertNotIn("raw_tag_type", absent_attrs)
        self.assertNotIn("tag_type", absent_attrs)
        for tag in (True, False, 1.0, 0.0, "1", "0", None):
            with self.subTest(tag=tag):
                sensor = self.entity(self.device(tagType=tag), "cartridge_type")
                self.assertIsNone(sensor.native_value)
                attrs = sensor.extra_state_attributes
                self.assertIsNotNone(attrs)
                self.assertEqual(attrs["raw_tag_type"], tag)
                self.assertNotEqual(sensor.native_value, "regular")
                self.assertNotEqual(sensor.native_value, "missing")

    def test_reported_timezone_is_raw_metadata_not_a_zone_or_dst_claim(self):
        model = self.device(
            configuration={"timezone": "-05:00", "dstFrom": "03-08", "dstTo": "11-01"}
        )
        sensor = self.entity(model, "reported_timezone")
        self.assertEqual(sensor.native_value, "-05:00")
        self.assertEqual(sensor.native_value, self.reported_timezone_value(model))
        attrs = sensor.extra_state_attributes
        self.assertEqual(attrs, self.reported_timezone_attributes(model))
        self.assertFalse(attrs["ha_zone_applied"])
        self.assertFalse(attrs["dst_claimed"])
        self.assertFalse(attrs["offset_trusted_for_schedule_conversion"])
        self.assertEqual(attrs["raw_dst_from"], "03-08")
        self.assertEqual(attrs["raw_dst_to"], "11-01")
        self.assertEqual(attrs["dst_semantics"], "unverified")
        self.assertNotIn("is_dst", attrs)
        self.assertNotIn("dst_active", attrs)
        self.assertNotIn("America/Toronto", str(attrs))
        self.assertNotIn("America/New_York", str(attrs))

    def test_omitted_timezone_does_not_publish_the_pydantic_default(self):
        omitted = self.device()
        empty = self.device(configuration={})
        explicit = self.device(configuration={"timezone": "+00:00"})
        blank = self.device(configuration={"timezone": ""})
        self.assertEqual(omitted.configuration.timezone, "+00:00")
        self.assertIsNone(self.entity(omitted, "reported_timezone").native_value)
        self.assertIsNone(self.entity(empty, "reported_timezone").native_value)
        empty_attrs = self.entity(empty, "reported_timezone").extra_state_attributes
        self.assertIsNotNone(empty_attrs)
        self.assertFalse(empty_attrs["timezone_present"])
        self.assertEqual(self.entity(explicit, "reported_timezone").native_value, "+00:00")
        self.assertIsNone(self.entity(blank, "reported_timezone").native_value)
        blank_attrs = self.entity(blank, "reported_timezone").extra_state_attributes
        self.assertIsNotNone(blank_attrs)
        self.assertEqual(blank_attrs["raw_timezone"], "")

    def test_dnd_empty_or_equal_is_reported_not_set_and_not_disabled(self):
        for start, end in (("", ""), ("", "02:00:00"), ("05:00:00", "05:00:00")):
            with self.subTest(start=start, end=end):
                model = self.device(
                    configuration={"dndFrom": start, "dndTo": end, "timezone": "-05:00"}
                )
                sensor = self.entity(model, "reported_dnd")
                self.assertEqual(sensor.native_value, "not set")
                self.assertEqual(sensor.native_value, self.reported_dnd_value(model))
                attrs = sensor.extra_state_attributes
                self.assertIsNotNone(attrs)
                self.assertEqual(attrs["reported_from"], start)
                self.assertEqual(attrs["reported_to"], end)
                self.assertFalse(attrs["disable_encoding_verified"])
                self.assertFalse(attrs["converted"])
                self.assertFalse(attrs["reported_offset_applied"])
                self.assertNotEqual(attrs.get("status"), "disabled")
                self.assertNotIn("disabled", str(sensor.native_value))
                self.assertNotIn("clock_entries", attrs)

    def test_dnd_clocks_stay_reported_and_are_not_converted_with_the_offset(self):
        model = self.device(
            configuration={
                "dndFrom": "22:00:00",
                "dndTo": "02:00:00",
                "timezone": "-05:00",
                "catDelay": 1800,
            }
        )
        sensor = self.entity(model, "reported_dnd")
        self.assertEqual(sensor.native_value, "22:00:00 to 02:00:00")
        attrs = sensor.extra_state_attributes
        self.assertIsNotNone(attrs)
        self.assertEqual(attrs["clock_entries"], ["22:00:00", "02:00:00"])
        self.assertEqual(attrs["basis"], "reported_configuration_string")
        self.assertEqual(attrs["clock_basis"], "unverified")
        self.assertFalse(attrs["converted"])
        self.assertFalse(attrs["reported_offset_applied"])
        self.assertNotIn("17:00:00", str(attrs))
        self.assertNotIn("21:00:00", str(attrs))
        self.assertNotIn("duration_minutes", attrs)
        self.assertNotIn("cat_delay", attrs)
        self.assertNotIn("local_clock", attrs)

    def test_absent_or_invalid_dnd_is_unknown_not_an_empty_window(self):
        self.assertIsNone(self.entity(self.device(), "reported_dnd").native_value)
        self.assertIsNone(
            self.entity(
                self.device(configuration={"timezone": "-05:00"}), "reported_dnd"
            ).native_value
        )
        one_sided = self.device(configuration={"dndFrom": "22:00:00"})
        self.assertIsNone(self.entity(one_sided, "reported_dnd").native_value)
        invalid = self.device(configuration={"dndFrom": "22:00", "dndTo": "02:00:00"})
        sensor = self.entity(invalid, "reported_dnd")
        self.assertIsNone(sensor.native_value)
        attrs = sensor.extra_state_attributes
        self.assertIsNotNone(attrs)
        self.assertEqual(attrs["raw_dnd_from"], "22:00")
        self.assertEqual(attrs["raw_dnd_to"], "02:00:00")
        self.assertNotIn("clock_entries", attrs)

    def test_schedule_local_display_is_an_explicit_hold(self):
        self.assertEqual(self.hold["status"], "hold")
        self.assertIn("unverified", self.hold["reason"])
        self.assertIn("reported UTC offset", self.hold["reason"])
        self.assertNotIn("-05:00", self.hold["reason"])
        keys = {item.key for item in self.sensors}
        self.assertIn("scheduled_cycles", keys)
        self.assertTrue(
            keys.isdisjoint(
                {
                    "schedule_editor",
                    "schedule_display",
                    "reported_schedule",
                    "dnd_window",
                    "dnd_from",
                    "dnd_to",
                }
            )
        )
        model = self.device(
            configuration={
                "schedule": ["05:00:00", "08:00:00"],
                "timezone": "-05:00",
            }
        )
        cycles = self.entity(model, "scheduled_cycles")
        self.assertEqual(cycles.native_value, 2)
        entries = cycles.extra_state_attributes["entries"]
        self.assertEqual(entries[0]["time"], "05:00:00")
        self.assertNotEqual(entries[0]["time"], "00:00:00")
        self.assertNotEqual(entries[0]["time"], "01:00:00")

    def test_existing_capacity_remaining_and_raw_progress_stay_unchanged(self):
        model = self.device(
            tagType=1,
            remainingSaniSolution=160,
            configuration={"mode": 0, "manual": 0},
        )
        self.assertEqual(self.entity(model, "cartridge_capacity").native_value, 240)
        self.assertEqual(self.entity(model, "cartridge_remaining").native_value, 160)
        self.assertEqual(self.entity(model, "operation_progress").native_value, 0)
        self.assertIsNone(model.operation_status.clean_progress_pct)
        manual = self.device(
            tagType=1,
            remainingSaniSolution=80,
            configuration={"mode": 0, "manual": 1},
        )
        self.assertEqual(self.entity(manual, "cartridge_capacity").native_value, 120)
        self.assertEqual(self.entity(manual, "cartridge_remaining").native_value, 80)

    def test_diagnostics_are_diagnostic_strings_without_units_or_secrets(self):
        translation = json.loads((COMPONENT / "translations" / "en.json").read_text())
        sensor_copy = translation["entity"]["sensor"]
        for key in ("cartridge_type", "reported_timezone", "reported_dnd"):
            description = self.sensor_description(key)
            self.assertEqual(description.entity_category, "diagnostic")
            self.assertIsNone(description.native_unit_of_measurement)
            self.assertIn(key, sensor_copy)
            self.assertNotIn("normal", json.dumps(sensor_copy[key]).lower())
        cartridge = self.sensor_description("cartridge_type")
        self.assertEqual(
            cartridge.options, ["missing", "regular", "maintenance", "unknown"]
        )
        self.assertNotIn("normal", cartridge.options)
        model = self.device(
            tagType=1,
            configuration={
                "timezone": "-05:00",
                "dndFrom": "22:00:00",
                "dndTo": "02:00:00",
            },
        )
        for key in ("cartridge_type", "reported_timezone", "reported_dnd"):
            attrs = self.entity(model, key).extra_state_attributes
            self.assertIsNotNone(attrs)
            self.assertTrue(FORBIDDEN_ATTR_KEYS.isdisjoint(attrs))
            self.assertNotIn("aa:bb:cc:dd:ee:ff", str(attrs).lower())

    def test_availability_matches_the_existing_device_presence_rule(self):
        online = self.device(tagType=1, configuration={"timezone": "-05:00"})
        offline_payload = harness.thing("offline", 0, progress=255)
        offline_payload.update(tagType=1, reportedStatus="disconnected")
        offline = self.device_cls.model_validate(self.normalize(offline_payload))
        coordinator = harness._Coordinator(
            {
                online.manufacturer_id: online,
                offline.manufacturer_id: offline,
            }
        )
        for key in ("cartridge_type", "reported_timezone", "volume_level"):
            with self.subTest(key=key):
                present = self.sensor_cls(
                    coordinator, online.manufacturer_id, self.sensor_description(key)
                )
                disconnected = self.sensor_cls(
                    coordinator, offline.manufacturer_id, self.sensor_description(key)
                )
                self.assertTrue(present.available)
                self.assertTrue(disconnected.available)
                del coordinator.data[online.manufacturer_id]
                self.assertFalse(present.available)
                coordinator.data[online.manufacturer_id] = online

    def test_callbacks_do_not_poll_or_prepare_a_write(self):
        tree = ast.parse((COMPONENT / "reported_config.py").read_text(encoding="utf-8"))
        imported = set()
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
        self.assertTrue(imported.isdisjoint({"homeassistant", "curl_cffi", "aiohttp"}))
        self.assertTrue(
            names.isdisjoint(
                {
                    "get_devices",
                    "_request",
                    "update_configuration",
                    "display_schedule",
                    "display_dnd",
                    "prepare_schedule_configuration",
                    "prepare_dnd_configuration",
                }
            )
        )
        self.assertIn("parse_wire_clock", names)

    def test_unique_ids_follow_the_existing_sensor_pattern(self):
        model = self.device(
            tagType=3,
            configuration={"timezone": "-05:00", "dndFrom": "", "dndTo": ""},
        )
        self.assertEqual(
            self.entity(model, "cartridge_type")._attr_unique_id, "diag_cartridge_type"
        )
        self.assertEqual(
            self.entity(model, "reported_timezone")._attr_unique_id,
            "diag_reported_timezone",
        )
        self.assertEqual(
            self.entity(model, "reported_dnd")._attr_unique_id, "diag_reported_dnd"
        )
        self.assertEqual(self.entity(model, "cartridge_type").native_value, "maintenance")


if __name__ == "__main__":
    unittest.main()
