"""SYNTHETIC readable operation-status sensor.

Uses the pinned catgenie 0.1.6 models and the current HA import seams.
Payloads are not live cloud responses. This does not start Home Assistant.
"""

from __future__ import annotations

import json
import unittest
from math import nan

from pydantic import ValidationError

from tests.unit_cases.test_unknown_operation_state import (
    CANDIDATE,
    CatGenieSensor,
    TolerantDevice,
    _Coordinator,
    _sensor,
    thing,
)


def _status_description():
    return _sensor("operation_status")


def _entity(device, key="operation_status"):
    return CatGenieSensor(
        _Coordinator({device.manufacturer_id: device}),
        device.manufacturer_id,
        _sensor(key),
    )


def _replace_progress(device, progress):
    device.operation_status = device.operation_status.model_construct(
        state=device.operation_status.state,
        progress=progress,
    )
    return device


class ReadableOperationStatusTests(unittest.TestCase):
    def test_text_sensor_does_not_replace_numeric_progress(self) -> None:
        status = _status_description()
        progress = _sensor("operation_progress")
        self.assertEqual(status.key, "operation_status")
        self.assertEqual(status.translation_key, "operation_status")
        self.assertNotEqual(status.key, "operation_state")
        self.assertIsNone(status.device_class)
        self.assertIsNone(status.state_class)
        self.assertIsNone(status.native_unit_of_measurement)
        self.assertFalse(getattr(status, "options", None))
        self.assertEqual(progress.native_unit_of_measurement, "%")
        self.assertEqual(progress.state_class, "measurement")
        self.assertIsNone(progress.device_class)
        translation = json.loads(
            (CANDIDATE / "custom_components/catgenie/translations/en.json").read_text()
        )
        sensors = translation["entity"]["sensor"]
        self.assertEqual(sensors["operation_status"]["name"], "Operation status")
        self.assertNotIn("state", sensors["operation_status"])
        self.assertIn("operation_state", sensors)
        self.assertIn("operation_progress", sensors)
        self.assertIn("operation_error", sensors)

    def test_online_idle_overrides_missing_and_stale_progress(self) -> None:
        for progress in (255, 100, 0, 42):
            with self.subTest(progress=progress):
                device = TolerantDevice.model_validate(
                    thing("idle", 0, progress=progress)
                )
                entity = _entity(device)
                numeric = _entity(device, "operation_progress")
                self.assertTrue(device.is_online)
                self.assertTrue(entity.available)
                self.assertEqual(entity.native_value, "Idle")
                self.assertEqual(entity._attr_unique_id, "idle_operation_status")
                self.assertEqual(
                    numeric.native_value, 0 if progress == 255 else progress
                )
                self.assertEqual(numeric._attr_unique_id, "idle_operation_progress")

    def test_online_cleaning_percentage_text(self) -> None:
        for progress, expected in ((0, "0%"), (42, "42%"), (100, "100%")):
            with self.subTest(progress=progress):
                device = TolerantDevice.model_validate(
                    thing("cleaning", 1, progress=progress)
                )
                entity = _entity(device)
                numeric = _entity(device, "operation_progress")
                self.assertTrue(entity.available)
                self.assertEqual(entity.native_value, expected)
                self.assertEqual(numeric.native_value, progress)
                self.assertNotEqual(entity.native_value, "Idle")

    def test_online_cleaning_invalid_progress_is_not_invented(self) -> None:
        for progress, numeric_value in (
            (255, None),
            (101, 101),
            (-1, -1),
            (256, 256),
        ):
            with self.subTest(progress=progress):
                device = TolerantDevice.model_validate(
                    thing("invalid", 1, progress=progress)
                )
                entity = _entity(device)
                self.assertTrue(entity.available)
                self.assertIsNone(entity.native_value)
                self.assertNotEqual(entity.native_value, "unknown")
                self.assertIsNone(_entity(device, "operation_progress").native_value)
                self.assertEqual(device.operation_status.clean_progress_pct, numeric_value)

        for label, raw, numeric_value in (
            ("bool-true", True, 1),
            ("bool-false", False, 0),
            ("numeric-string", "42", 42),
        ):
            with self.subTest(label=label):
                payload = thing("coerced", 1, progress=0)
                payload["operationStatus"]["progress"] = raw
                device = TolerantDevice.model_validate(payload)
                entity = _entity(device)
                self.assertTrue(entity.available)
                self.assertIsNone(entity.native_value)
                self.assertIsNone(_entity(device, "operation_progress").native_value)
                self.assertEqual(device.operation_status.clean_progress_pct, numeric_value)

        for label, raw in (("nan", nan), ("inf", float("inf")), ("text", "nope"), ("blank", " ")):
            with self.subTest(label=label):
                payload = thing("rejected", 1, progress=0)
                payload["operationStatus"]["progress"] = raw
                with self.assertRaises(ValidationError):
                    TolerantDevice.model_validate(payload)
                device = _replace_progress(
                    TolerantDevice.model_validate(thing("constructed", 1, progress=10)),
                    raw,
                )
                entity = _entity(device)
                self.assertTrue(entity.available)
                self.assertIsNone(entity.native_value)
                self.assertNotEqual(entity.native_value, "unknown")

        missing = thing("missing-progress", 1, progress=10)
        del missing["operationStatus"]["progress"]
        with self.assertRaises(ValidationError):
            TolerantDevice.model_validate(missing)
        device = TolerantDevice.model_validate(thing("constructed-missing", 1, progress=10))
        device.operation_status = device.operation_status.model_construct(state=1)
        self.assertIsNone(_entity(device).native_value)

    def test_offline_missing_and_defaults_are_not_idle(self) -> None:
        disconnected = thing("offline", 0, progress=100)
        disconnected["reportedStatus"] = "disconnected"
        device = TolerantDevice.model_validate(disconnected)
        entity = _entity(device)
        self.assertFalse(device.is_online)
        self.assertFalse(entity.available)
        self.assertIsNone(entity.native_value)
        self.assertNotEqual(entity.native_value, "Idle")
        self.assertEqual(_entity(device, "operation_progress").native_value, 100)

        for status in ("offline", "", "unknown", " disconnected"):
            with self.subTest(status=status):
                payload = thing("explicit-offline", 0, progress=255)
                payload["reportedStatus"] = status
                entity = _entity(TolerantDevice.model_validate(payload))
                self.assertFalse(entity.available)
                self.assertIsNone(entity.native_value)

        missing_status = thing("missing-status", 0, progress=255)
        del missing_status["reportedStatus"]
        missing_status["status"] = 2
        device = TolerantDevice.model_validate(missing_status)
        entity = _entity(device)
        self.assertFalse(device.is_online)
        self.assertNotIn("reported_status", device.model_fields_set)
        self.assertTrue(entity.available)
        self.assertIsNone(entity.native_value)
        self.assertNotEqual(entity.native_value, "Idle")

        defaults = {
            "manufacturerId": "defaults",
            "name": "SYNTHETIC-defaults",
            "macAddress": "aa:bb:cc:dd:ee:ff",
            "hwRevision": "1",
            "fwVersion": "8.7.205R",
        }
        device = TolerantDevice.model_validate(defaults)
        entity = _entity(device)
        self.assertNotIn("reported_status", device.model_fields_set)
        self.assertNotIn("operation_status", device.model_fields_set)
        self.assertEqual(device.operation_status.state, 0)
        self.assertIsNone(device.operation_status.clean_progress_pct)
        self.assertTrue(entity.available)
        self.assertIsNone(entity.native_value)
        self.assertNotEqual(entity.native_value, "Idle")

        connected_without_status = thing("online-default-state", 0)
        del connected_without_status["operationStatus"]
        device = TolerantDevice.model_validate(connected_without_status)
        entity = _entity(device)
        self.assertTrue(device.is_online)
        self.assertTrue(entity.available)
        self.assertIsNone(entity.native_value)
        self.assertNotEqual(entity.native_value, "Idle")

        capitalized = thing("capital-connected", 0, progress=100)
        capitalized["reportedStatus"] = "Connected"
        entity = _entity(TolerantDevice.model_validate(capitalized))
        self.assertTrue(entity.available)
        self.assertEqual(entity.native_value, "Idle")

    def test_fault_and_unsupported_state_are_not_false_idle(self) -> None:
        idle_fault = TolerantDevice.model_validate(
            thing("idle-fault", 0, progress=100, active_errors=[5])
        )
        entity = _entity(idle_fault)
        error = _entity(idle_fault, "operation_error")
        self.assertEqual(entity.native_value, "Idle")
        self.assertEqual(error.native_value, "Cleaning solution cartridge missing")
        self.assertEqual(error.extra_state_attributes, {"active_errors": [5]})

        for state in (2, 5, 99, -1):
            with self.subTest(state=state):
                device = TolerantDevice.model_validate(
                    thing("unsupported", state, progress=0, active_errors=[2])
                )
                entity = _entity(device)
                error = _entity(device, "operation_error")
                state_entity = _entity(device, "operation_state")
                self.assertTrue(entity.available)
                self.assertIsNone(entity.native_value)
                self.assertNotEqual(entity.native_value, "Idle")
                self.assertNotEqual(entity.native_value, "unknown")
                self.assertEqual(state_entity.native_value, "error")
                self.assertEqual(error.extra_state_attributes["active_errors"], [2])
                self.assertEqual(_entity(device, "operation_progress").native_value, 0)

        offline_fault = thing("offline-fault", 0, progress=100, active_errors=[5])
        offline_fault["reportedStatus"] = "disconnected"
        device = TolerantDevice.model_validate(offline_fault)
        entity = _entity(device)
        error = _entity(device, "operation_error")
        self.assertFalse(entity.available)
        self.assertIsNone(entity.native_value)
        self.assertNotEqual(entity.native_value, "Idle")
        self.assertTrue(error.available)
        self.assertEqual(error.native_value, "Cleaning solution cartridge missing")


if __name__ == "__main__":
    unittest.main(verbosity=2)
