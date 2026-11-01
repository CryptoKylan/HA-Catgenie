"""SYNTHETIC schedule-action callback tests. Not a live vendor or device result.

The registered catgenie.set_schedule callback is invoked through a small
service registry whose async_register and async_call match the Home Assistant
2026.10.4 public signatures. Refusals must not call the vendor.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
import types
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch as mock_patch
from zoneinfo import ZoneInfo

CANDIDATE = Path(__file__).resolve().parents[2]
DEPENDENCY = os.environ.get("CATGENIE_TEST_DEPENDENCY")
ROOT = CANDIDATE
_OMITTED = object()
_SCHEMA_INVALID: type[Exception] = Exception


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
        Platform=Platform,
        PERCENTAGE="%",
        UnitOfTime=SimpleNamespace(SECONDS="s", MINUTES="min"),
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
    helpers = _stub("homeassistant.helpers")
    ha.const = const
    ha.exceptions = exceptions
    ha.components = components
    ha.helpers = helpers
    helpers.update_coordinator = sys.modules["homeassistant.helpers.update_coordinator"]
    helpers.device_registry = sys.modules["homeassistant.helpers.device_registry"]
    helpers.entity_platform = sys.modules["homeassistant.helpers.entity_platform"]
    import importlib.util

    stub_path = Path(__file__).resolve().parents[1] / "fixtures" / "schema_stub.py"
    spec = importlib.util.spec_from_file_location("catgenie_schema_stub", stub_path)
    schema_stub = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(schema_stub)
    validation = _stub(
        "homeassistant.helpers.config_validation",
        vol=schema_stub,
        probatio=None,
    )
    helpers.config_validation = validation
    global _SCHEMA_INVALID
    _SCHEMA_INVALID = schema_stub.Invalid


_SEAM_PREFIXES = ("homeassistant", "curl_cffi", "Crypto", "custom_components")
_PATHS = [str(CANDIDATE), *([DEPENDENCY] if DEPENDENCY else []), *sys.path]
with mock_patch.dict(sys.modules), mock_patch.object(sys, "path", _PATHS):
    for _name in tuple(sys.modules):
        if _name == "custom_components" or _name.startswith("custom_components.catgenie"):
            del sys.modules[_name]
    _install_import_seams()
    from custom_components.catgenie.operation_state import TolerantDevice
    from custom_components.catgenie.schedule import schedule_editor_hold
    from custom_components.catgenie.schedule_actions import (
        REGISTRATION_FRAGMENT,
        SERVICES_YAML_FRAGMENT,
        SET_SCHEDULE_SCHEMA,
        SERVICE_SET_SCHEDULE,
        ScheduleActionError,
        ScheduleActionRefused,
        register_schedule_service,
    )
    import custom_components.catgenie.schedule_actions as schedule_actions
    import custom_components.catgenie.action_permissions
    _WORLD_MODULES = dict(sys.modules)


def _payload(
    manufacturer_id: str = "settings-device",
    *,
    schedule: list | None = None,
    omit: tuple[str, ...] = (),
    drop_configuration: bool = False,
    reported_status: str = "connected",
    configuration: dict | None = None,
) -> dict:
    if schedule is None:
        schedule = [{"hour": 6, "minute": 0, "time": "06:00:00"}]
    config = {
        "mode": 0,
        "manual": 0,
        "volumeLevel": 7,
        "schedule": schedule,
        "dndFrom": "02:00:00",
        "dndTo": "10:00:00",
        "catDelay": 1800,
        "autoLock": 300,
        "childLock": 1,
        "extraDry": True,
        "timezone": "-05:00",
    }
    if configuration:
        config.update(configuration)
    for key in omit:
        config.pop(key, None)
    body = {
        "_fixture": "SYNTHETIC",
        "manufacturerId": manufacturer_id,
        "name": "SYNTHETIC-schedule",
        "macAddress": "aa:bb:cc:dd:ee:ff",
        "hwRevision": "1",
        "fwVersion": "8.7.205R",
        "reportedStatus": reported_status,
        "operationStatus": {"state": 0, "progress": 255, "error": ""},
    }
    if not drop_configuration:
        body["configuration"] = config
    return body


def make_device(**kwargs: object) -> TolerantDevice:
    return TolerantDevice.model_validate(_payload(**kwargs))


def _siblings(device: TolerantDevice) -> dict:
    config = device.configuration
    extra = config.model_extra or {}
    return {
        "mode": config.mode,
        "manual": extra.get("manual"),
        "volumeLevel": config.volume_level,
        "catDelay": config.cat_delay,
        "autoLock": config.auto_lock,
        "extraDry": config.extra_dry,
        "timezone": config.timezone,
        "dndFrom": extra.get("dndFrom"),
        "dndTo": extra.get("dndTo"),
        "schedule": [(item.model_extra or {}).get("time") for item in config.schedule],
    }


class _Client:
    def __init__(self, device: TolerantDevice) -> None:
        self.methods: list[str] = []
        self.bodies: list[dict] = []
        self.fresh_devices: list | None = [device]
        self.read_error: Exception | None = None
        self.write_error: Exception | None = None

    async def get_devices(self) -> list:
        self.methods.append("get_devices")
        if self.read_error is not None:
            raise self.read_error
        if self.fresh_devices is None:
            raise AssertionError("fresh devices were not configured")
        return list(self.fresh_devices)

    async def update_configuration(self, device_id: str, **body: object) -> dict:
        self.methods.append("update_configuration")
        self.bodies.append({"device_id": device_id, **body})
        if self.write_error is not None:
            raise self.write_error
        return {"accepted": True}

    async def set_schedule(self, *args: object, **kwargs: object) -> dict:
        self.methods.append("set_schedule")
        raise AssertionError("library set_schedule must not be used")


class _Coordinator:
    def __init__(self, device: TolerantDevice) -> None:
        self.data = {device.manufacturer_id: device}
        self.client = _Client(device)
        self.last_update_success = True
        self.refresh_calls = 0
        self.refresh_error: Exception | None = None

    async def async_request_refresh(self) -> None:
        self.refresh_calls += 1
        if self.refresh_error is not None:
            raise self.refresh_error


class _Entry:
    def __init__(
        self,
        device_id: str,
        manufacturer_id: str,
        *,
        manufacturer: str = "PetNovations",
        identifiers: set | None = None,
    ) -> None:
        self.id = device_id
        self.manufacturer = manufacturer
        self.identifiers = identifiers if identifiers is not None else {( "catgenie", manufacturer_id)}


class HonestServiceRegistry:
    """Minimal registry matching HA ServiceRegistry.async_register/async_call."""

    def __init__(self) -> None:
        self._services: dict[str, dict[str, dict]] = {}
        self.registrations: list[dict] = []

    def async_register(
        self,
        domain: str,
        service: str,
        service_func: object,
        schema: object = None,
        supports_response: object = _OMITTED,
        job_type: object = None,
        *,
        description_placeholders: object = None,
    ) -> None:
        domain = domain.lower()
        service = service.lower()
        self._services.setdefault(domain, {})[service] = {
            "func": service_func,
            "schema": schema,
        }
        self.registrations.append(
            {
                "domain": domain,
                "service": service,
                "func": service_func,
                "schema": schema,
                "supports_response": supports_response,
                "job_type": job_type,
                "description_placeholders": description_placeholders,
            }
        )

    def has_service(self, domain: str, service: str) -> bool:
        return service.lower() in self._services.get(domain.lower(), {})

    async def async_call(
        self,
        domain: str,
        service: str,
        service_data: dict | None = None,
        blocking: bool = False,
        context: object = None,
        target: dict | None = None,
        return_response: bool = False,
    ) -> object:
        domain = domain.lower()
        service = service.lower()
        try:
            handler = self._services[domain][service]
        except KeyError:
            raise KeyError(f"{domain}.{service}") from None
        data = dict(service_data or {})
        if target:
            data.update(target)
        if handler["schema"] is not None:
            data = handler["schema"](data)
        call = SimpleNamespace(
            hass=None,
            domain=domain,
            service=service,
            data=data,
            context=context,
            return_response=return_response,
        )
        return await handler["func"](call)


def _independent_utc(clock: str, zone: str, on_date: date) -> str:
    hour, minute, second = (int(part) for part in clock.split(":"))
    local = datetime(
        on_date.year, on_date.month, on_date.day,
        hour, minute, second, tzinfo=ZoneInfo(zone),
    )
    return local.astimezone(timezone.utc).strftime("%H:%M:%S")


class _World:
    def __init__(self, device: TolerantDevice | None = None) -> None:
        self.device_id = "ha-device-1"
        self.manufacturer_id = "SN-SECRET-9"
        self.device = device or make_device(manufacturer_id=self.manufacturer_id)
        self.coordinator = _Coordinator(self.device)
        self.entry = _Entry(self.device_id, self.manufacturer_id)
        self.resolves = 0
        self.entered = 0
        self.resolve_error: Exception | None = None
        hass = SimpleNamespace()
        self.registry = HonestServiceRegistry()
        hass.services = self.registry
        register_schedule_service(hass, self.resolve_target)
        recorded = self.registry._services["catgenie"]["set_schedule"]["func"]

        async def _wrapped(call: object) -> object:
            self.entered += 1
            return await recorded(call)

        self.registry._services["catgenie"]["set_schedule"]["func"] = _wrapped

    async def resolve_target(self, device_id: str) -> tuple[_Coordinator, _Entry]:
        self.resolves += 1
        if self.resolve_error is not None:
            raise self.resolve_error
        if device_id != self.device_id:
            raise AssertionError("resolver received an unexpected device id")
        return self.coordinator, self.entry

    def call(self, **overrides: object) -> object:
        data = {
            "device_id": self.device_id,
            "times": [{"time": "07:00:00"}, {"time": "19:00:00"}],
            "zone": "America/New_York",
            "reference_date": "2026-10-31",
        }
        data.update(overrides)
        return self.registry.async_call("catgenie", "set_schedule", data, blocking=True)


class ScheduleActionCallbackTests(unittest.TestCase):
    def setUp(self):
        # Lazy production relative imports must resolve in this harness's world.
        self.enterContext(mock_patch.dict(sys.modules, _WORLD_MODULES))
        self.enterContext(mock_patch.object(sys, "path", _PATHS))

    def test_registration_matches_ha_signature_and_shared_service_wiring(self) -> None:
        world = _World()
        recorded = world.registry.registrations[0]
        self.assertEqual(recorded["domain"], "catgenie")
        self.assertEqual(recorded["service"], SERVICE_SET_SCHEDULE)
        self.assertIs(recorded["schema"], SET_SCHEDULE_SCHEMA)
        self.assertIs(recorded["supports_response"], _OMITTED)
        self.assertIsNone(recorded["job_type"])
        self.assertIsNone(recorded["description_placeholders"])
        signature = inspect.signature(HonestServiceRegistry.async_register)
        self.assertEqual(
            list(signature.parameters),
            [
                "self",
                "domain",
                "service",
                "service_func",
                "schema",
                "supports_response",
                "job_type",
                "description_placeholders",
            ],
        )
        self.assertEqual(
            signature.parameters["description_placeholders"].kind,
            inspect.Parameter.KEYWORD_ONLY,
        )
        init_source = (ROOT / "custom_components/catgenie/__init__.py").read_text()
        self.assertNotIn("schedule_actions", init_source)
        self.assertNotIn("set_schedule", init_source)
        self.assertTrue((ROOT / "custom_components/catgenie/services.yaml").exists())
        services_source = (ROOT / "custom_components/catgenie/services.py").read_text()
        self.assertIn("register_schedule_service(hass, resolve)", services_source)
        hold = schedule_editor_hold()
        self.assertFalse(hold["sendable"])
        self.assertFalse(hold["registered_ha_service"])
        source = Path(schedule_actions.__file__).read_text()
        self.assertNotIn("import logging", source)
        self.assertNotIn("_LOGGER", source)
        self.assertNotIn("client.set_schedule", source)
        self.assertNotIn(".set_schedule(", source)
        self.assertNotIn("async_run_command", source)
        self.assertIn("multiple: true", SERVICES_YAML_FRAGMENT)
        self.assertIn("time: {}", SERVICES_YAML_FRAGMENT)
        self.assertNotIn("multiple: true\n          selector:\n            time:", SERVICES_YAML_FRAGMENT)
        self.assertIn("manufacturer: PetNovations", SERVICES_YAML_FRAGMENT)
        self.assertIn("register_schedule_service", REGISTRATION_FRAGMENT)
        self.assertNotIn("mode:", SERVICES_YAML_FRAGMENT)
        self.assertNotIn("manual:", SERVICES_YAML_FRAGMENT)

    def test_structural_refusals_do_not_enter_the_callback_or_call_io(self) -> None:
        world = _World()
        cases = [
            {"mode": 1},
            {"manual": 0},
            {"times": ["07:00:00", "19:00:00"]},
            {"times": "[{\"time\": \"07:00:00\"}]"},
            {"times": [{"time": "07:00:00", "day": 1}]},
            {"times": [{"hour": 7, "minute": 0}]},
            {"device_id": ""},
            {"device_id": "../secret"},
            {"extra": 1},
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                before = (world.entered, world.resolves, list(world.coordinator.client.methods))
                with self.assertRaises(_SCHEMA_INVALID) as raised:
                    asyncio.run(world.call(**overrides))
                text = str(raised.exception)
                self.assertNotIsInstance(raised.exception, ScheduleActionRefused)
                if set(overrides) & {"mode", "manual", "extra"}:
                    self.assertIn("unknown_field", text)
                elif overrides.get("device_id") in ("", "../secret"):
                    self.assertIn("invalid_device_id", text)
                else:
                    self.assertIn("invalid_times", text)
                self.assertEqual((world.entered, world.resolves), (before[0], before[1]))
                self.assertEqual(world.coordinator.client.methods, before[2])
                self.assertNotIn("SN-SECRET-9", str(raised.exception))

    def test_local_refusals_do_not_resolve_or_call_io(self) -> None:
        cases = [
            ("empty", {"times": []}, "empty_schedule"),
            ("nine", {"times": [{"time": clock} for clock in _nine()]}, "too_many_clocks"),
            ("duplicate", {"times": [{"time": "07:00:00"}, {"time": "07:00:00"}]}, "duplicate_clock"),
            ("close", {"times": [{"time": "07:00:00"}, {"time": "08:59:59"}]}, "spacing"),
            ("wrap", {"times": [{"time": "23:30:00"}, {"time": "01:00:00"}]}, "spacing"),
            ("unpadded", {"times": [{"time": "7:00:00"}, {"time": "19:00:00"}]}, "invalid_clock"),
            ("no_seconds", {"times": [{"time": "07:00"}, {"time": "19:00"}]}, "invalid_clock"),
            ("unicode", {"times": [{"time": "07：00：00"}, {"time": "19:00:00"}]}, "invalid_clock"),
            ("offset", {"zone": "-05:00"}, "invalid_zone"),
            ("missing_zone_name", {"zone": "America/Not_A_Zone"}, "invalid_zone"),
            ("local_word", {"zone": "local"}, "invalid_zone"),
            ("date_time", {"reference_date": "2026-10-31T00:00:00"}, "invalid_reference_date"),
            ("bad_date", {"reference_date": "2026-02-31"}, "invalid_reference_date"),
            ("datetime_object", {"reference_date": datetime(2026, 10, 31)}, "invalid_reference_date"),
            ("gap", {"times": [{"time": "02:30:00"}, {"time": "12:00:00"}], "zone": "America/New_York", "reference_date": "2026-03-08"}, "nonexistent_local_time"),
            ("fold", {"times": [{"time": "01:30:00"}, {"time": "12:00:00"}], "zone": "America/New_York", "reference_date": "2026-11-01"}, "ambiguous_local_time"),
            ("berlin_gap", {"times": [{"time": "02:30:00"}, {"time": "12:00:00"}], "zone": "Europe/Berlin", "reference_date": "2026-03-29"}, "nonexistent_local_time"),
        ]
        for name, overrides, code in cases:
            with self.subTest(name=name):
                world = _World()
                with self.assertRaises(ScheduleActionRefused) as raised:
                    asyncio.run(world.call(**overrides))
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(world.resolves, 0)
                self.assertEqual(world.coordinator.client.methods, [])
                self.assertEqual(world.coordinator.refresh_calls, 0)
                self.assertNotIn("SN-SECRET-9", str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)

    def test_fresh_and_cache_refusals_do_not_put(self) -> None:
        secret = RuntimeError("vendor blew up SN-SECRET-9")

        def run(setup, code, kind) -> None:
            world = _World()
            setup(world)
            before = _siblings(world.device)
            cache_id = id(world.coordinator.data)
            device_id = id(world.device)
            with self.assertRaises(kind) as raised:
                asyncio.run(world.call())
            self.assertEqual(getattr(raised.exception, "code", None), code)
            self.assertNotIn("update_configuration", world.coordinator.client.methods)
            self.assertNotIn("set_schedule", world.coordinator.client.methods)
            self.assertEqual(world.coordinator.refresh_calls, 0)
            self.assertEqual(_siblings(world.device), before)
            self.assertEqual(id(world.coordinator.data), cache_id)
            if world.manufacturer_id in world.coordinator.data:
                self.assertIs(world.coordinator.data[world.manufacturer_id], world.device)
            self.assertEqual(id(world.device), device_id)
            text = str(raised.exception)
            self.assertNotIn("SN-SECRET-9", text)
            self.assertIsNone(raised.exception.__cause__)
            if kind is ScheduleActionError:
                self.assertTrue(raised.exception.__suppress_context__)
                self.assertEqual(raised.exception.cause_type, "RuntimeError")

        run(lambda world: setattr(world.coordinator, "last_update_success", False), "unavailable", ScheduleActionRefused)
        run(lambda world: world.coordinator.data.clear(), "unavailable", ScheduleActionRefused)
        run(
            lambda world: setattr(world.coordinator.client, "fresh_devices", []),
            "fresh_missing",
            ScheduleActionRefused,
        )
        run(
            lambda world: setattr(
                world.coordinator.client,
                "fresh_devices",
                [world.device, make_device(manufacturer_id=world.manufacturer_id)],
            ),
            "fresh_ambiguous",
            ScheduleActionRefused,
        )
        run(
            lambda world: setattr(world.coordinator.client, "fresh_devices", [{"manufacturerId": world.manufacturer_id}]),
            "fresh_shape",
            ScheduleActionRefused,
        )
        run(
            lambda world: setattr(
                world.coordinator.client,
                "fresh_devices",
                [make_device(manufacturer_id=world.manufacturer_id, reported_status="disconnected")],
            ),
            "offline",
            ScheduleActionRefused,
        )
        run(
            lambda world: setattr(world.coordinator.client, "fresh_devices", [make_device(manufacturer_id=world.manufacturer_id, drop_configuration=True)]),
            "incomplete",
            ScheduleActionRefused,
        )
        run(
            lambda world: setattr(world.coordinator.client, "fresh_devices", [make_device(manufacturer_id=world.manufacturer_id, omit=("schedule",))]),
            "schedule_not_explicit",
            ScheduleActionRefused,
        )
        run(
            lambda world: setattr(
                world.coordinator.client,
                "fresh_devices",
                [make_device(manufacturer_id=world.manufacturer_id, schedule=[{"day": 1, "hour": 6, "minute": 0, "enabled": True}])],
            ),
            "unsafe_schedule",
            ScheduleActionRefused,
        )
        run(lambda world: setattr(world.coordinator.client, "read_error", secret), "read", ScheduleActionError)
        run(lambda world: setattr(world, "resolve_error", secret), "resolve", ScheduleActionError)
        run(lambda world: setattr(world.entry, "manufacturer", "Other"), "unresolved", ScheduleActionRefused)
        run(
            lambda world: setattr(world.entry, "identifiers", {("catgenie", world.manufacturer_id), ("catgenie", "other")}),
            "unresolved",
            ScheduleActionRefused,
        )

    def test_write_failure_does_not_retry_refresh_or_leak_serial(self) -> None:
        world = _World()
        world.coordinator.client.write_error = RuntimeError("put failed SN-SECRET-9")
        before = _siblings(world.device)
        with self.assertRaises(ScheduleActionError) as raised:
            asyncio.run(world.call())
        self.assertEqual(raised.exception.code, "write")
        self.assertEqual(raised.exception.cause_type, "RuntimeError")
        self.assertEqual(world.coordinator.client.methods, ["get_devices", "update_configuration"])
        self.assertEqual(world.coordinator.refresh_calls, 0)
        self.assertEqual(len(world.coordinator.client.bodies), 1)
        self.assertNotIn("SN-SECRET-9", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertEqual(_siblings(world.device), before)

    def test_refresh_failure_does_not_retry_the_put(self) -> None:
        world = _World()
        world.coordinator.refresh_error = RuntimeError("refresh SN-SECRET-9")
        with self.assertRaises(ScheduleActionError) as raised:
            asyncio.run(world.call())
        self.assertEqual(raised.exception.code, "refresh")
        self.assertNotIn("was not changed", str(raised.exception))
        self.assertNotIn("SN-SECRET-9", str(raised.exception))
        self.assertEqual(world.coordinator.client.methods.count("update_configuration"), 1)
        self.assertEqual(world.coordinator.client.methods.count("get_devices"), 1)
        self.assertEqual(world.coordinator.refresh_calls, 1)

    def test_success_puts_only_schedule_and_preserves_siblings(self) -> None:
        cached = make_device(manufacturer_id="SN-SECRET-9", configuration={"mode": 1, "manual": 1})
        fresh = make_device(manufacturer_id="SN-SECRET-9", configuration={"mode": 1, "manual": 1})
        world = _World(cached)
        world.coordinator.client.fresh_devices = [fresh]
        before_cache = _siblings(cached)
        before_fresh = _siblings(fresh)
        data_id = id(world.coordinator.data)
        asyncio.run(world.call())
        self.assertEqual(world.entered, 1)
        self.assertEqual(world.resolves, 1)
        self.assertEqual(world.coordinator.client.methods, ["get_devices", "update_configuration"])
        self.assertEqual(world.coordinator.refresh_calls, 1)
        self.assertEqual(len(world.coordinator.client.bodies), 1)
        body = world.coordinator.client.bodies[0]
        self.assertEqual(set(body), {"device_id", "schedule"})
        self.assertEqual(body["device_id"], "SN-SECRET-9")
        self.assertEqual(
            body["schedule"],
            [
                _independent_utc("07:00:00", "America/New_York", date(2026, 10, 31)),
                _independent_utc("19:00:00", "America/New_York", date(2026, 10, 31)),
            ],
        )
        self.assertEqual(body["schedule"], ["11:00:00", "23:00:00"])
        self.assertIs(world.coordinator.data["SN-SECRET-9"], cached)
        self.assertEqual(id(world.coordinator.data), data_id)
        self.assertEqual(_siblings(cached), before_cache)
        self.assertEqual(_siblings(fresh), before_fresh)
        self.assertEqual(before_cache["mode"], 1)
        self.assertEqual(before_cache["manual"], 1)
        hold = schedule_editor_hold()
        self.assertFalse(hold["sendable"])
        self.assertFalse(hold["registered_ha_service"])

    def test_all_zones_date_offsets_wrap_and_same_date(self) -> None:
        on_date = date(2026, 10, 31)
        clocks = ["22:00:00", "06:00:00"]
        expected = {
            "UTC": ["22:00:00", "06:00:00"],
            "America/New_York": ["02:00:00", "10:00:00"],
            "Europe/Berlin": ["21:00:00", "05:00:00"],
            "Australia/Sydney": ["11:00:00", "19:00:00"],
            "Asia/Kolkata": ["16:30:00", "00:30:00"],
            "Asia/Kathmandu": ["16:15:00", "00:15:00"],
            "Australia/Lord_Howe": ["11:00:00", "19:00:00"],
        }
        for zone, utc_clocks in expected.items():
            with self.subTest(zone=zone):
                world = _World()
                seen: list[date] = []
                real = schedule_actions.local_time_to_utc_time

                def _spy(clock: str, zone_info: ZoneInfo, day: date, _real=real) -> str:
                    seen.append(day)
                    return _real(clock, zone_info, day)

                with mock_patch.object(schedule_actions, "local_time_to_utc_time", _spy):
                    asyncio.run(
                        world.call(
                            zone=zone,
                            reference_date=on_date.isoformat(),
                            times=[{"time": clock} for clock in clocks],
                        )
                    )
                self.assertEqual(seen, [on_date, on_date])
                body = world.coordinator.client.bodies[0]["schedule"]
                self.assertEqual(body, utc_clocks)
                self.assertEqual(
                    body,
                    [_independent_utc(clock, zone, on_date) for clock in clocks],
                )
                self.assertEqual(set(world.coordinator.client.bodies[0]), {"device_id", "schedule"})

        shifts = [
            ("America/New_York", "2026-10-31", "2026-11-02", "02:00:00", "03:00:00"),
            ("Europe/Berlin", "2026-10-24", "2026-10-31", "20:00:00", "21:00:00"),
            ("Australia/Lord_Howe", "2026-04-04", "2026-04-06", "11:00:00", "11:30:00"),
            ("Asia/Kolkata", "2026-01-15", "2026-07-15", "16:30:00", "16:30:00"),
            ("Asia/Kathmandu", "2026-01-15", "2026-07-15", "16:15:00", "16:15:00"),
        ]
        for zone, first, second, first_utc, second_utc in shifts:
            with self.subTest(zone=zone, first=first, second=second):
                for day, utc in ((first, first_utc), (second, second_utc)):
                    world = _World()
                    asyncio.run(
                        world.call(
                            zone=zone,
                            reference_date=day,
                            times=[{"time": "22:00:00"}, {"time": "08:00:00"}],
                        )
                    )
                    self.assertEqual(world.coordinator.client.bodies[0]["schedule"][0], utc)
                    self.assertEqual(
                        world.coordinator.client.bodies[0]["schedule"][0],
                        _independent_utc("22:00:00", zone, date.fromisoformat(day)),
                    )

        world = _World()
        asyncio.run(
            world.call(
                zone="Europe/Berlin",
                reference_date="2026-03-29",
                times=[{"time": "01:30:00"}, {"time": "03:30:00"}],
            )
        )
        self.assertEqual(world.coordinator.client.bodies[0]["schedule"], ["00:30:00", "01:30:00"])

        world = _World()
        asyncio.run(
            world.call(
                zone="UTC",
                reference_date="2026-10-31",
                times=[{"time": "23:00:00"}, {"time": "01:00:00"}],
            )
        )
        self.assertEqual(world.coordinator.client.bodies[0]["schedule"], ["23:00:00", "01:00:00"])

        world = _World()
        eight = [f"{hour:02d}:00:00" for hour in (0, 3, 6, 9, 12, 15, 18, 21)]
        asyncio.run(world.call(zone="UTC", times=[{"time": clock} for clock in eight]))
        self.assertEqual(len(world.coordinator.client.bodies[0]["schedule"]), 8)

    def test_default_reference_date_is_today_in_the_given_zone(self) -> None:
        world = _World()
        real = schedule_actions.datetime

        class Frozen(real):
            @classmethod
            def now(cls, tz: object = None) -> datetime:
                instant = real(2026, 11, 1, 2, 30, tzinfo=timezone.utc)
                if tz is None:
                    return instant
                return instant.astimezone(tz)

        data = {
            "device_id": world.device_id,
            "times": [{"time": "22:00:00"}, {"time": "08:00:00"}],
            "zone": "America/New_York",
        }
        with mock_patch.object(schedule_actions, "datetime", Frozen):
            asyncio.run(world.registry.async_call("catgenie", "set_schedule", data, blocking=True))
        self.assertEqual(world.coordinator.client.bodies[0]["schedule"][0], "02:00:00")
        self.assertNotEqual(world.coordinator.client.bodies[0]["schedule"][0], "03:00:00")

    def test_resolver_picks_one_device_when_several_exist(self) -> None:
        first = make_device(manufacturer_id="unit-a")
        second = make_device(manufacturer_id="unit-b")
        world = _World(first)
        other = _Coordinator(second)
        other.client.fresh_devices = [first, second]
        world.coordinator.client.fresh_devices = [first, second]
        entries = {
            "ha-a": (_Coordinator(first), _Entry("ha-a", "unit-a")),
            "ha-b": (other, _Entry("ha-b", "unit-b")),
        }
        entries["ha-a"][0].client.fresh_devices = [first, second]

        async def resolve_target(device_id: str):
            world.resolves += 1
            return entries[device_id]

        hass = SimpleNamespace(services=HonestServiceRegistry())
        register_schedule_service(hass, resolve_target)
        asyncio.run(
            hass.services.async_call(
                "catgenie",
                "set_schedule",
                {
                    "device_id": "ha-b",
                    "times": [{"time": "07:00:00"}, {"time": "19:00:00"}],
                    "zone": "UTC",
                    "reference_date": "2026-10-31",
                },
                blocking=True,
            )
        )
        self.assertEqual(other.client.bodies[0]["device_id"], "unit-b")
        self.assertEqual(entries["ha-a"][0].client.methods, [])
        self.assertEqual(other.client.methods, ["get_devices", "update_configuration"])


def _nine() -> list[str]:
    clocks = []
    minute = 0
    for _ in range(9):
        clocks.append(f"{minute // 60:02d}:{minute % 60:02d}:00")
        minute += 160
    return clocks


if __name__ == "__main__":
    unittest.main()
