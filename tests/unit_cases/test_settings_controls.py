"""SYNTHETIC settings-write regressions. Not live vendor or device results.

Payloads use the real CatGenie models. Home Assistant and HTTP are stubbed.
A successful PUT acknowledgement is not treated as proof the device applied it.
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import sys
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch as mock_patch

CANDIDATE = Path(__file__).resolve().parents[2]
DEPENDENCY = os.environ.get("CATGENIE_TEST_DEPENDENCY")
INTEGRATION = CANDIDATE / "custom_components" / "catgenie"
FIXTURE = "SYNTHETIC"


def _stub(name: str, **attrs: object) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


class _Subscriptable:
    def __class_getitem__(cls, item: object) -> type:
        return cls


def _install_import_seams() -> None:
    curl = _stub("curl_cffi")
    requests = _stub("curl_cffi.requests", AsyncSession=object, Response=object)
    curl.requests = requests
    crypto = _stub("Crypto")
    cipher = _stub("Crypto.Cipher", AES=object)
    util = _stub("Crypto.Util")
    _stub("Crypto.Util.Padding", pad=lambda *args, **kwargs: b"")
    crypto.Cipher = cipher
    crypto.Util = util

    @dataclass(frozen=True, kw_only=True)
    class SelectEntityDescription:
        key: str
        translation_key: str | None = None
        entity_category: object = None
        options: list | None = None

    @dataclass(frozen=True, kw_only=True)
    class NumberEntityDescription:
        key: str
        translation_key: str | None = None
        entity_category: object = None
        native_min_value: float | None = None
        native_max_value: float | None = None
        native_step: float | None = None
        mode: object = None
        native_unit_of_measurement: object = None

    class EntityCategory:
        CONFIG = "config"
        DIAGNOSTIC = "diagnostic"

    class NumberMode:
        BOX = "box"
        SLIDER = "slider"
        AUTO = "auto"

    class Platform:
        BINARY_SENSOR = "binary_sensor"
        BUTTON = "button"
        NUMBER = "number"
        SELECT = "select"
        SENSOR = "sensor"
        SWITCH = "switch"

    class CoordinatorEntity(_Subscriptable):
        def __init__(self, coordinator: object) -> None:
            self.coordinator = coordinator

        @property
        def available(self) -> bool:
            return True

    class DeviceInfo(dict):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)

    ha = _stub("homeassistant")
    const = _stub(
        "homeassistant.const",
        EntityCategory=EntityCategory,
        Platform=Platform,
        PERCENTAGE="%",
        UnitOfTime=types.SimpleNamespace(SECONDS="s", MINUTES="min"),
    )
    _stub("homeassistant.core", HomeAssistant=object)
    _stub("homeassistant.config_entries", ConfigEntry=_Subscriptable)
    exceptions = _stub(
        "homeassistant.exceptions",
        ConfigEntryAuthFailed=type("ConfigEntryAuthFailed", (Exception,), {}),
        HomeAssistantError=type("HomeAssistantError", (Exception,), {}),
    )
    _stub(
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=_Subscriptable,
        UpdateFailed=type("UpdateFailed", (Exception,), {}),
        CoordinatorEntity=CoordinatorEntity,
    )
    _stub(
        "homeassistant.helpers.device_registry",
        CONNECTION_NETWORK_MAC="mac",
        DeviceInfo=DeviceInfo,
        format_mac=lambda mac: mac,
    )
    _stub("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
    components = _stub("homeassistant.components")
    select = _stub(
        "homeassistant.components.select",
        SelectEntity=object,
        SelectEntityDescription=SelectEntityDescription,
    )
    number = _stub(
        "homeassistant.components.number",
        NumberEntity=object,
        NumberEntityDescription=NumberEntityDescription,
        NumberMode=NumberMode,
    )
    helpers = _stub("homeassistant.helpers")
    ha.const = const
    ha.exceptions = exceptions
    ha.components = components
    ha.helpers = helpers
    components.select = select
    components.number = number
    helpers.update_coordinator = sys.modules["homeassistant.helpers.update_coordinator"]
    helpers.device_registry = sys.modules["homeassistant.helpers.device_registry"]
    helpers.entity_platform = sys.modules["homeassistant.helpers.entity_platform"]


_SEAM_PREFIXES = ("homeassistant", "curl_cffi", "Crypto", "custom_components")
_MODULES_BEFORE = {
    name: module
    for name, module in sys.modules.items()
    if any(name == prefix or name.startswith(prefix + ".") for prefix in _SEAM_PREFIXES)
}
_PATH_BEFORE = tuple(sys.path)
_paths = [str(CANDIDATE), *([DEPENDENCY] if DEPENDENCY else []), *sys.path]
with mock_patch.dict(sys.modules), mock_patch.object(sys, "path", _paths):
    for _name in tuple(sys.modules):
        if _name == "custom_components" or _name.startswith("custom_components.catgenie"):
            del sys.modules[_name]
    _install_import_seams()
    from catgenie import CatGenieClient, CleaningMode, Credentials
    from catgenie.exceptions import CatGenieAuthenticationError, CatGenieException
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.catgenie.configuration import (
        ACTIVATION_OPTIONS,
        VOLUME_MAX,
        VOLUME_MIN,
        SettingsWriteRefused,
        activation_label,
        activation_payload,
        display_volume,
        volume_payload,
    )
    from custom_components.catgenie.number import NUMBERS, CatGenieNumber
    from custom_components.catgenie.operation_state import TolerantDevice
    from custom_components.catgenie.select import SELECTS, CatGenieSelect

_MODULES_AFTER = {
    name: module
    for name, module in sys.modules.items()
    if any(name == prefix or name.startswith(prefix + ".") for prefix in _SEAM_PREFIXES)
}
_PATH_AFTER = tuple(sys.path)

NESTED_KEYS = (
    "schedule",
    "binaryElements",
    "dndFrom",
    "dndTo",
    "catDelay",
    "autoLock",
    "volumeLevel",
    "childLock",
    "extraDry",
    "heater",
    "water",
    "pumpPctT",
    "catSense",
    "timezone",
    "manufacturerId",
)


def device_payload(**overrides: object) -> dict:
    """SYNTHETIC device. Schedule and nested siblings are present so writes can omit them."""
    configuration = {
        "mode": 0,
        "manual": 0,
        "volumeLevel": 7,
        "schedule": [{"hour": 6, "minute": 0, "time": "06:00:00"}],
        "binaryElements": {"EXTRA_WASH": True, "EXTRA_SHAKE": False},
        "dndFrom": "",
        "dndTo": "",
        "catDelay": 1800,
        "autoLock": 0,
        "childLock": 1,
        "extraDry": True,
        "timezone": "-05:00",
        "pumpPctT": 100,
    }
    replacement = overrides.pop("configuration", {})
    if replacement is None:
        configuration = None
    else:
        configuration.update(replacement)
        for key in overrides.pop("omit_configuration", ()):
            configuration.pop(key, None)
    payload = {
        "_fixture": FIXTURE,
        "manufacturerId": "settings-device",
        "name": "SYNTHETIC-settings",
        "macAddress": "aa:bb:cc:dd:ee:ff",
        "hwRevision": "1",
        "fwVersion": "8.7.205R",
        "reportedStatus": "connected",
        "operationStatus": {"state": 0, "progress": 255, "error": ""},
        "configuration": configuration,
    }
    payload.update(overrides)
    return payload


def make_device(**overrides: object) -> TolerantDevice:
    return TolerantDevice.model_validate(device_payload(**overrides))


class _Client:
    def __init__(self) -> None:
        self.bodies: list[dict] = []
        self.methods: list[str] = []
        self.error: Exception | None = None
        self.ack: dict = {"accepted": True, "mode": 2}
        # Explicit fresh snapshot for get_devices(). None is not a network call.
        self.fresh_devices: list | None = None
        self.read_error: Exception | None = None

    async def get_devices(self) -> list:
        """Pinned stand-in: CatGenieClient.get_devices(self) -> list[Device].

        No network. Callers must set ``fresh_devices`` or ``read_error``.
        """
        self.methods.append("get_devices")
        if self.read_error is not None:
            raise self.read_error
        if self.fresh_devices is None:
            raise AssertionError("fresh devices were not configured")
        return list(self.fresh_devices)

    async def update_configuration(self, device_id: str, **body: object) -> dict:
        self.methods.append("update_configuration")
        self.bodies.append({"device_id": device_id, **body})
        if self.error:
            raise self.error
        return dict(self.ack)

    async def set_cleaning_mode(self, device_id: str, mode: object) -> dict:
        self.methods.append("set_cleaning_mode")
        raise AssertionError("library set_cleaning_mode must not be used")

    async def set_volume(self, device_id: str, level: object) -> dict:
        self.methods.append("set_volume")
        raise AssertionError("unbounded library set_volume must not be used")

    async def set_schedule(self, *args: object, **kwargs: object) -> dict:
        raise AssertionError("schedule must not be created or rewritten")

    async def set_cat_delay(self, *args: object, **kwargs: object) -> dict:
        raise AssertionError("cat delay is not a proven control")

    async def set_auto_lock(self, *args: object, **kwargs: object) -> dict:
        raise AssertionError("library set_auto_lock must not be used; write autoLock only")


class _Coordinator:
    def __init__(self, device: TolerantDevice) -> None:
        self.data = {device.manufacturer_id: device}
        self.client = _Client()
        # Same object the cache holds, unless a test replaces the snapshot.
        self.client.fresh_devices = [device]
        self.refreshes = 0

    async def async_request_refresh(self) -> None:
        self.refreshes += 1


def _select(coordinator: _Coordinator) -> CatGenieSelect:
    description = next(item for item in SELECTS if item.key == "activation_mode")
    return CatGenieSelect(coordinator, "settings-device", description)


def _number(coordinator: _Coordinator) -> CatGenieNumber:
    description = next(item for item in NUMBERS if item.key == "volume")
    return CatGenieNumber(coordinator, "settings-device", description)


class SettingsPayloadTests(unittest.TestCase):
    def test_import_seams_restore(self) -> None:
        self.assertEqual(_MODULES_AFTER, _MODULES_BEFORE)
        self.assertEqual(_PATH_AFTER, _PATH_BEFORE)

    def test_observed_pairs_are_labels_not_presentation_enums(self) -> None:
        self.assertEqual(ACTIVATION_OPTIONS, ("cat", "manual", "time"))
        for mode, manual, label in ((0, 0, "cat"), (0, 1, "manual"), (1, 0, "time")):
            with self.subTest(mode=mode, manual=manual):
                self.assertEqual(
                    activation_label(make_device(configuration={"mode": mode, "manual": manual})),
                    label,
                )
        presentation = make_device()
        presentation.configuration = presentation.configuration.model_copy(update={"mode": 2})
        self.assertIsNone(activation_label(presentation))
        self.assertIsNone(activation_label(make_device(configuration={"mode": 0, "manual": 2})))

    def test_manual_preserves_existing_mode_and_pairs_both_fields(self) -> None:
        from_cat = activation_payload(make_device(), "manual")
        from_time = activation_payload(
            make_device(configuration={"mode": 1, "manual": 0}), "manual"
        )
        self.assertEqual(from_cat, {"mode": 0, "manual": 1})
        self.assertEqual(from_time, {"mode": 1, "manual": 1})
        self.assertNotIn(2, from_time.values())

    def test_cat_and_time_are_explicit_pairs_not_library_manual(self) -> None:
        device = make_device(configuration={"mode": 1, "manual": 1, "volumeLevel": 7})
        self.assertEqual(activation_payload(device, "cat"), {"mode": 0, "manual": 0})
        self.assertEqual(activation_payload(device, "time"), {"mode": 1, "manual": 0})
        self.assertNotEqual(activation_payload(device, "manual"), {"mode": 1})

    def test_payloads_omit_schedule_and_nested_siblings(self) -> None:
        device = make_device()
        for option in ACTIVATION_OPTIONS:
            payload = activation_payload(device, option)
            with self.subTest(option=option):
                self.assertEqual(set(payload), {"mode", "manual"})
                for key in NESTED_KEYS:
                    self.assertNotIn(key, payload)
                self.assertNotIn("schedule", payload)
                self.assertIsInstance(payload["mode"], int)
                self.assertIsInstance(payload["manual"], int)
                self.assertNotIsInstance(payload["mode"], bool)
        volume = volume_payload(device, 3)
        self.assertEqual(volume, {"volumeLevel": 3})
        self.assertEqual(set(volume), {"volumeLevel"})

    def test_guards_refuse_unknown_offline_and_incomplete_config(self) -> None:

        incomplete_payload = device_payload()
        del incomplete_payload["configuration"]
        missing_config = TolerantDevice.model_validate(incomplete_payload)
        missing_mode = make_device(omit_configuration=("mode",))
        missing_manual = make_device(omit_configuration=("manual",))
        unknown_mode = make_device()
        unknown_mode.configuration = unknown_mode.configuration.model_copy(update={"mode": 99})
        cases = [
            make_device(reportedStatus="disconnected"),
            make_device(reportedStatus=""),
            missing_config,
            missing_mode,
            missing_manual,
            unknown_mode,
            make_device(configuration={"manual": True}),
            make_device(configuration={"manual": "1"}),
        ]
        for device in cases:
            with self.subTest(device=device.reported_status, fields=device.configuration.model_fields_set):
                for option in ("cat", "manual", "time", "0", "1", "2", "MANUAL"):
                    with self.assertRaises(SettingsWriteRefused):
                        activation_payload(device, option)
        self.assertIsNone(activation_label(missing_config))
        self.assertIsNone(activation_label(missing_mode))
        self.assertIsNone(activation_label(unknown_mode))


    def test_volume_accepts_only_app_library_range(self) -> None:
        device = make_device()
        self.assertEqual(VOLUME_MIN, 1)
        self.assertEqual(VOLUME_MAX, 7)
        for level in range(1, 8):
            self.assertEqual(volume_payload(device, level), {"volumeLevel": level})
            self.assertEqual(volume_payload(device, float(level)), {"volumeLevel": level})
        for bad in (0, 8, 100, -1, 1.5, True, False, "7", None, 7.1):
            with self.subTest(bad=bad):
                with self.assertRaises(SettingsWriteRefused):
                    volume_payload(device, bad)
        self.assertEqual(display_volume(device), 7)
        outside = make_device(configuration={"mode": 0, "manual": 0, "volumeLevel": 0})
        self.assertIsNone(display_volume(outside))
        self.assertEqual(volume_payload(outside, 2), {"volumeLevel": 2})

    def test_volume_refuses_defaulted_or_offline_readings(self) -> None:
        payload = device_payload(omit_configuration=("volumeLevel",))
        defaulted = TolerantDevice.model_validate(payload)
        self.assertEqual(defaulted.configuration.volume_level, 7)
        self.assertIsNone(display_volume(defaulted))
        with self.assertRaises(SettingsWriteRefused):
            volume_payload(defaulted, 7)
        with self.assertRaises(SettingsWriteRefused):
            volume_payload(make_device(reportedStatus="offline"), 4)


class LibraryPartialPutTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_update_configuration_sends_only_supplied_keys(self) -> None:
        captured: list[dict] = []

        class Recording(CatGenieClient):
            async def _request(self, method, path, body=None, params=None):
                captured.append({"method": method, "path": path, "body": body})
                return {"not": "vendor-validation"}

        client = Recording(Credentials(access_token="synthetic", token_expiration=10**12), session=object())
        device = make_device(configuration={"mode": 1, "manual": 0, "volumeLevel": 6})
        ack = await client.update_configuration("settings-device", **activation_payload(device, "manual"))
        volume_ack = await client.update_configuration(
            "settings-device", **volume_payload(device, 1)
        )
        library_manual = await client.set_cleaning_mode("settings-device", CleaningMode.MANUAL)
        self.assertEqual(ack["not"], "vendor-validation")
        self.assertEqual(volume_ack["not"], "vendor-validation")
        self.assertEqual(library_manual["not"], "vendor-validation")
        self.assertEqual(captured[0]["method"], "PUT")
        self.assertEqual(captured[0]["path"], "device/management/settings-device/configuration")
        self.assertEqual(captured[0]["body"], {"mode": 1, "manual": 1})
        self.assertEqual(captured[1]["body"], {"volumeLevel": 1})
        self.assertEqual(captured[2]["body"], {"mode": 1})
        self.assertNotEqual(captured[0]["body"], captured[2]["body"])


class SettingsEntityTests(unittest.IsolatedAsyncioTestCase):
    async def test_select_writes_pair_refreshes_once_and_reads_back_from_coordinator(self) -> None:
        coordinator = _Coordinator(make_device())
        entity = _select(coordinator)
        self.assertEqual(entity.current_option, "cat")
        self.assertEqual(entity.options, ["cat", "manual", "time"])
        self.assertEqual(entity._attr_unique_id, "settings-device_activation_mode")
        await entity.async_select_option("time")
        self.assertEqual(coordinator.refreshes, 1)
        self.assertEqual(coordinator.client.methods, ["update_configuration"])
        self.assertEqual(
            coordinator.client.bodies,
            [{"device_id": "settings-device", "mode": 1, "manual": 0}],
        )
        self.assertEqual(set(coordinator.client.bodies[0]) - {"device_id"}, {"mode", "manual"})
        # The acknowledgement is not vendor confirmation. The coordinator
        # snapshot stays on the previous poll; the select holds the request.
        self.assertEqual(activation_label(coordinator.data["settings-device"]), "cat")
        self.assertEqual(entity.current_option, "time")
        self.assertEqual(entity.extra_state_attributes, {"pending_confirmation": True})
        coordinator.data["settings-device"] = make_device(configuration={"mode": 1, "manual": 0, "volumeLevel": 7})
        self.assertEqual(entity.current_option, "time")
        self.assertIsNone(entity.extra_state_attributes)

    async def test_manual_from_time_keeps_mode_and_does_not_refresh_on_refusal(self) -> None:
        coordinator = _Coordinator(make_device(configuration={"mode": 1, "manual": 0, "volumeLevel": 5}))
        entity = _select(coordinator)
        await entity.async_select_option("manual")
        self.assertEqual(coordinator.client.bodies[0]["mode"], 1)
        self.assertEqual(coordinator.client.bodies[0]["manual"], 1)
        self.assertNotIn("schedule", coordinator.client.bodies[0])
        offline = _Coordinator(make_device(reportedStatus="disconnected"))
        with self.assertRaises(HomeAssistantError):
            await _select(offline).async_select_option("cat")
        self.assertEqual(offline.client.bodies, [])
        self.assertEqual(offline.refreshes, 0)

    async def test_failed_put_does_not_refresh_or_claim_readback(self) -> None:
        coordinator = _Coordinator(make_device())
        coordinator.client.error = CatGenieException("synthetic failure")
        with self.assertRaises(HomeAssistantError):
            await _select(coordinator).async_select_option("manual")
        self.assertEqual(coordinator.refreshes, 0)
        self.assertEqual(_select(coordinator).current_option, "cat")

    async def test_volume_number_is_bounded_and_refreshes_once(self) -> None:
        coordinator = _Coordinator(make_device())
        entity = _number(coordinator)
        self.assertEqual(entity.native_value, 7)
        self.assertEqual(entity.native_min_value, 1)
        self.assertEqual(entity.native_max_value, 7)
        self.assertEqual(entity.native_step, 1)
        self.assertEqual(entity.mode, "box")
        self.assertIsNone(entity.native_unit_of_measurement)
        self.assertNotEqual(entity._attr_unique_id, "settings-device_volume_level")
        await entity.async_set_native_value(4.0)
        self.assertEqual(coordinator.refreshes, 1)
        self.assertEqual(coordinator.client.bodies, [{"device_id": "settings-device", "volumeLevel": 4}])
        self.assertEqual(entity.device.configuration.volume_level, 7)
        self.assertEqual(entity.native_value, 4)
        self.assertIs(type(entity.native_value), int)
        self.assertEqual(entity.extra_state_attributes, {"pending_confirmation": True})
        coordinator.data["settings-device"] = make_device(configuration={"mode": 0, "manual": 0, "volumeLevel": 4})
        self.assertEqual(entity.native_value, 4)
        self.assertIsNone(entity.extra_state_attributes)
        for bad in (0, 8, 100, 1.5):
            refused = _Coordinator(make_device())
            with self.subTest(bad=bad):
                with self.assertRaises(HomeAssistantError):
                    await _number(refused).async_set_native_value(bad)
                self.assertEqual(refused.client.bodies, [])
                self.assertEqual(refused.refreshes, 0)

    def test_registered_numbers_keep_schedule_and_panel_lock_unwired(self) -> None:
        self.assertEqual([item.key for item in SELECTS], ["activation_mode"])
        self.assertEqual(
            [item.key for item in NUMBERS],
            ["volume", "auto_lock_timeout", "cat_activation_delay"],
        )
        tree = ast.parse((INTEGRATION / "__init__.py").read_text())
        platforms = []
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == "PLATFORMS":
                platforms = [elt.attr for elt in node.value.elts]
        self.assertEqual(platforms, ["BINARY_SENSOR", "BUTTON", "NUMBER", "SELECT", "SENSOR", "SWITCH"])
        translations = json.loads((INTEGRATION / "translations" / "en.json").read_text())
        self.assertEqual(
            translations["entity"]["select"]["activation_mode"]["state"],
            {"cat": "Cat activation", "manual": "Manual", "time": "Time activation"},
        )
        self.assertEqual(translations["entity"]["number"]["volume"]["name"], "Volume")
        self.assertEqual(
            translations["entity"]["number"]["cat_activation_delay"]["name"],
            "Cat activation delay",
        )
        self.assertNotIn("panel_lock_delay", translations["entity"].get("number", {}))
        for path in (INTEGRATION / "configuration.py", INTEGRATION / "select.py", INTEGRATION / "number.py"):
            ast.parse(path.read_text())


if __name__ == "__main__":
    unittest.main()
