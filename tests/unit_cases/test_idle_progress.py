"""Synthetic numeric display regressions; no device or network calls."""

from copy import deepcopy
import unittest

from pydantic import ValidationError

from tests.unit_cases.test_operation_status import _entity
from tests.unit_cases.test_unknown_operation_state import TolerantDevice, thing


class IdleProgressTests(unittest.TestCase):
    def device(self, state=0, progress: object = 255):
        payload = thing("display", state)
        payload["operationStatus"]["progress"] = progress
        return TolerantDevice.model_validate(payload)

    def value(self, device):
        return _entity(device, "operation_progress").native_value

    def wire_payload(self):
        # Minimal real-model payload reproducing the saved vendor status shape.
        # Identifiers are synthetic; no network calls or live data are needed.
        return {
            "manufacturerId": "display",
            "name": "SYNTHETIC-display",
            "macAddress": "aa:bb:cc:dd:ee:ff",
            "hwRevision": "1",
            "fwVersion": "8.7.205R",
            "reportedStatus": "connected",
            "activeErrors": [],
            "operationStatus": {"state": 0, "progress": 255},
        }

    def test_minimal_wire_idle_without_optional_error_displays_zero(self):
        payload = self.wire_payload()
        before = deepcopy(payload)
        device = TolerantDevice.model_validate(payload)
        telemetry = deepcopy(device.model_dump())
        self.assertEqual(device.operation_status.model_fields_set, {"state", "progress"})
        self.assertEqual(self.value(device), 0)
        self.assertEqual(_entity(device).native_value, "Idle")
        self.assertEqual(device.operation_status.progress, 255)
        self.assertIsNone(device.operation_status.clean_progress_pct)
        self.assertEqual(device.model_dump(), telemetry)
        self.assertEqual(payload, before)

    def test_optional_error_still_requires_all_other_idle_guards(self):
        for key, value in (
            ("reportedStatus", "offline"),
            ("reportedStatus", None),
            ("activeErrors", [2]),
            ("activeErrors", None),
        ):
            with self.subTest(key=key, value=value):
                payload = self.wire_payload()
                if value is None:
                    del payload[key]
                else:
                    payload[key] = value
                self.assertIsNone(self.value(TolerantDevice.model_validate(payload)))
        for state in (1, 2, 99):
            with self.subTest(state=state):
                payload = self.wire_payload()
                payload["operationStatus"]["state"] = state
                self.assertIsNone(self.value(TolerantDevice.model_validate(payload)))
        device = TolerantDevice.model_validate(self.wire_payload())
        device.operation_status = device.operation_status.model_construct(progress=255)
        self.assertIsNone(self.value(device))

    def test_optional_error_preserves_valid_idle_percentages(self):
        for progress in (0, 42, 100):
            with self.subTest(progress=progress):
                payload = self.wire_payload()
                payload["operationStatus"]["progress"] = progress
                self.assertEqual(self.value(TolerantDevice.model_validate(payload)), progress)

    def test_optional_error_does_not_relax_progress_validation(self):
        for progress in (False, True, "0", "42", "255", -1, 101, 256):
            with self.subTest(progress=progress):
                payload = self.wire_payload()
                payload["operationStatus"]["progress"] = progress
                self.assertIsNone(self.value(TolerantDevice.model_validate(payload)))
        payload = self.wire_payload()
        del payload["operationStatus"]["progress"]
        with self.assertRaises(ValidationError):
            TolerantDevice.model_validate(payload)
        device = TolerantDevice.model_validate(self.wire_payload())
        device.operation_status = device.operation_status.model_construct(state=0)
        self.assertEqual(self.value(device), 0)
        device.operation_status = device.operation_status.model_construct(state=1)
        self.assertIsNone(self.value(device))

    def test_present_optional_error_must_be_a_blank_string(self):
        for error in ("", " \t\n", "fault", None, False, 0, [], {}):
            with self.subTest(error=error):
                device = TolerantDevice.model_validate(self.wire_payload())
                # Invalid wire types are rejected by Pydantic; constructed
                # statuses also must not turn them into a healthy idle zero.
                device.operation_status = device.operation_status.model_construct(
                    state=0, progress=255, error=error
                )
                if isinstance(error, str) and not error.strip():
                    self.assertEqual(self.value(device), 0)
                else:
                    self.assertIsNone(self.value(device))

    def test_idle_sentinel_is_display_zero_without_mutating_telemetry(self):
        device = self.device()
        before = deepcopy(device.model_dump())
        self.assertEqual(self.value(device), 0)
        self.assertEqual(device.model_dump(), before)
        self.assertEqual(device.operation_status.progress, 255)
        self.assertIsNone(device.operation_status.clean_progress_pct)
        self.assertEqual(_entity(device).native_value, "Idle")
        self.assertEqual(_entity(device, "operation_error").native_value, "No active errors")
        entity = _entity(device, "operation_progress")
        self.assertEqual(entity._attr_unique_id, "display_operation_progress")
        self.assertEqual(entity.entity_description.native_unit_of_measurement, "%")
        self.assertEqual(entity.entity_description.state_class, "measurement")

    def test_missing_progress_on_constructed_status_is_display_zero(self):
        device = self.device()
        device.operation_status = device.operation_status.model_construct(state=0, error="")
        self.assertEqual(self.value(device), 0)
        # The pinned dependency still rejects absent progress on the wire.
        payload = thing("missing", 0)
        del payload["operationStatus"]["progress"]
        with self.assertRaises(ValidationError):
            TolerantDevice.model_validate(payload)

    def test_valid_idle_percent_is_preserved_not_reset(self):
        for progress in (0, 42, 100):
            with self.subTest(progress=progress):
                self.assertEqual(self.value(self.device(progress=progress)), progress)

    def test_running_strict_valid_percent_is_preserved(self):
        for progress in (0, 42, 100):
            with self.subTest(progress=progress):
                self.assertEqual(self.value(self.device(1, progress)), progress)
        device = self.device(1)
        device.operation_status = device.operation_status.model_construct(state=1, progress=42.5)
        self.assertEqual(self.value(device), 42.5)

    def test_running_missing_and_sentinel_are_not_zero(self):
        self.assertIsNone(self.value(self.device(1)))
        device = self.device(1)
        device.operation_status = device.operation_status.model_construct(state=1, error="")
        self.assertIsNone(self.value(device))

    def test_valid_reported_values_are_not_synthetic_fallbacks(self):
        for state in (0, 1, 2, 99):
            for progress in (0, 42, 100):
                with self.subTest(state=state, progress=progress):
                    device = self.device(state, progress)
                    device.reported_status = "disconnected"
                    device.active_errors = [5]
                    self.assertEqual(self.value(device), progress)

    def test_malformed_progress_never_becomes_zero(self):
        for state in (0, 1):
            for raw in (False, True, "0", "42", "255", None, "bad", -1, 101, 256,
                        float("nan"), float("inf"), [], {}):
                with self.subTest(state=state, raw=raw):
                    device = self.device(state)
                    # Exercise values rejected by the pinned model as well as
                    # raw values retained before its int/string/bool coercion.
                    device.operation_status = device.operation_status.model_construct(
                        state=state, progress=raw, error=""
                    )
                    self.assertIsNone(self.value(device))
        for raw in (False, True, "0", "42", "255"):
            with self.subTest(validated_raw=raw):
                self.assertIsNone(self.value(self.device(progress=raw)))

    def test_fault_or_unconfirmed_clear_does_not_display_zero(self):
        for errors in ([5], [2], [False], ["5"], None, "", {}):
            with self.subTest(errors=errors):
                device = self.device()
                device.active_errors = errors
                self.assertIsNone(self.value(device))
        device = self.device()
        device.model_fields_set.discard("active_errors")
        self.assertIsNone(self.value(device))
        for error in ("fault", None, False):
            with self.subTest(error=error):
                device = self.device()
                device.operation_status.error = error
                self.assertIsNone(self.value(device))
        device = self.device()
        device.operation_status.model_fields_set.discard("error")
        # Idle contract: error is optional on the wire, unlike activeErrors.
        # A present malformed/nonblank error above still prevents fallback.
        self.assertEqual(self.value(device), 0)

    def test_offline_and_missing_connectivity_do_not_display_zero(self):
        for status in ("disconnected", "offline", "", "unknown", None, True):
            with self.subTest(status=status):
                device = self.device()
                device.reported_status = status
                self.assertIsNone(self.value(device))
        device = self.device()
        device.model_fields_set.discard("reported_status")
        self.assertIsNone(self.value(device))

    def test_unknown_malformed_and_missing_state_do_not_display_zero(self):
        for state in (2, 5, 99, -1, False, "0", None, 0.0):
            with self.subTest(state=state):
                device = self.device()
                device.operation_status.state = state
                self.assertIsNone(self.value(device))
        device = self.device()
        device.model_fields_set.discard("operation_status")
        self.assertIsNone(self.value(device))
        device = self.device()
        device.operation_status.model_fields_set.discard("state")
        self.assertIsNone(self.value(device))


if __name__ == "__main__":
    unittest.main()
