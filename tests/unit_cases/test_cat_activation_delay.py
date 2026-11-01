"""SYNTHETIC cat-activation delay contract. Not a live vendor or device result.

App slider constants are 300/600/1800 seconds with a 300-second snap. The
label divides that integer by 60. The save object is exactly dndFrom, dndTo,
and catDelay. This control echoes a supported stored DND pair and does not
convert clocks or disable DND.
"""

from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

import tests.unit_cases.test_settings_controls as harness

INTEGRATION = Path(__file__).resolve().parents[2] / "custom_components" / "catgenie"
_CONFIG = harness.volume_payload.__globals__
cat_delay_payload = _CONFIG["cat_delay_payload"]
display_cat_delay_minutes = _CONFIG["display_cat_delay_minutes"]
CAT_DELAY_MINUTES = _CONFIG["CAT_DELAY_MINUTES"]
CAT_DELAY_SECONDS = _CONFIG["CAT_DELAY_SECONDS"]


def _number(coordinator: harness._Coordinator) -> harness.CatGenieNumber:
    description = next(item for item in harness.NUMBERS if item.key == "cat_activation_delay")
    return harness.CatGenieNumber(coordinator, "settings-device", description)


class CatDelayContractTests(unittest.TestCase):
    def test_choices_are_five_minute_steps_and_wire_seconds(self) -> None:
        self.assertEqual(CAT_DELAY_MINUTES, (5, 10, 15, 20, 25, 30))
        self.assertEqual(CAT_DELAY_SECONDS, (300, 600, 900, 1200, 1500, 1800))
        device = harness.make_device()
        for minutes, seconds in zip(CAT_DELAY_MINUTES, CAT_DELAY_SECONDS, strict=True):
            with self.subTest(minutes=minutes):
                payload = cat_delay_payload(device, minutes)
                self.assertEqual(
                    payload,
                    {"dndFrom": "", "dndTo": "", "catDelay": seconds},
                )
                self.assertEqual(list(payload), ["dndFrom", "dndTo", "catDelay"])
                self.assertIs(type(payload["catDelay"]), int)
                self.assertEqual(cat_delay_payload(device, float(minutes)), payload)

    def test_observed_1800_displays_as_30_minutes(self) -> None:
        device = harness.make_device(configuration={"catDelay": 1800})
        self.assertEqual(display_cat_delay_minutes(device), 30)
        self.assertEqual(device.configuration.cat_delay, 1800)

    def test_display_does_not_snap_an_unknown_integer(self) -> None:
        unexpected = harness.make_device(configuration={"catDelay": 100})
        self.assertIsNone(display_cat_delay_minutes(unexpected))
        self.assertEqual(
            cat_delay_payload(unexpected, 10),
            {"dndFrom": "", "dndTo": "", "catDelay": 600},
        )

    def test_missing_cat_delay_is_not_the_library_default(self) -> None:
        omitted = harness.make_device(omit_configuration=("catDelay",))
        self.assertIsNone(display_cat_delay_minutes(omitted))
        with self.assertRaises(harness.SettingsWriteRefused) as raised:
            cat_delay_payload(omitted, 10)
        self.assertEqual(raised.exception.reason, "incomplete")

    def test_non_choices_are_refused_before_any_payload(self) -> None:
        device = harness.make_device()
        for bad in (0, 1, 7, 35, 2.5, -5, 300, None, True, "30", 30.5):
            with self.subTest(bad=bad):
                with self.assertRaises(harness.SettingsWriteRefused) as raised:
                    cat_delay_payload(device, bad)
                self.assertEqual(raised.exception.reason, "not_a_choice")

    def test_echoes_supported_clocks_without_timezone_conversion(self) -> None:
        device = harness.make_device(
            configuration={
                "timezone": "-05:00",
                "dndFrom": "22:15:00",
                "dndTo": "02:45:09",
                "catDelay": 1800,
                "schedule": [{"hour": 6, "minute": 0, "time": "06:00:00"}],
                "mode": 1,
                "manual": 0,
                "volumeLevel": 4,
            }
        )
        stored_from = device.configuration.model_extra["dndFrom"]
        stored_to = device.configuration.model_extra["dndTo"]
        payload = cat_delay_payload(device, 15)
        self.assertIs(payload["dndFrom"], stored_from)
        self.assertIs(payload["dndTo"], stored_to)
        self.assertEqual(payload["dndFrom"], "22:15:00")
        self.assertEqual(payload["dndTo"], "02:45:09")
        self.assertEqual(payload["catDelay"], 900)
        for key in (
            "schedule",
            "mode",
            "manual",
            "volumeLevel",
            "timezone",
            "autoLock",
            "binaryElements",
            "manufacturerId",
        ):
            self.assertNotIn(key, payload)
        self.assertNotIn("-05:00", str(payload))

    def test_equal_clocks_are_copied_not_blanked(self) -> None:
        device = harness.make_device(
            configuration={"dndFrom": "08:00:00", "dndTo": "08:00:00"}
        )
        payload = cat_delay_payload(device, 5)
        self.assertEqual(payload["dndFrom"], "08:00:00")
        self.assertEqual(payload["dndTo"], "08:00:00")

    def test_unknown_dnd_representations_refuse_before_io(self) -> None:
        cases = (
            {"dndFrom": "", "dndTo": "06:00:00"},
            {"dndFrom": "06:00:00", "dndTo": ""},
            {"dndFrom": "6:00:00", "dndTo": "07:00:00"},
            {"dndFrom": "06:00", "dndTo": "07:00:00"},
            {"dndFrom": "06:00:00 ", "dndTo": "07:00:00"},
            {"dndFrom": None, "dndTo": None},
            {"dndFrom": 3600, "dndTo": 7200},
            {"dndFrom": "0\u0661:00:00", "dndTo": "01:00:00"},
            {"dndFrom": "01:00:00", "dndTo": "0\u0661:00:00"},
        )
        for configuration in cases:
            with self.subTest(configuration=configuration):
                device = harness.make_device(configuration=configuration)
                with self.assertRaises(harness.SettingsWriteRefused) as raised:
                    cat_delay_payload(device, 10)
                self.assertEqual(raised.exception.reason, "dnd_unknown")

    def test_missing_dnd_key_is_not_invented_as_empty(self) -> None:
        omitted = harness.make_device(omit_configuration=("dndFrom",))
        with self.assertRaises(harness.SettingsWriteRefused) as raised:
            cat_delay_payload(omitted, 10)
        self.assertEqual(raised.exception.reason, "dnd_unknown")

    def test_offline_missing_and_incomplete_send_nothing(self) -> None:
        offline = harness.make_device(reportedStatus="disconnected")
        with self.assertRaises(harness.SettingsWriteRefused) as raised:
            cat_delay_payload(offline, 10)
        self.assertEqual(raised.exception.reason, "offline")
        missing = harness.device_payload()
        del missing["configuration"]
        incomplete = harness.TolerantDevice.model_validate(missing)
        with self.assertRaises(harness.SettingsWriteRefused) as raised:
            cat_delay_payload(incomplete, 10)
        self.assertEqual(raised.exception.reason, "incomplete")
        with self.assertRaises(harness.SettingsWriteRefused) as raised:
            cat_delay_payload(None, 10)
        self.assertEqual(raised.exception.reason, "missing")


class CatDelayEntityTests(unittest.IsolatedAsyncioTestCase):
    async def test_setup_registers_the_number_and_the_write_is_the_atomic_put(self) -> None:
        self.assertEqual(
            [item.key for item in harness.NUMBERS],
            ["volume", "auto_lock_timeout", "cat_activation_delay"],
        )
        coordinator = harness._Coordinator(harness.make_device())
        added: list[harness.CatGenieNumber] = []

        class _Entry:
            runtime_data = coordinator

        async_setup_entry = harness.CatGenieNumber.async_set_native_value.__globals__[
            "async_setup_entry"
        ]
        await async_setup_entry(None, _Entry(), lambda entities: added.extend(entities))
        entity = next(
            item for item in added if item.entity_description.key == "cat_activation_delay"
        )
        self.assertIs(type(entity), harness.CatGenieNumber)
        self.assertEqual(entity.native_value, 30)
        self.assertEqual(entity.native_min_value, 5)
        self.assertEqual(entity.native_max_value, 30)
        self.assertEqual(entity.native_step, 5)
        self.assertEqual(entity.mode, "box")
        self.assertEqual(entity.native_unit_of_measurement, "min")
        self.assertEqual(entity._attr_unique_id, "settings-device_cat_activation_delay")

        cached = coordinator.data["settings-device"]
        coordinator.client.fresh_devices = [cached]
        await entity.async_set_native_value(20.0)
        self.assertEqual(
            coordinator.client.methods, ["get_devices", "update_configuration"]
        )
        self.assertIs(coordinator.data["settings-device"], cached)
        self.assertEqual(
            coordinator.client.bodies,
            [{
                "device_id": "settings-device",
                "dndFrom": "",
                "dndTo": "",
                "catDelay": 1200,
            }],
        )
        self.assertNotIn("set_cat_delay", coordinator.client.methods)
        self.assertEqual(entity.device.configuration.cat_delay, 1800)
        self.assertEqual(entity.native_value, 20)
        self.assertEqual(entity.extra_state_attributes, {"pending_confirmation": True})
        coordinator.data["settings-device"] = harness.make_device(
            configuration={"catDelay": 1200}
        )
        self.assertEqual(entity.native_value, 20)
        self.assertIsNone(entity.extra_state_attributes)
        self.assertEqual(coordinator.refreshes, 1)

    async def test_refused_write_does_not_call_the_client(self) -> None:
        coordinator = harness._Coordinator(harness.make_device())
        entity = _number(coordinator)
        for bad in (0, 7, 35, 2.5):
            with self.subTest(bad=bad):
                with self.assertRaises(harness.HomeAssistantError):
                    await entity.async_set_native_value(bad)
        mixed = harness._Coordinator(
            harness.make_device(configuration={"dndFrom": "", "dndTo": "06:00:00"})
        )
        with self.assertRaises(harness.HomeAssistantError):
            await _number(mixed).async_set_native_value(10)
        offline = harness._Coordinator(
            harness.make_device(reportedStatus="disconnected")
        )
        with self.assertRaises(harness.HomeAssistantError):
            await _number(offline).async_set_native_value(10)
        self.assertEqual(coordinator.client.bodies, [])
        self.assertEqual(mixed.client.bodies, [])
        self.assertEqual(offline.client.bodies, [])
        self.assertEqual(coordinator.refreshes, 0)

    def test_dnd_editor_and_library_setter_stay_unwired(self) -> None:
        number_src = (INTEGRATION / "number.py").read_text()
        config_src = (INTEGRATION / "configuration.py").read_text()
        init_src = (INTEGRATION / "__init__.py").read_text()
        self.assertNotIn("set_cat_delay", number_src)
        self.assertNotIn("prepare_dnd", number_src)
        self.assertNotIn("local_time_to_utc_time", number_src)
        self.assertNotIn("local_time_to_utc_time", config_src)
        self.assertNotIn("ZoneInfo", config_src)
        self.assertNotIn('"-05:00"', config_src)
        self.assertNotIn("Platform.TIME", init_src)
        self.assertIn("cat_delay_payload", config_src)
        translations = harness.json.loads(
            (INTEGRATION / "translations" / "en.json").read_text()
        )
        self.assertEqual(
            translations["entity"]["number"]["cat_activation_delay"]["name"],
            "Cat activation delay",
        )
        self.assertEqual(
            translations["entity"]["sensor"]["cat_activation_delay"]["name"],
            "Reported cat activation delay",
        )
        ast.parse(number_src)
        ast.parse(config_src)


def _snapshot(device: harness.TolerantDevice) -> dict:
    configuration = device.configuration
    extra = configuration.model_extra or {}
    return {
        "mode": configuration.mode,
        "manual": extra.get("manual"),
        "volume": configuration.volume_level,
        "auto_lock": configuration.auto_lock,
        "cat_delay": configuration.cat_delay,
        "dnd_from": extra.get("dndFrom"),
        "dnd_to": extra.get("dndTo"),
        "schedule": [
            (entry.hour, entry.minute, (entry.model_extra or {}).get("time"))
            for entry in configuration.schedule
        ],
    }


class CatDelayFreshReadTests(unittest.IsolatedAsyncioTestCase):
    """The coupled payload uses one fresh get_devices() pair, not the cache."""

    async def test_bad_choice_and_cached_offline_or_missing_skip_io(self) -> None:
        coordinator = harness._Coordinator(harness.make_device())
        coordinator.client.read_error = RuntimeError("must-not-read")
        entity = _number(coordinator)
        for bad in (0, 7, 35, True, False, "30", None, 2.5):
            with self.subTest(bad=bad):
                with self.assertRaises(harness.HomeAssistantError):
                    await entity.async_set_native_value(bad)
        self.assertEqual(coordinator.client.methods, [])
        self.assertEqual(coordinator.client.bodies, [])
        self.assertEqual(coordinator.refreshes, 0)

        offline = harness._Coordinator(
            harness.make_device(reportedStatus="disconnected")
        )
        offline.client.read_error = RuntimeError("must-not-read")
        with self.assertRaises(harness.HomeAssistantError):
            await _number(offline).async_set_native_value(10)
        self.assertEqual(offline.client.methods, [])
        self.assertEqual(offline.client.bodies, [])

        missing = harness._Coordinator(harness.make_device())
        missing.client.read_error = RuntimeError("must-not-read")
        entity = _number(missing)
        missing.data.clear()
        with self.assertRaises(harness.HomeAssistantError):
            await entity.async_set_native_value(10)
        self.assertEqual(missing.client.methods, [])
        self.assertEqual(missing.client.bodies, [])
        self.assertEqual(missing.refreshes, 0)

    async def test_stale_empty_cache_uses_fresh_enabled_pair(self) -> None:
        cached = harness.make_device()
        fresh = harness.make_device(
            configuration={
                "timezone": "-05:00",
                "dndFrom": "22:15:00",
                "dndTo": "02:45:09",
                "catDelay": 600,
                "mode": 1,
                "manual": 0,
                "volumeLevel": 3,
                "autoLock": 300,
                "schedule": [{"hour": 7, "minute": 30, "time": "07:30:00"}],
            }
        )
        before = _snapshot(cached)
        coordinator = harness._Coordinator(cached)
        coordinator.client.fresh_devices = [fresh]
        entity = _number(coordinator)
        await entity.async_set_native_value(15.0)
        body = coordinator.client.bodies[0]
        fresh_from = fresh.configuration.model_extra["dndFrom"]
        fresh_to = fresh.configuration.model_extra["dndTo"]
        self.assertEqual(coordinator.client.methods, ["get_devices", "update_configuration"])
        self.assertIs(body["dndFrom"], fresh_from)
        self.assertIs(body["dndTo"], fresh_to)
        self.assertEqual(body["catDelay"], 900)
        self.assertEqual(
            set(body), {"device_id", "dndFrom", "dndTo", "catDelay"}
        )
        for key in ("mode", "manual", "schedule", "volumeLevel", "autoLock", "timezone"):
            self.assertNotIn(key, body)
        self.assertIs(coordinator.data["settings-device"], cached)
        self.assertEqual(_snapshot(cached), before)
        self.assertEqual(coordinator.refreshes, 1)
        self.assertEqual(coordinator.client.methods.count("get_devices"), 1)

    async def test_fresh_disabled_empty_pair_is_preserved(self) -> None:
        cached = harness.make_device(
            configuration={"dndFrom": "22:15:00", "dndTo": "02:45:09"}
        )
        fresh = harness.make_device(configuration={"dndFrom": "", "dndTo": ""})
        before = _snapshot(cached)
        coordinator = harness._Coordinator(cached)
        coordinator.client.fresh_devices = [fresh]
        await _number(coordinator).async_set_native_value(10.0)
        body = coordinator.client.bodies[0]
        self.assertEqual(body["dndFrom"], "")
        self.assertEqual(body["dndTo"], "")
        self.assertIs(body["dndFrom"], fresh.configuration.model_extra["dndFrom"])
        self.assertIs(body["dndTo"], fresh.configuration.model_extra["dndTo"])
        self.assertNotEqual(body["dndFrom"], cached.configuration.model_extra["dndFrom"])
        self.assertEqual(body["catDelay"], 600)
        self.assertEqual(_snapshot(cached), before)
        self.assertIs(coordinator.data["settings-device"], cached)
        self.assertEqual(coordinator.client.methods, ["get_devices", "update_configuration"])
        self.assertEqual(coordinator.refreshes, 1)

    async def test_fresh_invalid_missing_or_read_error_does_not_put(self) -> None:
        cached = harness.make_device()
        before = _snapshot(cached)
        cases = (
            harness.make_device(configuration={"dndFrom": "", "dndTo": "06:00:00"}),
            harness.make_device(configuration={"dndFrom": "0\u0661:00:00", "dndTo": "01:00:00"}),
            harness.make_device(omit_configuration=("catDelay",)),
            harness.make_device(reportedStatus="disconnected"),
            harness.make_device(manufacturerId="other-device"),
        )
        for fresh in cases:
            with self.subTest(fresh=fresh.manufacturer_id):
                coordinator = harness._Coordinator(cached)
                coordinator.client.fresh_devices = [fresh]
                with self.assertRaises(harness.HomeAssistantError):
                    await _number(coordinator).async_set_native_value(10)
                self.assertEqual(coordinator.client.bodies, [])
                self.assertEqual(coordinator.client.methods, ["get_devices"])
                self.assertEqual(coordinator.refreshes, 0)
                self.assertIs(coordinator.data["settings-device"], cached)
                self.assertEqual(_snapshot(cached), before)

        empty = harness._Coordinator(cached)
        empty.client.fresh_devices = []
        with self.assertRaises(harness.HomeAssistantError):
            await _number(empty).async_set_native_value(10)
        self.assertEqual(empty.client.bodies, [])
        self.assertEqual(empty.client.methods, ["get_devices"])
        self.assertEqual(empty.refreshes, 0)

        failed = harness._Coordinator(cached)
        failed.client.read_error = harness.CatGenieAuthenticationError("Bearer secret-token")
        with self.assertRaises(harness.HomeAssistantError) as raised:
            await _number(failed).async_set_native_value(10)
        message = str(raised.exception)
        self.assertIn("CatGenieAuthenticationError", message)
        self.assertNotIn("secret-token", message)
        self.assertNotIn("Bearer", message)
        self.assertEqual(failed.client.methods, ["get_devices"])
        self.assertEqual(failed.client.bodies, [])
        self.assertEqual(failed.refreshes, 0)
        self.assertEqual(_snapshot(cached), before)

    async def test_other_number_controls_do_not_read_devices(self) -> None:
        coordinator = harness._Coordinator(harness.make_device())
        coordinator.client.read_error = RuntimeError("secret-token")
        for key, value in (("volume", 4), ("auto_lock_timeout", 10)):
            description = next(item for item in harness.NUMBERS if item.key == key)
            entity = harness.CatGenieNumber(coordinator, "settings-device", description)
            await entity.async_set_native_value(value)
        self.assertEqual(
            coordinator.client.methods,
            ["update_configuration", "update_configuration"],
        )
        self.assertNotIn("get_devices", coordinator.client.methods)
        self.assertNotIn("secret-token", str(coordinator.client.bodies))

    def test_get_devices_call_matches_pinned_client_and_is_outside_refresh(self) -> None:
        library = inspect.signature(harness.CatGenieClient.get_devices)
        self.assertEqual(list(library.parameters), ["self"])
        client_tree = ast.parse((INTEGRATION / "client.py").read_text())
        args = None
        for node in client_tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name != "HomeAssistantCatGenieClient":
                continue
            for item in node.body:
                if isinstance(item, ast.AsyncFunctionDef) and item.name == "get_devices":
                    args = [arg.arg for arg in item.args.args]
        self.assertEqual(args, ["self"])
        number_src = (INTEGRATION / "number.py").read_text()
        self.assertEqual(number_src.count("await self.coordinator.client.get_devices()"), 1)
        setter = number_src.split("async def async_set_native_value", 1)[1]
        before_command, command = setter.split("async def _command", 1)
        self.assertIn("get_devices()", before_command)
        self.assertNotIn("get_devices", command.split("await async_run_command", 1)[0])
        self.assertIn(
            "not a remote compare-and-swap",
            " ".join(number_src.split()),
        )
        self.assertNotIn("coordinator.data[", number_src)
        self.assertNotIn("update_interval", number_src)
        config_src = (INTEGRATION / "configuration.py").read_text()
        clock = config_src.split("_WIRE_CLOCK", 1)[1].split("def stored_cat_delay_seconds", 1)[0]
        self.assertIn("[0-9]", clock)
        self.assertIn("re.ASCII", clock)
        self.assertNotIn("\\d", clock)


if __name__ == "__main__":
    unittest.main()
