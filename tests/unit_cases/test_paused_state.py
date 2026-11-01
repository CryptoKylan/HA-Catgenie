"""SYNTHETIC paused-state contract.

Reported operation state 2 is app SUSPENDED, mapped by
``convertDeviceCleaningStatusToAppCleannigStatus`` (#6945) to STOPPED.
That is a pause only with an explicit empty active-error list, blank
vendor text, and an explicit connected report. Active-error code 2 is
water fill and is a different namespace. Payloads are not live captures.
"""

from __future__ import annotations

import json
import unittest

from pydantic import ValidationError

from tests.unit_cases.test_unknown_operation_state import (
    CANDIDATE,
    TolerantDevice,
    _entities,
    _sensor,
    operation_state_label,
    thing,
)
from tests.unit_cases.test_operation_status import _entity


class PausedStateContractTests(unittest.TestCase):
    """Device-aware pause label. Integer 2 alone is not a pause."""

    def test_integer_label_does_not_treat_state_2_as_paused(self) -> None:
        self.assertEqual(operation_state_label(2), "error")
        self.assertNotEqual(operation_state_label(2), "paused")

    def test_enum_options_and_translation_include_paused(self) -> None:
        operation = _sensor("operation_state")
        self.assertEqual(operation.options, ["idle", "cleaning", "paused", "error"])
        self.assertNotIn("running", operation.options)
        self.assertNotIn("water_fill", operation.options)
        translation = json.loads(
            (CANDIDATE / "custom_components/catgenie/translations/en.json").read_text()
        )
        states = translation["entity"]["sensor"]["operation_state"]["state"]
        self.assertEqual(states["paused"], "Paused")
        self.assertEqual(states["error"], "Error")
        self.assertEqual(set(states), {"idle", "cleaning", "paused", "error"})

    def test_explicit_empty_errors_online_state_2_is_paused(self) -> None:
        for progress, expected in ((0, 0), (40, 40), (100, 100), (255, None)):
            with self.subTest(progress=progress):
                device = TolerantDevice.model_validate(
                    thing("paused", 2, progress=progress, error="", active_errors=[])
                )
                states, progress_entities, errors, cleaning = _entities([device])
                text = _entity(device)
                self.assertEqual(states[0].native_value, "paused")
                self.assertEqual(states[0].extra_state_attributes["raw_state"], 2)
                self.assertEqual(states[0].extra_state_attributes["active_errors"], [])
                self.assertEqual(states[0]._attr_unique_id, "paused_operation_state")
                self.assertEqual(errors[0].native_value, "No active errors")
                self.assertEqual(errors[0].extra_state_attributes, {"active_errors": []})
                self.assertEqual(errors[0]._attr_unique_id, "paused_operation_error")
                self.assertTrue(text.available)
                self.assertEqual(text.native_value, "Paused")
                self.assertNotEqual(text.native_value, "Idle")
                self.assertNotIn("%", str(text.native_value))
                self.assertEqual(
                    progress_entities[0].native_value,
                    expected,
                )
                self.assertIsNone(cleaning[0].is_on)

    def test_blank_vendor_text_does_not_block_explicit_pause(self) -> None:
        device = TolerantDevice.model_validate(
            thing("blank-pause", 2, progress=17, error=" \t\n ", active_errors=[])
        )
        states, progress_entities, errors, _ = _entities([device])
        self.assertEqual(states[0].native_value, "paused")
        self.assertEqual(errors[0].native_value, "No active errors")
        self.assertEqual(_entity(device).native_value, "Paused")
        self.assertEqual(progress_entities[0].native_value, 17)

    def test_snake_case_empty_active_errors_is_explicit(self) -> None:
        payload = thing("alias-pause", 2, progress=8)
        del payload["activeErrors"]
        payload["active_errors"] = []
        device = TolerantDevice.model_validate(payload)
        self.assertIn("active_errors", device.model_fields_set)
        self.assertEqual(_entities([device])[0][0].native_value, "paused")
        self.assertEqual(_entities([device])[2][0].native_value, "No active errors")
        self.assertEqual(_entity(device).native_value, "Paused")

    def test_water_fill_code_2_with_operation_state_2_stays_a_fault(self) -> None:
        device = TolerantDevice.model_validate(
            thing("water-fill-state-2", 2, progress=40, active_errors=[2])
        )
        states, progress_entities, errors, cleaning = _entities([device])
        text = _entity(device)
        self.assertEqual(states[0].native_value, "error")
        self.assertNotEqual(states[0].native_value, "paused")
        self.assertEqual(states[0].extra_state_attributes["raw_state"], 2)
        self.assertEqual(states[0].extra_state_attributes["active_errors"], [2])
        self.assertEqual(errors[0].native_value, "Water fill issue")
        self.assertEqual(errors[0].extra_state_attributes, {"active_errors": [2]})
        self.assertIsNone(text.native_value)
        self.assertNotEqual(text.native_value, "Paused")
        self.assertNotEqual(text.native_value, "40%")
        self.assertEqual(progress_entities[0].native_value, 40)
        self.assertIsNone(cleaning[0].is_on)

    def test_other_faults_with_state_2_keep_error_visibility(self) -> None:
        cases = (
            ([3], "Drainage issue"),
            ([4], "Dryer overheating"),
            ([5], "Cleaning solution cartridge missing"),
            ([6], "Cleaning solution cartridge empty"),
            ([99], "Unknown error code: 99"),
            ([2, 5, 99], "Water fill issue; Cleaning solution cartridge missing; Unknown error code: 99"),
            (["2"], "Unknown error code: 2"),
            ([2.0], "Unknown error code: 2.0"),
            ([True], "Unknown error code: True"),
            ([None], "Unknown error code: None"),
        )
        for active, expected in cases:
            with self.subTest(active=active):
                device = TolerantDevice.model_validate(
                    thing("other-fault", 2, progress=22, active_errors=active)
                )
                states, progress_entities, errors, _ = _entities([device])
                self.assertEqual(states[0].native_value, "error")
                self.assertEqual(errors[0].native_value, expected)
                self.assertEqual(errors[0].extra_state_attributes["active_errors"], active)
                self.assertIsNone(_entity(device).native_value)
                self.assertEqual(progress_entities[0].native_value, 22)

    def test_vendor_text_with_state_2_beats_empty_active_errors(self) -> None:
        device = TolerantDevice.model_validate(
            thing("vendor-pause", 2, progress=9, error="WATER FILL ISSUE", active_errors=[])
        )
        states, progress_entities, errors, _ = _entities([device])
        self.assertEqual(states[0].native_value, "error")
        self.assertEqual(errors[0].native_value, "WATER FILL ISSUE")
        self.assertEqual(errors[0].extra_state_attributes["active_errors"], [])
        self.assertIsNone(_entity(device).native_value)
        self.assertEqual(progress_entities[0].native_value, 9)

    def test_missing_active_errors_is_not_a_pause(self) -> None:
        payload = thing("missing-errors", 2, progress=40)
        del payload["activeErrors"]
        device = TolerantDevice.model_validate(payload)
        self.assertNotIn("active_errors", device.model_fields_set)
        self.assertEqual(device.active_errors, [])
        states, progress_entities, errors, _ = _entities([device])
        self.assertEqual(states[0].native_value, "error")
        self.assertEqual(errors[0].native_value, "Error reported (operation state: 2)")
        self.assertNotIn("Water fill", errors[0].native_value)
        self.assertIsNone(_entity(device).native_value)
        self.assertEqual(progress_entities[0].native_value, 40)

    def test_malformed_active_errors_are_refused_not_paused(self) -> None:
        for bad in (None, "none", {}, 2, "[]", True, 2.0):
            with self.subTest(bad=bad):
                payload = thing("malformed-errors", 2)
                payload["activeErrors"] = bad
                with self.assertRaises(ValidationError):
                    TolerantDevice.model_validate(payload)

    def test_offline_and_missing_status_are_not_paused(self) -> None:
        for status in ("disconnected", "offline", "", "unknown", " disconnected"):
            with self.subTest(status=status):
                payload = thing("offline-pause", 2, progress=40, active_errors=[])
                payload["reportedStatus"] = status
                device = TolerantDevice.model_validate(payload)
                states, progress_entities, errors, _ = _entities([device])
                text = _entity(device)
                self.assertIsNone(states[0].native_value)
                self.assertIsNone(errors[0].native_value)
                self.assertFalse(text.available)
                self.assertIsNone(text.native_value)
                self.assertNotEqual(text.native_value, "Paused")
                self.assertEqual(progress_entities[0].native_value, 40)

        missing = thing("missing-status-pause", 2, progress=15, active_errors=[])
        del missing["reportedStatus"]
        missing["status"] = 2
        device = TolerantDevice.model_validate(missing)
        self.assertNotIn("reported_status", device.model_fields_set)
        states, _, errors, _ = _entities([device])
        text = _entity(device)
        self.assertIsNone(states[0].native_value)
        self.assertIsNone(errors[0].native_value)
        self.assertTrue(text.available)
        self.assertIsNone(text.native_value)
        self.assertNotEqual(text.native_value, "Paused")
        self.assertNotEqual(text.native_value, "Idle")

    def test_unknown_states_stay_errors_even_with_explicit_empty_errors(self) -> None:
        for state in (3, 4, 5, 6, 99, -1, 129, 255):
            with self.subTest(state=state):
                device = TolerantDevice.model_validate(
                    thing("unknown-state", state, progress=50, active_errors=[])
                )
                states, progress_entities, errors, cleaning = _entities([device])
                text = _entity(device)
                self.assertEqual(states[0].native_value, "error")
                self.assertEqual(operation_state_label(state), "error")
                self.assertEqual(
                    errors[0].native_value,
                    f"Error reported (operation state: {state})",
                )
                self.assertNotIn("Water fill", errors[0].native_value)
                self.assertIsNone(text.native_value)
                self.assertNotEqual(text.native_value, "Paused")
                self.assertNotEqual(text.native_value, "50%")
                self.assertNotEqual(text.native_value, "Idle")
                self.assertEqual(progress_entities[0].native_value, 50)
                self.assertIsNone(cleaning[0].is_on)

    def test_idle_and_cleaning_progress_contracts_stay(self) -> None:
        idle = TolerantDevice.model_validate(thing("idle-contract", 0, progress=100))
        self.assertEqual(_entities([idle])[0][0].native_value, "idle")
        self.assertEqual(_entity(idle).native_value, "Idle")
        self.assertEqual(_entities([idle])[2][0].native_value, "No active errors")
        self.assertEqual(_entity(idle, "operation_progress").native_value, 100)

        cleaning = TolerantDevice.model_validate(thing("clean-contract", 1, progress=42))
        self.assertEqual(_entities([cleaning])[0][0].native_value, "cleaning")
        self.assertEqual(_entity(cleaning).native_value, "42%")
        self.assertEqual(_entity(cleaning, "operation_progress").native_value, 42)
        self.assertEqual(_entities([cleaning])[2][0].native_value, "No active errors")

        faulted_clean = TolerantDevice.model_validate(
            thing("clean-fault", 1, progress=42, active_errors=[2])
        )
        self.assertEqual(_entities([faulted_clean])[0][0].native_value, "cleaning")
        self.assertEqual(_entity(faulted_clean).native_value, "42%")
        self.assertEqual(_entities([faulted_clean])[2][0].native_value, "Water fill issue")


if __name__ == "__main__":
    unittest.main(verbosity=2)
