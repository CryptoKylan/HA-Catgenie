"""SYNTHETIC auto-lock timeout contract. Not a live vendor or device result.

The app slider snaps to elementary units 1–6 times a multiplier of 5 minutes,
then stores seconds. Switch-off stores 0. The PUT object is autoLock only.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

import tests.unit_cases.test_settings_controls as harness

INTEGRATION = Path(__file__).resolve().parents[2] / "custom_components" / "catgenie"
_CONFIG = harness.volume_payload.__globals__
auto_lock_payload = _CONFIG["auto_lock_payload"]
display_auto_lock_minutes = _CONFIG["display_auto_lock_minutes"]
AUTO_LOCK_MINUTES = _CONFIG["AUTO_LOCK_MINUTES"]
AUTO_LOCK_SECONDS = _CONFIG["AUTO_LOCK_SECONDS"]


def _number(coordinator: harness._Coordinator) -> harness.CatGenieNumber:
    description = next(item for item in harness.NUMBERS if item.key == "auto_lock_timeout")
    return harness.CatGenieNumber(coordinator, "settings-device", description)


class AutoLockTimeoutTests(unittest.TestCase):
    def test_exact_minute_choices_map_to_wire_seconds(self) -> None:
        self.assertEqual(AUTO_LOCK_MINUTES, (0, 5, 10, 15, 20, 25, 30))
        self.assertEqual(AUTO_LOCK_SECONDS, (0, 300, 600, 900, 1200, 1500, 1800))
        device = harness.make_device()
        for minutes, seconds in zip(AUTO_LOCK_MINUTES, AUTO_LOCK_SECONDS, strict=True):
            with self.subTest(minutes=minutes):
                payload = auto_lock_payload(device, minutes)
                self.assertEqual(payload, {"autoLock": seconds})
                self.assertEqual(set(payload), {"autoLock"})
                self.assertIs(type(payload["autoLock"]), int)
                self.assertEqual(auto_lock_payload(device, float(minutes)), payload)

    def test_zero_is_disable_and_non_choices_are_refused(self) -> None:
        device = harness.make_device(configuration={"autoLock": 1800})
        self.assertEqual(auto_lock_payload(device, 0), {"autoLock": 0})
        for bad in (1, 7, 12, 35, 2.5, -5, 300, None, True, "10"):
            with self.subTest(bad=bad):
                with self.assertRaises(harness.SettingsWriteRefused) as raised:
                    auto_lock_payload(device, bad)
                self.assertEqual(raised.exception.reason, "not_a_choice")

    def test_missing_field_is_not_treated_as_disabled(self) -> None:
        omitted = harness.make_device(omit_configuration=("autoLock",))
        self.assertIsNone(display_auto_lock_minutes(omitted))
        with self.assertRaises(harness.SettingsWriteRefused) as raised:
            auto_lock_payload(omitted, 0)
        self.assertEqual(raised.exception.reason, "incomplete")

    def test_display_only_exact_stored_seconds(self) -> None:
        self.assertEqual(display_auto_lock_minutes(harness.make_device()), 0)
        shown = harness.make_device(configuration={"autoLock": 900})
        self.assertEqual(display_auto_lock_minutes(shown), 15)
        unexpected = harness.make_device(configuration={"autoLock": 100})
        self.assertIsNone(display_auto_lock_minutes(unexpected))
        self.assertEqual(auto_lock_payload(unexpected, 10), {"autoLock": 600})

    def test_offline_and_incomplete_send_nothing(self) -> None:
        offline = harness.make_device(reportedStatus="disconnected")
        with self.assertRaises(harness.SettingsWriteRefused) as raised:
            auto_lock_payload(offline, 5)
        self.assertEqual(raised.exception.reason, "offline")
        missing = harness.device_payload()
        del missing["configuration"]
        incomplete = harness.TolerantDevice.model_validate(missing)
        with self.assertRaises(harness.SettingsWriteRefused) as raised:
            auto_lock_payload(incomplete, 5)
        self.assertEqual(raised.exception.reason, "incomplete")
        with self.assertRaises(harness.SettingsWriteRefused) as raised:
            auto_lock_payload(None, 5)
        self.assertEqual(raised.exception.reason, "missing")


class AutoLockEntityTests(unittest.IsolatedAsyncioTestCase):
    async def test_entity_writes_only_autolock_and_holds_minutes(self) -> None:
        self.assertEqual(
            [item.key for item in harness.NUMBERS],
            ["volume", "auto_lock_timeout", "cat_activation_delay"],
        )
        coordinator = harness._Coordinator(harness.make_device())
        entity = _number(coordinator)
        self.assertEqual(entity.native_value, 0)
        self.assertEqual(entity.native_min_value, 0)
        self.assertEqual(entity.native_max_value, 30)
        self.assertEqual(entity.native_step, 5)
        self.assertEqual(entity.mode, "box")
        self.assertEqual(entity.native_unit_of_measurement, "min")
        self.assertEqual(entity._attr_unique_id, "settings-device_auto_lock_timeout")
        self.assertNotEqual(entity._attr_unique_id, "settings-device_panel_lock_delay")

        await entity.async_set_native_value(15.0)
        self.assertEqual(coordinator.client.methods, ["update_configuration"])
        self.assertEqual(
            coordinator.client.bodies,
            [{"device_id": "settings-device", "autoLock": 900}],
        )
        self.assertNotIn("set_auto_lock", coordinator.client.methods)
        self.assertEqual(entity.device.configuration.auto_lock, 0)
        self.assertEqual(entity.native_value, 15)
        self.assertEqual(entity.extra_state_attributes, {"pending_confirmation": True})
        coordinator.data["settings-device"] = harness.make_device(configuration={"autoLock": 900})
        self.assertEqual(entity.native_value, 15)
        self.assertIsNone(entity.extra_state_attributes)

    async def test_refused_entity_write_does_not_call_the_client(self) -> None:
        coordinator = harness._Coordinator(harness.make_device())
        entity = _number(coordinator)
        for bad in (1, 7, 35, 2.5):
            with self.subTest(bad=bad):
                with self.assertRaises(harness.HomeAssistantError):
                    await entity.async_set_native_value(bad)
        self.assertEqual(coordinator.client.bodies, [])
        self.assertEqual(coordinator.refreshes, 0)

    def test_library_setters_stay_unwired(self) -> None:
        number_src = (INTEGRATION / "number.py").read_text()
        config_src = (INTEGRATION / "configuration.py").read_text()
        select_src = (INTEGRATION / "select.py").read_text()
        self.assertIn("cat_activation_delay", [item.key for item in harness.NUMBERS])
        self.assertNotIn("set_auto_lock", number_src)
        self.assertNotIn("set_cat_delay", number_src)
        self.assertIn("cat_delay_payload", config_src)
        self.assertNotIn('"addDelay"', number_src)
        self.assertNotIn('"addDelay"', config_src)
        self.assertEqual([item.key for item in harness.SELECTS], ["activation_mode"])
        ast.parse(number_src)
        ast.parse(config_src)
        ast.parse(select_src)
        translations = harness.json.loads(
            (INTEGRATION / "translations" / "en.json").read_text()
        )
        self.assertEqual(translations["entity"]["number"]["auto_lock_timeout"]["name"], "Auto-lock timeout")
        self.assertNotIn("panel_lock_delay", translations["entity"].get("number", {}))
        self.assertEqual(
            translations["entity"]["number"]["cat_activation_delay"]["name"],
            "Cat activation delay",
        )
