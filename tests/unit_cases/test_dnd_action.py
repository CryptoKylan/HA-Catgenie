"""SYNTHETIC Do Not Disturb action tests. Not a live device or Home Assistant run.

Expected UTC clocks are literals checked by an independent ZoneInfo fold walk.
They are not produced by calling ``local_time_to_utc_time`` and comparing the
action to that helper.
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import sys
import types
import unittest
from datetime import date, datetime, time, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import tests.unit_cases.test_settings_controls as harness

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "custom_components" / "catgenie"
SIGNATURES = ROOT / "tests" / "fixtures" / "ha_service_registry_signatures.py"
# Invented conversion date, not an owner save or activity observation.
OWNER_DAY = date(2024, 10, 30)
EXPECTED = {
    ("America/Toronto", OWNER_DAY, "22:00:00"): "02:00:00",
    ("America/Toronto", OWNER_DAY, "06:00:00"): "10:00:00",
    ("America/New_York", OWNER_DAY, "22:00:00"): "02:00:00",
    ("America/New_York", OWNER_DAY, "06:00:00"): "10:00:00",
    ("UTC", OWNER_DAY, "22:00:00"): "22:00:00",
    ("UTC", OWNER_DAY, "06:00:00"): "06:00:00",
    ("Europe/Berlin", OWNER_DAY, "22:00:00"): "21:00:00",
    ("Europe/Berlin", OWNER_DAY, "06:00:00"): "05:00:00",
    ("Australia/Sydney", OWNER_DAY, "22:00:00"): "11:00:00",
    ("Australia/Sydney", OWNER_DAY, "06:00:00"): "19:00:00",
    ("Asia/Kolkata", date(2026, 6, 15), "22:00:00"): "16:30:00",
    ("Asia/Kolkata", date(2026, 6, 15), "06:00:00"): "00:30:00",
    ("Asia/Kathmandu", date(2026, 6, 15), "22:15:00"): "16:30:00",
    ("Asia/Kathmandu", date(2026, 6, 15), "06:15:00"): "00:30:00",
    ("Australia/Lord_Howe", date(2026, 6, 15), "22:00:00"): "11:30:00",
    ("Australia/Lord_Howe", date(2026, 6, 15), "06:00:00"): "19:30:00",
    ("Australia/Lord_Howe", OWNER_DAY, "22:00:00"): "11:00:00",
    ("Australia/Lord_Howe", OWNER_DAY, "06:00:00"): "19:00:00",
}
INSTANT = datetime(2026, 11, 1, 3, 30, tzinfo=timezone.utc)


def independent_utc(clock: str, zone_name: str, on: date) -> list[str]:
    """Fold walk that does not call the integration helper."""
    zone = ZoneInfo(zone_name)
    hour, minute, second = (int(part) for part in clock.split(":"))
    found: list[str] = []
    for fold in (0, 1):
        local = datetime(
            on.year, on.month, on.day, hour, minute, second, tzinfo=zone, fold=fold
        )
        utc = local.astimezone(timezone.utc)
        back = utc.astimezone(zone)
        if back.date() != on or (back.hour, back.minute, back.second) != (hour, minute, second):
            continue
        rendered = utc.strftime("%H:%M:%S")
        if rendered not in found:
            found.append(rendered)
    return found


class _Invalid(Exception):
    pass


class _Marker:
    def __init__(self, key: str) -> None:
        self.key = key


class _Required(_Marker):
    pass


class _Optional(_Marker):
    pass


def _backend_module(invalid: type[Exception]) -> types.ModuleType:
    """One framework backend. Schema failures use this backend's Invalid."""

    class Schema:
        def __init__(self, spec: dict, extra: object = None) -> None:
            if extra is None:
                raise TypeError("extra is required")
            self.spec = spec
            self.extra = extra

        def __call__(self, data: dict) -> dict:
            if type(data) is not dict:
                raise invalid("not-dict")
            allowed: set[str] = set()
            required: set[str] = set()
            validators: dict[str, object] = {}
            for key, validator in self.spec.items():
                name = key.key if isinstance(key, _Marker) else str(key)
                allowed.add(name)
                validators[name] = validator
                if isinstance(key, _Required):
                    required.add(name)
            if set(data) - allowed:
                raise invalid("unknown_field")
            if required - set(data):
                raise invalid("missing")
            parsed = {}
            for name, value in data.items():
                validator = validators[name]
                if isinstance(validator, type):
                    if not isinstance(value, validator):
                        raise invalid("type")
                    parsed[name] = value
                elif callable(validator):
                    parsed[name] = validator(value)
                else:
                    raise invalid("validator")
            return parsed

    module = types.ModuleType("config_validation_backend")
    module.Invalid = invalid
    module.Schema = Schema
    module.Required = _Required
    module.Optional = _Optional
    module.PREVENT_EXTRA = "prevent"
    return module


class _SupportsResponse:
    NONE = "none"


class _Services:
    def __init__(self) -> None:
        self.registered: dict[str, dict[str, dict]] = {}
        self.removed: list[tuple[str, str]] = []
        self.fail_register = False
        self.fail_on: str | None = None

    def has_service(self, domain: str, service: str) -> bool:
        return service in self.registered.get(domain, {})

    def async_register(self, domain, service, func, schema=None, supports_response=None, job_type=None, *, description_placeholders=None):
        self.registered.setdefault(domain, {})[service] = {
            "func": func,
            "schema": schema,
            "supports_response": supports_response,
            "job_type": job_type,
            "placeholders": description_placeholders,
        }
        if self.fail_register or service == self.fail_on:
            raise RuntimeError("register failed after insert")

    def async_remove(self, domain: str, service: str) -> None:
        self.removed.append((domain, service))
        self.registered.get(domain, {}).pop(service, None)


class _Hass:
    def __init__(self, coordinator, device, entries: dict | None = None) -> None:
        self.services = _Services()
        self.data: dict = {}
        self.config = SimpleNamespace(time_zone="Australia/Sydney")
        self.registry = SimpleNamespace(async_get=lambda device_id: device if device_id == device.id else None)
        table = entries if entries is not None else {
            "entry-1": SimpleNamespace(
                domain="catgenie",
                entry_id="entry-1",
                runtime_data=coordinator,
            )
        }
        self.config_entries = SimpleNamespace(
            async_get_entry=lambda entry_id: table.get(entry_id)
        )
        self.device = device


_SAVED_MODULES: dict[str, types.ModuleType] = {}
_INSERTED: list[str] = []


def _install() -> None:
    dependency = os.environ.get("CATGENIE_TEST_DEPENDENCY")
    if dependency and dependency not in sys.path:
        sys.path.insert(0, dependency)
    harness._install_import_seams()
    core = sys.modules["homeassistant.core"]
    core.SupportsResponse = _SupportsResponse
    registry = sys.modules["homeassistant.helpers.device_registry"]
    registry.async_get = lambda hass: hass.registry
    typing_mod = types.ModuleType("homeassistant.helpers.typing")
    typing_mod.VolSchemaType = object
    sys.modules["homeassistant.helpers.typing"] = typing_mod
    sys.modules["homeassistant.helpers"].typing = typing_mod
    current = _backend_module(_Invalid)
    legacy = _backend_module(type("VolInvalid", (Exception,), {}))
    validation = types.ModuleType("homeassistant.helpers.config_validation")
    validation.probatio = current
    validation.vol = legacy
    sys.modules["homeassistant.helpers.config_validation"] = validation
    sys.modules["homeassistant.helpers"].config_validation = validation
    # A globally installed library must not be the backend the integration picks.
    decoy = _backend_module(type("DecoyInvalid", (Exception,), {}))
    sys.modules["probatio"] = decoy
    import catgenie as catgenie_mod

    sys.modules["catgenie"] = catgenie_mod
    for name in list(sys.modules):
        if name == "custom_components" or name.startswith("custom_components.catgenie"):
            del sys.modules[name]
    from custom_components.catgenie import dnd_actions, services

    global actions, service_mod
    actions = dnd_actions
    service_mod = services


def _activate_stubs() -> None:
    needed = (
        "homeassistant",
        "homeassistant.core",
        "homeassistant.exceptions",
        "homeassistant.helpers",
        "homeassistant.helpers.device_registry",
        "homeassistant.helpers.typing",
        "homeassistant.helpers.config_validation",
        "probatio",
        "catgenie",
    )
    for name in needed:
        module = sys.modules.get(name)
        if module is None:
            continue
        if name not in _SAVED_MODULES and name not in _INSERTED:
            _SAVED_MODULES[name] = module
    # Rebind only for this test. Later modules imported a clean package.
    import catgenie

    if "catgenie.Device" not in _SAVED_MODULES:
        _SAVED_MODULES["catgenie.Device"] = catgenie.Device
    catgenie.Device = harness.TolerantDevice.__mro__[1]
    registry = sys.modules["homeassistant.helpers.device_registry"]
    registry.async_get = lambda hass: hass.registry


def _restore_stubs() -> None:
    import catgenie

    saved = _SAVED_MODULES.get("catgenie.Device")
    if saved is not None:
        catgenie.Device = saved


_install()
_restore_stubs()


def _device(**overrides):
    return harness.make_device(**overrides)


def _bound(device=None, fresh=None):
    device = device or _device()
    coordinator = harness._Coordinator(device)
    coordinator.last_update_success = True
    if fresh is not None:
        coordinator.client.fresh_devices = fresh
    registry_device = SimpleNamespace(
        id="ha-device-1",
        config_entry_id="entry-1",
        identifiers={("catgenie", device.manufacturer_id)},
        manufacturer="PetNovations",
        disabled_by=None,
        is_composite_device=False,
    )
    hass = _Hass(coordinator, registry_device)
    return hass, coordinator, registry_device


def _run(coro):
    return asyncio.run(coro)


def _error_type():
    return sys.modules["homeassistant.exceptions"].HomeAssistantError


class DndActionTests(unittest.TestCase):
    def setUp(self):
        _activate_stubs()

    def tearDown(self):
        _restore_stubs()

    def test_literals_match_an_independent_zoneinfo_walk(self):
        for (zone_name, on, clock), expected in EXPECTED.items():
            with self.subTest(zone=zone_name, clock=clock, on=on):
                self.assertEqual(independent_utc(clock, zone_name, on), [expected])

    def test_synthetic_window_and_other_zones_put_utc_clocks(self):
        windows = [
            ("America/Toronto", OWNER_DAY, "22:00:00", "06:00:00"),
            ("America/New_York", OWNER_DAY, "22:00:00", "06:00:00"),
            ("UTC", OWNER_DAY, "22:00:00", "06:00:00"),
            ("Europe/Berlin", OWNER_DAY, "22:00:00", "06:00:00"),
            ("Australia/Sydney", OWNER_DAY, "22:00:00", "06:00:00"),
            ("Asia/Kolkata", date(2026, 6, 15), "22:00:00", "06:00:00"),
            ("Asia/Kathmandu", date(2026, 6, 15), "22:15:00", "06:15:00"),
            ("Australia/Lord_Howe", date(2026, 6, 15), "22:00:00", "06:00:00"),
            ("Australia/Lord_Howe", OWNER_DAY, "22:00:00", "06:00:00"),
        ]
        for zone_name, on, start, end in windows:
            with self.subTest(zone=zone_name, on=on):
                hass, coordinator, _device_entry = _bound(
                    _device(configuration={"timezone": "-05:00", "dstFrom": "03-08 07:00:00", "dstTo": "11-01 06:00:00", "mode": 0, "manual": 0})
                )
                payload = _run(actions.async_apply_dnd(hass, {
                    "device_id": "ha-device-1",
                    "enabled": True,
                    "start_time": start,
                    "end_time": end,
                    "timezone": zone_name,
                    "reference_date": on.isoformat(),
                }))
                self.assertEqual(payload, {
                    "dndFrom": EXPECTED[(zone_name, on, start)],
                    "dndTo": EXPECTED[(zone_name, on, end)],
                    "catDelay": 1800,
                })
                body = coordinator.client.bodies[0]
                self.assertEqual(set(body), {"device_id", "dndFrom", "dndTo", "catDelay"})
                self.assertEqual(coordinator.client.methods, ["get_devices", "update_configuration"])
                self.assertEqual(coordinator.refreshes, 1)
                self.assertNotIn("mode", body)
                self.assertNotIn("manual", body)
                self.assertNotIn("schedule", body)
                self.assertNotIn("timezone", body)
                self.assertNotIn("dstFrom", body)
                self.assertNotIn("dstTo", body)

    def test_host_zone_is_not_the_conversion_zone_and_default_date_uses_selected_zone(self):
        seen = []

        def clock(zone):
            seen.append(zone.key)
            return INSTANT.astimezone(zone)

        hass, coordinator, _device_entry = _bound()
        self.assertEqual(hass.config.time_zone, "Australia/Sydney")
        payload = _run(actions.async_apply_dnd(hass, {
            "device_id": "ha-device-1",
            "enabled": True,
            "start_time": "22:00",
            "end_time": time(6, 0, 0),
            "timezone": "America/Toronto",
        }, now=clock))
        self.assertEqual(seen, ["America/Toronto"])
        self.assertEqual(payload["dndFrom"], "02:00:00")
        self.assertEqual(payload["dndTo"], "10:00:00")
        self.assertNotEqual(payload["dndFrom"], "11:00:00")

    def test_disable_clears_both_clocks_without_inventing_times(self):
        hass, coordinator, _device_entry = _bound(_device(configuration={
            "dndFrom": "02:00:00",
            "dndTo": "10:00:00",
            "catDelay": 900,
        }))
        payload = _run(service_mod.async_handle_set_do_not_disturb(SimpleNamespace(
            hass=hass,
            data={"device_id": "ha-device-1", "enabled": False},
        )))
        self.assertIsNone(payload)
        body = coordinator.client.bodies[0]
        self.assertEqual(body["dndFrom"], "")
        self.assertEqual(body["dndTo"], "")
        self.assertEqual(body["catDelay"], 900)
        self.assertEqual(list(body), ["device_id", "dndFrom", "dndTo", "catDelay"])
        self.assertEqual(coordinator.refreshes, 1)

    def test_registered_callback_is_the_handler_and_preserves_siblings(self):
        hass, coordinator, _device_entry = _bound(_device(configuration={
            "mode": 1,
            "manual": 0,
            "volumeLevel": 4,
            "dndFrom": "02:00:00",
            "dndTo": "10:00:00",
            "timezone": "-05:00",
            "dstFrom": "03-08 07:00:00",
            "dstTo": "11-01 06:00:00",
        }))
        entry = SimpleNamespace(entry_id="entry-1")
        service_mod.async_setup_actions(hass, entry)
        stored = hass.services.registered["catgenie"]["set_do_not_disturb"]
        self.assertIs(stored["func"], service_mod.async_handle_set_do_not_disturb)
        self.assertIs(stored["supports_response"], _SupportsResponse.NONE)
        self.assertIsInstance(stored["schema"], type(sys.modules["homeassistant.helpers.config_validation"].probatio.Schema({"x": str}, extra="prevent")))
        _run(stored["func"](SimpleNamespace(
            hass=hass,
            data={
                "device_id": "ha-device-1",
                "enabled": True,
                "start_time": "22:00:00",
                "end_time": "06:00:00",
                "timezone": "America/Toronto",
                "reference_date": "2026-10-31",
            },
        )))
        body = coordinator.client.bodies[0]
        self.assertEqual(body["device_id"], "settings-device")
        self.assertEqual(set(body) - {"device_id"}, {"dndFrom", "dndTo", "catDelay"})
        self.assertEqual(body["catDelay"], 1800)
        self.assertNotIn("mode", body)
        self.assertNotIn("dstFrom", body)

    def test_entry_lifecycle_registers_once_and_removes_on_last_unload(self):
        hass, _coordinator, _device_entry = _bound()
        first = SimpleNamespace(entry_id="entry-a")
        second = SimpleNamespace(entry_id="entry-b")
        service_mod.async_setup_actions(hass, first)
        service_mod.async_setup_actions(hass, second)
        self.assertEqual(len(hass.services.registered["catgenie"]), 2)
        service_mod.async_unload_actions(hass, second)
        self.assertTrue(hass.services.has_service("catgenie", "set_do_not_disturb"))
        self.assertEqual(hass.services.removed, [])
        service_mod.async_unload_actions(hass, first)
        self.assertEqual(hass.services.removed, [("catgenie", "set_do_not_disturb"), ("catgenie", "set_schedule")])
        self.assertFalse(hass.services.has_service("catgenie", "set_do_not_disturb"))
        self.assertNotIn(actions.DND_ACTION_ENTRIES, hass.data)
        self.assertNotIn("catgenie", hass.data)

    def test_setup_failure_does_not_leave_a_handler(self):
        hass, _coordinator, _device_entry = _bound()
        hass.services.fail_register = True
        with self.assertRaises(RuntimeError):
            service_mod.async_setup_actions(hass, SimpleNamespace(entry_id="entry-a"))
        self.assertFalse(hass.services.has_service("catgenie", "set_do_not_disturb"))
        self.assertEqual(hass.services.removed, [("catgenie", "set_do_not_disturb")])
        self.assertNotIn(actions.DND_ACTION_ENTRIES, hass.data)

    def test_bad_input_and_resolution_do_no_vendor_io(self):
        cases = [
            {"device_id": "ha-device-1", "enabled": True, "start_time": "22:00:00", "end_time": "22:00:00", "timezone": "America/Toronto", "reference_date": "2026-10-31"},
            {"device_id": "ha-device-1", "enabled": True, "start_time": "02:30:00", "end_time": "06:00:00", "timezone": "America/New_York", "reference_date": "2026-03-08"},
            {"device_id": "ha-device-1", "enabled": True, "start_time": "01:30:00", "end_time": "06:00:00", "timezone": "America/New_York", "reference_date": "2026-11-01"},
            {"device_id": "ha-device-1", "enabled": True, "start_time": "02:15:00", "end_time": "06:00:00", "timezone": "Australia/Lord_Howe", "reference_date": "2026-10-04"},
            {"device_id": "ha-device-1", "enabled": True, "start_time": "01:45:00", "end_time": "06:00:00", "timezone": "Australia/Lord_Howe", "reference_date": "2026-04-05"},
            {"device_id": "ha-device-1", "enabled": True, "start_time": float("nan"), "end_time": "06:00:00", "timezone": "UTC"},
            {"device_id": "ha-device-1", "enabled": 1, "start_time": "22:00:00", "end_time": "06:00:00", "timezone": "UTC"},
            {"device_id": "ha-device-1", "enabled": True, "start_time": "22:00:00", "end_time": "06:00:00", "timezone": "-05:00"},
            {"device_id": "settings-device", "enabled": False, "mode": 1},
            {"device_id": "ha-device-1", "enabled": True, "start_time": "٢٢:٠٠:٠٠", "end_time": "06:00:00", "timezone": "UTC"},
        ]
        for data in cases:
            with self.subTest(data=data):
                hass, coordinator, _device_entry = _bound()
                with self.assertRaises(_error_type()):
                    _run(service_mod.async_handle_set_do_not_disturb(SimpleNamespace(hass=hass, data=data)))
                self.assertEqual(coordinator.client.methods, [])
                self.assertEqual(coordinator.refreshes, 0)

    def test_missing_foreign_and_ambiguous_targets_do_no_io(self):
        hass, coordinator, device_entry = _bound()
        missing = dict(device_id="missing", enabled=False)
        with self.assertRaises(_error_type()):
            _run(service_mod.async_handle_set_do_not_disturb(SimpleNamespace(hass=hass, data=missing)))
        device_entry.manufacturer = "Other"
        with self.assertRaises(_error_type()):
            _run(service_mod.async_handle_set_do_not_disturb(SimpleNamespace(
                hass=hass, data={"device_id": "ha-device-1", "enabled": False}
            )))
        device_entry.manufacturer = "PetNovations"
        device_entry.identifiers = {("other", "settings-device")}
        with self.assertRaises(_error_type()):
            _run(service_mod.async_handle_set_do_not_disturb(SimpleNamespace(
                hass=hass, data={"device_id": "ha-device-1", "enabled": False}
            )))
        device_entry.identifiers = {("catgenie", "settings-device"), ("catgenie", "other")}
        with self.assertRaises(_error_type()):
            _run(service_mod.async_handle_set_do_not_disturb(SimpleNamespace(
                hass=hass, data={"device_id": "ha-device-1", "enabled": False}
            )))
        device_entry.identifiers = {("catgenie", "settings-device")}
        device_entry.is_composite_device = True
        with self.assertRaises(_error_type()):
            _run(service_mod.async_handle_set_do_not_disturb(SimpleNamespace(
                hass=hass, data={"device_id": "ha-device-1", "enabled": False}
            )))
        self.assertEqual(coordinator.client.methods, [])

    def test_unknown_dnd_bad_delay_failed_get_and_failed_put_do_no_extra_io(self):
        unknown = _device(configuration={"dndFrom": "", "dndTo": "10:00:00"})
        hass, coordinator, _device_entry = _bound(unknown, fresh=[unknown])
        with self.assertRaises(_error_type()) as caught:
            _run(service_mod.async_handle_set_do_not_disturb(SimpleNamespace(
                hass=hass, data={"device_id": "ha-device-1", "enabled": False}
            )))
        self.assertIn("not a supported pair", str(caught.exception))
        self.assertEqual(coordinator.client.methods, ["get_devices"])
        self.assertEqual(coordinator.refreshes, 0)

        odd = _device(configuration={"catDelay": 100})
        hass, coordinator, _device_entry = _bound(odd, fresh=[odd])
        with self.assertRaises(_error_type()):
            _run(service_mod.async_handle_set_do_not_disturb(SimpleNamespace(
                hass=hass, data={"device_id": "ha-device-1", "enabled": False}
            )))
        self.assertEqual(coordinator.client.methods, ["get_devices"])
        self.assertEqual(coordinator.client.bodies, [])

        hass, coordinator, _device_entry = _bound()
        coordinator.client.read_error = TimeoutError("vendor secret")
        with self.assertRaises(_error_type()) as caught:
            _run(service_mod.async_handle_set_do_not_disturb(SimpleNamespace(
                hass=hass, data={"device_id": "ha-device-1", "enabled": False}
            )))
        self.assertIn("TimeoutError", str(caught.exception))
        self.assertNotIn("secret", str(caught.exception))
        self.assertEqual(coordinator.client.methods, ["get_devices"])
        self.assertEqual(coordinator.refreshes, 0)

        hass, coordinator, _device_entry = _bound()
        coordinator.client.error = ConnectionError("vendor secret")
        with self.assertRaises(_error_type()) as caught:
            _run(service_mod.async_handle_set_do_not_disturb(SimpleNamespace(
                hass=hass, data={"device_id": "ha-device-1", "enabled": False}
            )))
        self.assertIn("ConnectionError", str(caught.exception))
        self.assertIn("unconfirmed", str(caught.exception))
        self.assertNotIn("not changed", str(caught.exception))
        self.assertNotIn("secret", str(caught.exception))
        self.assertEqual(coordinator.client.methods, ["get_devices", "update_configuration"])
        self.assertEqual(coordinator.refreshes, 0)
        self.assertEqual(len(coordinator.client.bodies), 1)

    def test_readback_failure_does_not_retry_or_roll_back(self):
        hass, coordinator, _device_entry = _bound()

        async def fail_refresh() -> None:
            coordinator.refreshes += 1
            raise RuntimeError("vendor secret")

        coordinator.async_request_refresh = fail_refresh
        with self.assertRaises(_error_type()) as caught:
            _run(service_mod.async_handle_set_do_not_disturb(SimpleNamespace(
                hass=hass, data={"device_id": "ha-device-1", "enabled": False}
            )))
        self.assertIn("readback", str(caught.exception))
        self.assertIn("RuntimeError", str(caught.exception))
        self.assertNotIn("secret", str(caught.exception))
        self.assertEqual(coordinator.client.methods, ["get_devices", "update_configuration"])
        self.assertEqual(len(coordinator.client.bodies), 1)

    def test_offline_cache_skips_get(self):
        offline = _device(reportedStatus="disconnected")
        hass, coordinator, _device_entry = _bound(offline)
        with self.assertRaises(_error_type()):
            _run(service_mod.async_handle_set_do_not_disturb(SimpleNamespace(
                hass=hass, data={"device_id": "ha-device-1", "enabled": False}
            )))
        self.assertEqual(coordinator.client.methods, [])

    def test_registration_matches_pinned_public_signatures(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("ha_service_registry_signatures", SIGNATURES)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        pinned = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pinned)
        self.assertEqual(pinned.ASYNC_REGISTER_2026[:7], pinned.ASYNC_REGISTER_2025)
        self.assertIn("schema", pinned.ASYNC_REGISTER_2026)
        self.assertEqual(pinned.ASYNC_REMOVE, ("self", "domain", "service"))
        self.assertTrue(pinned.SCHEMA_IS_CALLABLE)
        self.assertIn("2026.10.4", SIGNATURES.read_text(encoding="utf-8"))
        self.assertIn("2025.1.0", SIGNATURES.read_text(encoding="utf-8"))
        self.assertNotRegex(
            SIGNATURES.read_text(encoding="utf-8"),
            r"(?:/home/|/Users/|/root/|[A-Za-z]:\\Users\\)",
        )
        services_tree = ast.parse((COMPONENT / "services.py").read_text(encoding="utf-8"))
        calls = [
            node for node in ast.walk(services_tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]
        register_calls = [node for node in calls if node.func.attr == "async_register"]
        remove_calls = [node for node in calls if node.func.attr == "async_remove"]
        self.assertEqual(len(register_calls), 1)
        self.assertGreaterEqual(len(remove_calls), 1)
        register_call = register_calls[0]
        self.assertEqual(len(register_call.args), 5)
        self.assertIsInstance(register_call.args[4], ast.Attribute)
        self.assertEqual(register_call.args[4].attr, "NONE")
        self.assertFalse(any(isinstance(node, ast.ExceptHandler) and _handler_skips_import(node) for node in ast.walk(services_tree)))
        init_tree = ast.parse((COMPONENT / "__init__.py").read_text(encoding="utf-8"))
        setup = _function(init_tree, "async_setup_entry")
        forward = action = None
        for node in ast.walk(setup):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "async_forward_entry_setups":
                forward = node.lineno
            if isinstance(func, ast.Name) and func.id == "async_setup_actions":
                action = node.lineno
        self.assertIsNotNone(forward)
        self.assertIsNotNone(action)
        self.assertLess(forward, action)
        action_tree = ast.parse((COMPONENT / "dnd_actions.py").read_text(encoding="utf-8"))
        imported = " ".join(
            node.module or ""
            for node in ast.walk(action_tree)
            if isinstance(node, ast.ImportFrom)
        )
        self.assertNotIn("settings_pending", imported)
        source = (COMPONENT / "dnd_actions.py").read_text(encoding="utf-8") + (COMPONENT / "services.py").read_text(encoding="utf-8")
        for forbidden in ("set_dnd", "set_schedule", "start_cleaning", "async_clean", "import probatio", "VolSchemaType"):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("Toronto", source)
        schedule = ast.parse((COMPONENT / "schedule.py").read_text(encoding="utf-8"))
        self.assertIn("sendable=False", ast.unparse(schedule))
        description = json.loads((COMPONENT / "translations" / "en.json").read_text(encoding="utf-8"))
        self.assertIn("set_do_not_disturb", description["services"])
        yaml_text = (COMPONENT / "services.yaml").read_text(encoding="utf-8")
        for needle in ("device:", "boolean:", "time:", "date:", "text:", "multiple: false"):
            self.assertIn(needle, yaml_text)
        self.assertNotIn("custom frontend", yaml_text.lower())

    def test_registered_callbacks_resolve_both_actions_once(self):
        hass, coordinator, device_entry = _bound()
        schedule = device_entry  # registry entry returned to the schedule handler
        self.assertEqual(schedule.id, "ha-device-1")
        fresh = _device()
        self.assertEqual(
            set(fresh.configuration.schedule[0].model_fields_set) & {"hour", "minute", "day", "enabled"},
            {"hour", "minute"},
        )
        self.assertEqual(set(fresh.configuration.schedule[0].model_extra or {}), {"time"})
        coordinator.client.fresh_devices = [fresh]
        coordinator.data = {fresh.manufacturer_id: fresh}
        service_mod.async_setup_actions(hass, SimpleNamespace(entry_id="entry-1"))
        registered = hass.services.registered["catgenie"]
        dnd = registered["set_do_not_disturb"]
        schedule_call = registered["set_schedule"]
        self.assertIs(dnd["func"], service_mod.async_handle_set_do_not_disturb)
        with self.assertRaises(_Invalid):
            dnd["schema"]({"device_id": "ha-device-1", "enabled": "yes"})
        with self.assertRaises(_Invalid):
            dnd["schema"]({"device_id": "ha-device-1", "enabled": True, "mode": 1})
        _run(dnd["func"](SimpleNamespace(
            hass=hass,
            data={"device_id": "ha-device-1", "enabled": False},
        )))
        self.assertEqual(coordinator.client.methods, ["get_devices", "update_configuration"])
        self.assertEqual(coordinator.refreshes, 1)
        coordinator.client.methods.clear()
        coordinator.client.bodies.clear()
        coordinator.refreshes = 0
        from custom_components.catgenie import schedule_actions

        # The handler's Device class is the one it imported. Rebuild the
        # string-origin snapshot with that class so the isinstance check is real.
        payload = harness.device_payload()
        library_device = schedule_actions.Device.model_validate(payload)
        entry = library_device.configuration.schedule[0]
        self.assertEqual(set(entry.model_extra or {}), {"time"})
        self.assertEqual(
            set(entry.model_fields_set) & set(schedule_actions.ScheduleEntry.model_fields),
            {"hour", "minute"},
        )
        coordinator.data = {library_device.manufacturer_id: library_device}
        coordinator.client.fresh_devices = [library_device]
        _run(schedule_call["func"](SimpleNamespace(
            hass=hass,
            data={
                "device_id": "ha-device-1",
                "times": [{"time": "07:00:00"}, {"time": "19:00:00"}],
                "zone": "America/New_York",
                "reference_date": "2026-10-31",
            },
        )))
        self.assertEqual(coordinator.client.methods, ["get_devices", "update_configuration"])
        self.assertEqual(coordinator.refreshes, 1)
        body = coordinator.client.bodies[0]
        self.assertEqual(set(body) - {"device_id"}, {"schedule"})

    def test_legacy_config_entries_one_match_foreign_sibling_and_ambiguous(self):
        hass, coordinator, device_entry = _bound()
        del device_entry.config_entry_id
        device_entry.config_entries = {"entry-1", "foreign-1"}
        foreign = SimpleNamespace(domain="other", entry_id="foreign-1", runtime_data=None, data={"id": "raw"})
        hass.config_entries = SimpleNamespace(async_get_entry=lambda entry_id: {
            "entry-1": SimpleNamespace(domain="catgenie", entry_id="entry-1", runtime_data=coordinator),
            "foreign-1": foreign,
        }.get(entry_id))
        _run(service_mod.async_handle_set_do_not_disturb(SimpleNamespace(
            hass=hass, data={"device_id": "ha-device-1", "enabled": False},
        )))
        self.assertEqual(coordinator.client.methods, ["get_devices", "update_configuration"])
        self.assertEqual(coordinator.refreshes, 1)

        hass, coordinator, device_entry = _bound()
        del device_entry.config_entry_id
        device_entry.config_entries = {"entry-1", "entry-2"}
        hass.config_entries = SimpleNamespace(async_get_entry=lambda entry_id: SimpleNamespace(
            domain="catgenie", entry_id=entry_id, runtime_data=coordinator,
        ))
        with self.assertRaises(_error_type()):
            _run(service_mod.async_handle_set_do_not_disturb(SimpleNamespace(
                hass=hass, data={"device_id": "ha-device-1", "enabled": False},
            )))
        self.assertEqual(coordinator.client.methods, [])

        hass, coordinator, device_entry = _bound()
        del device_entry.config_entry_id
        device_entry.config_entries = {"foreign-1"}
        hass.config_entries = SimpleNamespace(async_get_entry=lambda entry_id: SimpleNamespace(
            domain="other", entry_id=entry_id, data={"manufacturer_id": "settings-device"},
        ))
        with self.assertRaises(_error_type()):
            _run(service_mod.async_handle_set_do_not_disturb(SimpleNamespace(
                hass=hass, data={"device_id": "ha-device-1", "enabled": False},
            )))
        self.assertEqual(coordinator.client.methods, [])

    def test_current_device_does_not_read_deprecated_config_entries(self):
        hass, coordinator, device_entry = _bound()

        class _CurrentDevice:
            def __init__(self) -> None:
                self.id = device_entry.id
                self.config_entry_id = device_entry.config_entry_id
                self.identifiers = device_entry.identifiers
                self.manufacturer = device_entry.manufacturer
                self.disabled_by = None
                self.is_composite_device = False

            @property
            def config_entries(self):
                raise AssertionError("config_entries was read")

        current = _CurrentDevice()
        hass.registry = SimpleNamespace(async_get=lambda device_id: current if device_id == current.id else None)
        _run(service_mod.async_handle_set_do_not_disturb(SimpleNamespace(
            hass=hass, data={"device_id": "ha-device-1", "enabled": False},
        )))
        self.assertEqual(coordinator.client.methods, ["get_devices", "update_configuration"])

    def test_stale_cache_refuses_before_get(self):
        hass, coordinator, _device_entry = _bound()
        coordinator.last_update_success = False
        with self.assertRaises(_error_type()) as caught:
            _run(service_mod.async_handle_set_do_not_disturb(SimpleNamespace(
                hass=hass, data={"device_id": "ha-device-1", "enabled": False},
            )))
        self.assertIn("unavailable", str(caught.exception))
        self.assertEqual(coordinator.client.methods, [])
        self.assertEqual(coordinator.refreshes, 0)

    def test_second_register_failure_removes_only_the_new_service(self):
        hass, _coordinator, _device_entry = _bound()
        hass.services.async_register(
            "catgenie", "set_do_not_disturb", lambda call: None, None, _SupportsResponse.NONE,
        )
        hass.services.fail_on = "set_schedule"
        with self.assertRaises(RuntimeError):
            service_mod.async_setup_actions(hass, SimpleNamespace(entry_id="entry-a"))
        self.assertTrue(hass.services.has_service("catgenie", "set_do_not_disturb"))
        self.assertFalse(hass.services.has_service("catgenie", "set_schedule"))
        self.assertEqual(hass.services.removed, [("catgenie", "set_schedule")])
        self.assertNotIn(actions.DND_ACTION_ENTRIES, hass.data)

    def test_second_entry_keeps_services_and_last_unload_removes_both(self):
        hass, _coordinator, _device_entry = _bound()
        first = SimpleNamespace(entry_id="entry-a")
        second = SimpleNamespace(entry_id="entry-b")
        service_mod.async_setup_actions(hass, first)
        service_mod.async_setup_actions(hass, second)
        service_mod.async_unload_actions(hass, second)
        self.assertTrue(hass.services.has_service("catgenie", "set_do_not_disturb"))
        self.assertTrue(hass.services.has_service("catgenie", "set_schedule"))
        self.assertEqual(hass.services.removed, [])
        service_mod.async_unload_actions(hass, first)
        self.assertEqual(
            hass.services.removed,
            [("catgenie", "set_do_not_disturb"), ("catgenie", "set_schedule")],
        )
        self.assertFalse(hass.services.has_service("catgenie", "set_do_not_disturb"))
        self.assertFalse(hass.services.has_service("catgenie", "set_schedule"))

    def test_missing_backend_cleans_nothing_and_ignores_global_library(self):
        validation = sys.modules["homeassistant.helpers.config_validation"]
        saved = (validation.probatio, validation.vol)
        validation.probatio = None
        validation.vol = None
        hass, _coordinator, _device_entry = _bound()
        try:
            with self.assertRaises(service_mod.ServiceRegistrationContractError):
                service_mod.async_setup_actions(hass, SimpleNamespace(entry_id="entry-z"))
            self.assertFalse(hass.services.has_service("catgenie", "set_do_not_disturb"))
            self.assertFalse(hass.services.has_service("catgenie", "set_schedule"))
            self.assertNotIn(actions.DND_ACTION_ENTRIES, hass.data)
            self.assertIn("probatio", sys.modules)
        finally:
            validation.probatio, validation.vol = saved

    def test_legacy_and_current_backends_restore_module_globals(self):
        validation = sys.modules["homeassistant.helpers.config_validation"]
        before = {
            name: sys.modules.get(name)
            for name in (
                "homeassistant.helpers.config_validation",
                "probatio",
                "voluptuous",
            )
        }
        saved = (validation.probatio, validation.vol)
        try:
            for use_name, backend in (("probatio", saved[0]), ("vol", saved[1])):
                validation.probatio = saved[0] if use_name == "probatio" else None
                validation.vol = saved[1] if use_name == "vol" else None
                schema = service_mod.build_registered_schema()
                self.assertIsInstance(schema, backend.Schema)
                with self.assertRaises(backend.Invalid) as caught:
                    schema({"device_id": "device", "enabled": 1})
                self.assertNotIsInstance(caught.exception, _error_type())
                with self.assertRaises(backend.Invalid):
                    schema({"device_id": "device", "enabled": True, "extra": 1})
                self.assertIs(
                    schema({"device_id": "device", "enabled": False})["enabled"],
                    False,
                )
        finally:
            validation.probatio, validation.vol = saved
            for name, module in before.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module
        self.assertIs(validation.probatio, saved[0])
        self.assertIs(validation.vol, saved[1])
        self.assertIs(sys.modules.get("probatio"), before["probatio"])


def _function(tree: ast.AST, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(name)


def _method(tree: ast.AST, class_name: str, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name:
                return item
    raise AssertionError(f"{class_name}.{name}")


def _handler_skips_import(node: ast.ExceptHandler) -> bool:
    if node.type is None:
        return False
    rendered = ast.unparse(node.type)
    return "ImportError" in rendered or "ModuleNotFoundError" in rendered


if __name__ == "__main__":
    unittest.main()
