"""SYNTHETIC offline regression for unrecognized CatGenie operation states.

Not live device, cloud, or Home Assistant results. Payloads are labeled
SYNTHETIC. State 2 is preserved as an integer; its fault reason is not asserted.
HTTP/HA seams are stubbed. Pydantic models and the integration adapter are real.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch as mock_patch

CANDIDATE = Path(__file__).resolve().parents[1]
# Optional extracted dependency for offline review; otherwise use the installed
# catgenie requirement. Do not tie upstream tests to a developer's filesystem.
DEPENDENCY = os.environ.get("CATGENIE_TEST_DEPENDENCY")
FIXTURE = "SYNTHETIC"

# Stable entity keys. Unique ids are "{manufacturer_id}_{key}".
SENSOR_KEYS = (
    "last_clean",
    "total_cycles",
    "cartridge_remaining",
    "cartridge_capacity",
    "operation_state",
    "operation_progress",
    "operation_error",
    "cleaning_mode",
    "scheduled_cycles",
    "cat_activation_delay",
    "panel_lock_delay",
    "cat_sensitivity",
    "volume_level",
    "network_type",
)
BINARY_KEYS = ("online", "cleaning", "low_heater", "fan_shutter")
FORBIDDEN_LABELS = ("running", "paused", "water_fill", "water-fill")


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
    """Stub missing HTTP/HA imports only. Do not stub pydantic or catgenie.models."""
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
    class SensorEntityDescription:
        key: str
        translation_key: str | None = None
        device_class: object = None
        options: list | None = None
        native_unit_of_measurement: object = None
        state_class: object = None
        entity_category: object = None
        suggested_unit_of_measurement: object = None
        entity_registry_enabled_default: bool = True

    @dataclass(frozen=True, kw_only=True)
    class BinarySensorEntityDescription:
        key: str
        translation_key: str | None = None
        device_class: object = None
        entity_category: object = None
        entity_registry_enabled_default: bool = True

    class SensorDeviceClass:
        TIMESTAMP = "timestamp"
        ENUM = "enum"
        DURATION = "duration"

    class SensorStateClass:
        TOTAL_INCREASING = "total_increasing"
        MEASUREMENT = "measurement"

    class BinarySensorDeviceClass:
        CONNECTIVITY = "connectivity"
        RUNNING = "running"

    class EntityCategory:
        DIAGNOSTIC = "diagnostic"

    class UnitOfTime:
        SECONDS = "s"
        MINUTES = "min"

    class Platform:
        BINARY_SENSOR = "binary_sensor"
        BUTTON = "button"
        SENSOR = "sensor"
        SWITCH = "switch"

    class CoordinatorEntity(_Subscriptable):
        def __init__(self, coordinator: object) -> None:
            self.coordinator = coordinator

        @property
        def available(self) -> bool:
            return True

    class DataUpdateCoordinator(_Subscriptable):
        pass

    class ConfigEntry(_Subscriptable):
        pass

    class DeviceInfo(dict):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)

    ha = _stub("homeassistant")
    const = _stub(
        "homeassistant.const",
        PERCENTAGE="%",
        EntityCategory=EntityCategory,
        UnitOfTime=UnitOfTime,
        Platform=Platform,
    )
    core = _stub("homeassistant.core", HomeAssistant=object)
    config_entries = _stub("homeassistant.config_entries", ConfigEntry=ConfigEntry)
    exceptions = _stub(
        "homeassistant.exceptions",
        ConfigEntryAuthFailed=Exception,
        HomeAssistantError=Exception,
    )
    update_coordinator = _stub(
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=DataUpdateCoordinator,
        UpdateFailed=Exception,
        CoordinatorEntity=CoordinatorEntity,
    )
    device_registry = _stub(
        "homeassistant.helpers.device_registry",
        CONNECTION_NETWORK_MAC="mac",
        DeviceInfo=DeviceInfo,
        format_mac=lambda mac: mac,
    )
    entity_platform = _stub(
        "homeassistant.helpers.entity_platform",
        AddEntitiesCallback=object,
    )
    typing_mod = _stub("homeassistant.helpers.typing", StateType=object)
    components = _stub("homeassistant.components")
    sensor = _stub(
        "homeassistant.components.sensor",
        SensorDeviceClass=SensorDeviceClass,
        SensorEntity=object,
        SensorEntityDescription=SensorEntityDescription,
        SensorStateClass=SensorStateClass,
    )
    binary = _stub(
        "homeassistant.components.binary_sensor",
        BinarySensorDeviceClass=BinarySensorDeviceClass,
        BinarySensorEntity=object,
        BinarySensorEntityDescription=BinarySensorEntityDescription,
    )
    helpers = _stub("homeassistant.helpers")
    ha.const = const
    ha.core = core
    ha.config_entries = config_entries
    ha.exceptions = exceptions
    ha.components = components
    ha.helpers = helpers
    components.sensor = sensor
    components.binary_sensor = binary
    helpers.update_coordinator = update_coordinator
    helpers.device_registry = device_registry
    helpers.entity_platform = entity_platform
    helpers.typing = typing_mod


# Import the actual adapter against temporary framework/HTTP seams. Restore
# module registrations and the import path so other test suites are not poisoned.
_SEAM_PREFIXES = ("homeassistant", "curl_cffi", "Crypto", "custom_components")


def _seam_modules() -> dict[str, types.ModuleType]:
    return {
        name: module
        for name, module in sys.modules.items()
        if any(name == prefix or name.startswith(prefix + ".") for prefix in _SEAM_PREFIXES)
    }


_MODULES_BEFORE = _seam_modules()
_PATH_BEFORE = tuple(sys.path)
_paths = [str(CANDIDATE), *([DEPENDENCY] if DEPENDENCY else []), *sys.path]
with mock_patch.dict(sys.modules), mock_patch.object(sys, "path", _paths):
    # Do not accidentally reuse an adapter imported earlier by another suite.
    for _name in tuple(sys.modules):
        if _name == "custom_components" or _name.startswith("custom_components.catgenie"):
            del sys.modules[_name]
    _install_import_seams()

    from catgenie.models import Device, OperationState
    from pydantic import ValidationError

    from custom_components.catgenie.binary_sensor import (
        BINARY_SENSORS,
        CatGenieBinarySensor,
    )
    from custom_components.catgenie.client import (
        HomeAssistantCatGenieClient,
        _normalize_thing,
    )
    from custom_components.catgenie.operation_state import (
        TolerantDevice,
        TolerantOperationStatus,
        cleaning_known,
        operation_state_label,
    )
    from custom_components.catgenie.sensor import SENSORS, CatGenieSensor
    from catgenie.auth import Credentials

_MODULES_AFTER = _seam_modules()
_PATH_AFTER = tuple(sys.path)


def thing(
    manufacturer_id: str,
    state: object,
    *,
    progress: int = 40,
    error: str = "",
    active_errors: list | None = None,
    schedule: list | None = None,
) -> dict:
    """Build one SYNTHETIC device payload. Not a captured live response."""
    payload: dict = {
        "_fixture": FIXTURE,
        "manufacturerId": manufacturer_id,
        "name": f"{FIXTURE}-{manufacturer_id}",
        "macAddress": "aa:bb:cc:dd:ee:ff",
        "hwRevision": "1",
        "fwVersion": "8.7.205R",
        "reportedStatus": "connected",
        "operationStatus": {
            "state": state,
            "progress": progress,
            "error": error,
        },
        "activeErrors": [] if active_errors is None else active_errors,
    }
    if schedule is not None:
        payload["configuration"] = {"schedule": schedule}
    return payload


def _sensor(key: str):
    return next(item for item in SENSORS if item.key == key)


def _binary(key: str):
    return next(item for item in BINARY_SENSORS if item.key == key)


class _Coordinator:
    def __init__(self, devices: dict) -> None:
        self.data = devices


def _entities(devices: list[TolerantDevice]):
    coordinator = _Coordinator({device.manufacturer_id: device for device in devices})
    sensors = [
        CatGenieSensor(coordinator, device.manufacturer_id, _sensor("operation_state"))
        for device in devices
    ]
    progress = [
        CatGenieSensor(coordinator, device.manufacturer_id, _sensor("operation_progress"))
        for device in devices
    ]
    errors = [
        CatGenieSensor(coordinator, device.manufacturer_id, _sensor("operation_error"))
        for device in devices
    ]
    cleaning = [
        CatGenieBinarySensor(coordinator, device.manufacturer_id, _binary("cleaning"))
        for device in devices
    ]
    return sensors, progress, errors, cleaning


class UnknownOperationStateTests(unittest.TestCase):
    """SYNTHETIC red baseline and green candidate coverage."""

    def test_missing_cartridge_active_error_five_with_idle_state(self) -> None:
        device = TolerantDevice.model_validate(thing("cartridge", 0, active_errors=[5]))
        states, _, errors, cleaning = _entities([device])
        self.assertEqual(errors[0].native_value, "Cleaning solution cartridge missing")
        self.assertEqual(errors[0].extra_state_attributes, {"active_errors": [5]})
        self.assertEqual(states[0].native_value, "idle")
        self.assertEqual(states[0].extra_state_attributes["raw_state"], 0)
        self.assertIs(cleaning[0].is_on, False)

    def test_operation_state_five_is_not_cartridge_error_five(self) -> None:
        device = TolerantDevice.model_validate(thing("different-domain", 5))
        states, _, errors, _ = _entities([device])
        self.assertEqual(states[0].native_value, "error")
        self.assertEqual(errors[0].native_value, "Error reported (operation state: 5)")

    def test_unknown_active_error_remains_visible(self) -> None:
        device = TolerantDevice.model_validate(thing("unknown", 0, active_errors=[99]))
        _, _, errors, _ = _entities([device])
        self.assertEqual(errors[0].native_value, "Unknown error code: 99")
        self.assertEqual(errors[0].extra_state_attributes["active_errors"], [99])

    def test_mixed_codes_do_not_hide_unknown_errors(self) -> None:
        device = TolerantDevice.model_validate(thing("mixed", 0, active_errors=[5, 99]))
        _, _, errors, _ = _entities([device])
        self.assertEqual(errors[0].native_value, "Cleaning solution cartridge missing; Unknown error code: 99")
        self.assertEqual(errors[0].extra_state_attributes["active_errors"], [5, 99])

    def test_vendor_error_text_takes_precedence(self) -> None:
        device = TolerantDevice.model_validate(thing("text", 0, error="Vendor detail", active_errors=[5]))
        _, _, errors, _ = _entities([device])
        self.assertEqual(errors[0].native_value, "Vendor detail")
        self.assertEqual(errors[0].extra_state_attributes["active_errors"], [5])

    def test_empty_and_malformed_codes_are_not_invented_mappings(self) -> None:
        for active, expected in [([], "No active errors"), (["5"], "Unknown error code: 5"), ([True], "Unknown error code: True"), ([5.0], "Unknown error code: 5.0")]:
            with self.subTest(active=active):
                device = TolerantDevice.model_validate(thing("typed", 0, active_errors=active))
                self.assertEqual(_entities([device])[2][0].native_value, expected)

    def test_import_seams_restore_modules_and_search_path(self) -> None:
        self.assertEqual(_MODULES_AFTER, _MODULES_BEFORE)
        self.assertEqual(_PATH_AFTER, _PATH_BEFORE)

    def test_known_code_coercions_are_deliberately_rejected(self) -> None:
        for value in ("0", "1", 0.0, 1.0, False, True):
            with self.subTest(value=value):
                payload = thing("coercion", value)
                self.assertEqual(Device.model_validate(payload).operation_status.state, int(value))
                with self.assertRaises(ValidationError):
                    TolerantDevice.model_validate(payload)

    def test_omitted_operation_status_keeps_dependency_defaults(self) -> None:
        payload = thing("defaults", 0)
        del payload["operationStatus"]
        stock = Device.model_validate(payload)
        candidate = TolerantDevice.model_validate(payload)
        self.assertEqual(candidate.operation_status.state, 0)
        self.assertEqual(candidate.operation_status.progress, 255)
        self.assertEqual(
            candidate.model_dump(mode="json", by_alias=True),
            stock.model_dump(mode="json", by_alias=True),
        )

    def test_operation_status_aliases_and_inherited_fields(self) -> None:
        for field_name in ("operationStatus", "operation_status"):
            with self.subTest(field_name=field_name):
                payload = thing("aliases", 2, progress=17)
                operation = payload.pop("operationStatus")
                operation.update({
                    "stepNum": 7,
                    "relayMode": 3,
                    "sens": "SYNTHETIC-CAT",
                    "extraStatusField": {"value": "kept"},
                })
                payload[field_name] = operation
                candidate = TolerantDevice.model_validate(payload)
                self.assertEqual(candidate.operation_status.step_num, 7)
                self.assertEqual(candidate.operation_status.relay_mode, 3)
                self.assertTrue(candidate.operation_status.is_cat_detected)
                serialized = candidate.model_dump(mode="json", by_alias=True)["operationStatus"]
                self.assertEqual(serialized["state"], 2)
                self.assertEqual(serialized["progress"], 17)
                self.assertEqual(serialized["stepNum"], 7)
                self.assertEqual(serialized["relayMode"], 3)
                self.assertEqual(serialized["extraStatusField"], {"value": "kept"})


    def test_synthetic_red_baseline_stock_device_rejects_state_2(self) -> None:
        payload = thing("red-2", 2, error="WATER FILL ISSUE")
        with self.assertRaises(ValidationError) as caught:
            Device.model_validate(payload)
        message = str(caught.exception)
        self.assertIn("operationStatus", message)
        self.assertIn("state", message)
        self.assertIn("0 or 1", message)
        self.assertEqual(list(OperationState), [OperationState.IDLE, OperationState.RUNNING])
        self.assertFalse(
            any(member.value == 2 for member in OperationState),
            "dependency enum must stay 0/1; do not monkeypatch it",
        )

    def test_synthetic_nested_instance_into_stock_device_keeps_integer(self) -> None:
        """Prove, do not assume, that a tolerant instance can ride inside Device."""
        operation = TolerantOperationStatus.model_validate(
            {"state": 2, "progress": 40, "error": "WATER FILL ISSUE"}
        )
        self.assertIs(type(operation.state), int)
        self.assertEqual(operation.state, 2)
        payload = thing("nested", 0)
        payload["operationStatus"] = operation
        device = Device.model_validate(payload)
        self.assertIsInstance(device.operation_status, TolerantOperationStatus)
        self.assertIs(type(device.operation_status.state), int)
        self.assertEqual(device.operation_status.state, 2)
        self.assertEqual(device.operation_status.progress, 40)
        self.assertEqual(device.operation_status.error, "WATER FILL ISSUE")
        self.assertNotEqual(device.operation_status.state, OperationState.IDLE)
        self.assertNotEqual(device.operation_status.state, OperationState.RUNNING)

    def test_synthetic_green_tolerant_device_preserves_state_2_and_other_ints(self) -> None:
        for code in (2, -1, 3, 99, 255):
            with self.subTest(code=code):
                device = TolerantDevice.model_validate(
                    thing(f"green-{code}", code, progress=17, error="kept")
                )
                self.assertIsInstance(device, Device)
                self.assertIs(type(device.operation_status), TolerantOperationStatus)
                self.assertIs(type(device.operation_status.state), int)
                self.assertEqual(device.operation_status.state, code)
                self.assertEqual(operation_state_label(code), "error")
                self.assertIsNone(cleaning_known(code))
                self.assertNotIn(operation_state_label(code), FORBIDDEN_LABELS)
                self.assertFalse(device.is_cleaning)
                self.assertEqual(device.operation_status.error, "kept")
                self.assertEqual(device.operation_status.clean_progress_pct, 17)

    def test_synthetic_known_states_0_and_1_stay_idle_and_cleaning(self) -> None:
        idle = TolerantDevice.model_validate(thing("idle", 0, progress=255, error=""))
        cleaning = TolerantDevice.model_validate(
            thing("run", 1, progress=12, error="")
        )
        self.assertEqual(idle.operation_status.state, 0)
        self.assertEqual(operation_state_label(idle.operation_status.state), "idle")
        self.assertIs(cleaning_known(idle.operation_status.state), False)
        self.assertFalse(idle.is_cleaning)
        self.assertIsNone(idle.operation_status.clean_progress_pct)
        self.assertEqual(cleaning.operation_status.state, 1)
        self.assertEqual(operation_state_label(cleaning.operation_status.state), "cleaning")
        self.assertIs(cleaning_known(cleaning.operation_status.state), True)
        self.assertTrue(cleaning.is_cleaning)
        self.assertEqual(cleaning.operation_status.clean_progress_pct, 12)

    def test_synthetic_malformed_state_refused(self) -> None:
        for bad in ("2", "idle", None, True, False, 2.0, 1.0, [], {}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    TolerantDevice.model_validate(thing("bad", bad))
                with self.assertRaises(ValidationError):
                    TolerantOperationStatus.model_validate(
                        {"state": bad, "progress": 0}
                    )

    def test_synthetic_error_progress_and_active_errors_retained(self) -> None:
        class Weird:
            def __str__(self) -> str:
                return "weird-synthetic"

        active = [{"code": "E2", "text": "WATER FILL ISSUE"}, Weird()]
        device = TolerantDevice.model_validate(
            thing(
                "retain",
                2,
                progress=40,
                error="WATER FILL ISSUE",
                active_errors=active,
            )
        )
        sensors, progress, errors, cleaning = _entities([device])
        self.assertEqual(sensors[0].native_value, "error")
        self.assertEqual(sensors[0].extra_state_attributes["raw_state"], 2)
        self.assertEqual(
            sensors[0].extra_state_attributes["active_errors"][0],
            {"code": "E2", "text": "WATER FILL ISSUE"},
        )
        self.assertEqual(
            sensors[0].extra_state_attributes["active_errors"][1],
            "weird-synthetic",
        )
        self.assertEqual(progress[0].native_value, 40)
        self.assertEqual(errors[0].native_value, "WATER FILL ISSUE")
        self.assertEqual(errors[0].extra_state_attributes["active_errors"][0]["code"], "E2")
        self.assertIsNone(cleaning[0].is_on)
        encoded = json.dumps(sensors[0].extra_state_attributes)
        self.assertIn('"raw_state": 2', encoded)
        self.assertNotIn(sensors[0].native_value, {"idle", "cleaning", *FORBIDDEN_LABELS})

    def test_synthetic_schedule_normalization_still_runs_before_validate(self) -> None:
        raw = thing("sched", 2, schedule=["06:00:00", {"hour": 7, "minute": 30}])
        with self.assertRaises(ValidationError):
            TolerantDevice.model_validate(raw)
        normalized = _normalize_thing(raw)
        device = TolerantDevice.model_validate(normalized)
        first, second = device.configuration.schedule
        self.assertEqual(first.hour, 6)
        self.assertEqual(first.minute, 0)
        self.assertEqual(first.model_extra["time"], "06:00:00")
        self.assertEqual(second.hour, 7)
        self.assertEqual(second.minute, 30)
        self.assertEqual(device.operation_status.state, 2)

    def test_synthetic_get_devices_mixed_availability_and_request_shape(self) -> None:
        things = [
            thing("unknown-2", 2, progress=40, error="WATER FILL ISSUE", active_errors=[{"code": "raw"}]),
            thing("idle-0", 0, progress=255, schedule=["06:00:00"]),
            thing("run-1", 1, progress=8),
        ]
        calls: list[tuple] = []

        async def fake_request(method, path, body=None, params=None):
            calls.append((method, path, body, params))
            return {"thingList": things}

        client = HomeAssistantCatGenieClient(Credentials())
        client._request = fake_request
        devices = asyncio.run(client.get_devices())
        self.assertEqual(calls, [("GET", "device/device/v2", None, {"useFleetIndexAndGetRealConnectivity": "true"})])
        self.assertEqual([device.manufacturer_id for device in devices], ["unknown-2", "idle-0", "run-1"])
        self.assertTrue(all(isinstance(device, TolerantDevice) for device in devices))
        self.assertEqual(devices[0].operation_status.state, 2)
        self.assertEqual(devices[1].configuration.schedule[0].hour, 6)
        sensors, progress, errors, cleaning = _entities(devices)
        self.assertTrue(all(entity.available for entity in (*sensors, *cleaning)))
        self.assertEqual([entity.native_value for entity in sensors], ["error", "idle", "cleaning"])
        self.assertEqual([entity.extra_state_attributes["raw_state"] for entity in sensors], [2, 0, 1])
        self.assertEqual([entity.is_on for entity in cleaning], [None, False, True])
        self.assertEqual(progress[0].native_value, 40)
        self.assertIsNone(progress[1].native_value)
        self.assertEqual(errors[0].native_value, "WATER FILL ISSUE")
        self.assertEqual(errors[0].extra_state_attributes["active_errors"], [{"code": "raw"}])
        self.assertEqual(sensors[0]._attr_unique_id, "unknown-2_operation_state")
        self.assertEqual(cleaning[0]._attr_unique_id, "unknown-2_cleaning")

    def test_synthetic_malformed_device_does_not_parse_as_error(self) -> None:
        things = [thing("good", 0, progress=255), thing("bad", "2")]
        client = HomeAssistantCatGenieClient(Credentials())

        async def fake_request(method, path, body=None, params=None):
            return {"thingList": things}

        client._request = fake_request
        with self.assertRaises(ValidationError):
            asyncio.run(client.get_devices())

    def test_synthetic_entity_ids_and_enum_options_stay_stable(self) -> None:
        self.assertEqual(tuple(item.key for item in SENSORS), SENSOR_KEYS)
        self.assertEqual(tuple(item.key for item in BINARY_SENSORS), BINARY_KEYS)
        operation = _sensor("operation_state")
        self.assertEqual(operation.options, ["idle", "cleaning", "error"])
        self.assertNotIn("running", operation.options)
        self.assertNotIn("paused", operation.options)
        self.assertIn("error", operation.options)
        translation = json.loads(
            (CANDIDATE / "custom_components/catgenie/translations/en.json").read_text()
        )
        states = translation["entity"]["sensor"]["operation_state"]["state"]
        self.assertEqual(states["error"], "Error")
        self.assertEqual(set(states), {"idle", "cleaning", "error"})


class ErrorReportingTests(unittest.TestCase):
    """Exercise error descriptions through the real sensor implementation."""

    def test_water_fill_active_code_is_independent_of_operation_state(self) -> None:
        for state in (0, 1, 2):
            with self.subTest(state=state):
                device = TolerantDevice.model_validate(
                    thing("water-fill", state, active_errors=[2])
                )
                states, _, errors, _ = _entities([device])
                self.assertEqual(errors[0].native_value, "Water fill issue")
                self.assertEqual(errors[0].extra_state_attributes, {"active_errors": [2]})
                attrs = states[0].extra_state_attributes
                assert attrs is not None
                self.assertEqual(attrs["raw_state"], state)

    def test_normal_idle_and_cleaning_have_explicit_no_error_label(self) -> None:
        for state, progress in ((0, 255), (1, 0), (1, 50), (1, 100)):
            with self.subTest(state=state, progress=progress):
                device = TolerantDevice.model_validate(
                    thing("normal", state, progress=progress)
                )
                _, _, errors, _ = _entities([device])
                self.assertEqual(errors[0].native_value, "No active errors")
                self.assertEqual(errors[0].extra_state_attributes, {"active_errors": []})

    def test_abnormal_state_with_empty_codes_is_not_reported_clear(self) -> None:
        for state in (2, 5, 99, -1):
            with self.subTest(state=state):
                device = TolerantDevice.model_validate(thing("state-only", state))
                value = _entities([device])[2][0].native_value
                assert isinstance(value, str)
                self.assertEqual(value, f"Error reported (operation state: {state})")
                self.assertNotIn("Water fill", value)
                self.assertNotIn("cartridge", value)

    def test_missing_active_errors_is_not_an_explicit_clear_report(self) -> None:
        for name in ("activeErrors", "active_errors"):
            with self.subTest(alias=name):
                payload = thing("missing-errors", 0)
                del payload["activeErrors"]
                if name == "active_errors":
                    payload[name] = []
                    device = TolerantDevice.model_validate(payload)
                    self.assertEqual(_entities([device])[2][0].native_value, "No active errors")
                else:
                    device = TolerantDevice.model_validate(payload)
                    self.assertIsNone(_entities([device])[2][0].native_value)

    def test_defaulted_operation_status_is_not_an_explicit_clear_report(self) -> None:
        payload = thing("missing-status", 0)
        del payload["operationStatus"]
        device = TolerantDevice.model_validate(payload)
        self.assertIsNone(_entities([device])[2][0].native_value)

    def test_offline_device_does_not_report_no_active_errors(self) -> None:
        payload = thing("offline", 0)
        payload["reportedStatus"] = "disconnected"
        device = TolerantDevice.model_validate(payload)
        self.assertFalse(device.is_online)
        self.assertIsNone(_entities([device])[2][0].native_value)

    def test_blank_vendor_text_does_not_hide_codes_or_normal_state(self) -> None:
        for state, active, expected in (
            (0, [], "No active errors"),
            (2, [2], "Water fill issue"),
            (0, [5], "Cleaning solution cartridge missing"),
            (99, [], "Error reported (operation state: 99)"),
        ):
            with self.subTest(state=state, active=active):
                device = TolerantDevice.model_validate(
                    thing("blank-text", state, error=" \t\n ", active_errors=active)
                )
                self.assertEqual(_entities([device])[2][0].native_value, expected)

    def test_water_fill_lookalikes_remain_explicitly_unmapped(self) -> None:
        for code in ("2", 2.0, True, False, None):
            with self.subTest(code=code):
                device = TolerantDevice.model_validate(
                    thing("lookalike", 0, active_errors=[code])
                )
                self.assertEqual(
                    _entities([device])[2][0].native_value,
                    f"Unknown error code: {code}",
                )

    def test_known_and_unknown_faults_keep_order_and_diagnostics(self) -> None:
        device = TolerantDevice.model_validate(
            thing("mixed-faults", 2, active_errors=[2, 5, 99, 2])
        )
        _, _, errors, _ = _entities([device])
        self.assertEqual(
            errors[0].native_value,
            "Water fill issue; Cleaning solution cartridge missing; "
            "Unknown error code: 99; Water fill issue",
        )
        attrs = errors[0].extra_state_attributes
        assert attrs is not None
        self.assertEqual(attrs["active_errors"], [2, 5, 99, 2])

    def test_normal_cycle_preserves_numeric_progress_and_error_sensor_identity(self) -> None:
        device = TolerantDevice.model_validate(thing("cycle", 0, progress=255))
        sensors, progress, errors, _ = _entities([device])
        for state, pct in ((1, 50), (1, 100), (0, 255)):
            with self.subTest(state=state, progress=pct):
                update = TolerantDevice.model_validate(thing("cycle", state, progress=pct))
                for entity in (*sensors, *progress, *errors):
                    entity.coordinator.data["cycle"] = update
                self.assertEqual(errors[0].native_value, "No active errors")
                self.assertEqual(errors[0]._attr_unique_id, "cycle_operation_error")
                self.assertEqual(progress[0].native_value, None if pct == 255 else pct)

    def test_fault_clear_updates_existing_error_sensor(self) -> None:
        device = TolerantDevice.model_validate(thing("recovery", 2, active_errors=[2]))
        _, _, errors, _ = _entities([device])
        self.assertEqual(errors[0].native_value, "Water fill issue")
        errors[0].coordinator.data["recovery"] = TolerantDevice.model_validate(
            thing("recovery", 1, progress=17)
        )
        self.assertEqual(errors[0].native_value, "No active errors")
        attrs = errors[0].extra_state_attributes
        assert attrs is not None
        self.assertEqual(attrs["active_errors"], [])

    def test_missing_device_has_no_value_and_is_unavailable(self) -> None:
        device = TolerantDevice.model_validate(thing("gone", 0))
        _, _, errors, _ = _entities([device])
        errors[0].coordinator.data.clear()
        self.assertIsNone(errors[0].native_value)
        self.assertIsNone(errors[0].extra_state_attributes)
        self.assertFalse(errors[0].available)

    def test_long_vendor_text_is_bounded_without_losing_full_detail(self) -> None:
        text = "Vendor detail " * 30
        device = TolerantDevice.model_validate(
            thing("long-vendor", 2, error=text, active_errors=[2])
        )
        error = _entities([device])[2][0]
        value = error.native_value
        attrs = error.extra_state_attributes
        assert isinstance(value, str) and attrs is not None
        self.assertEqual(len(value), 255)
        self.assertTrue(value.endswith("..."))
        self.assertEqual(attrs["error_details"], text)
        self.assertEqual(attrs["active_errors"], [2])

    def test_long_active_code_list_keeps_every_raw_code(self) -> None:
        active = list(range(100, 130))
        device = TolerantDevice.model_validate(thing("long-codes", 0, active_errors=active))
        error = _entities([device])[2][0]
        value = error.native_value
        attrs = error.extra_state_attributes
        assert isinstance(value, str) and attrs is not None
        self.assertEqual(len(value), 255)
        self.assertEqual(attrs["active_errors"], active)
        self.assertIn("Unknown error code: 129", attrs["error_details"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
