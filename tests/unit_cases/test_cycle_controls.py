"""SYNTHETIC abort and no-scoop regressions. Not a live device command.

Payloads use the pinned CatGenie models. Home Assistant and HTTP are stubbed.
A constructed state-4 or state-129 body is not proof the firmware accepted it.
State 129 is sent only after the traced fwVersion gate. It is not a finishing
cycle and not a replacement for Stop.
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
PAUSE_KEY = "pause_cleaning"
RESUME_KEY = "resume_cleaning"
ABORT_KEY = "abort_cleaning"
NO_SCOOP_KEY = "no_scoop_cleaning"
OPERATION_PATH = "device/management/{device_id}/operation"
THRESHOLD = (8, 5, 81)
_MAX_SAFE_COMPONENT = "9007199254740991"
_OVER_SAFE_COMPONENT = "9007199254740992"
_FIVE_THOUSAND_DIGITS = "9" * 5000 + ".0.0"
_WITHIN_LENGTH_OVERSIZE = "9" * 252 + ".0.0"


def _case_label(value: object) -> str:
    """Keep subtests readable when a firmware string is thousands of digits."""
    if isinstance(value, str) and len(value) > 48:
        return f"{value[:16]}...({len(value)} chars)"
    return repr(value)


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
    class ButtonEntityDescription:
        key: str
        translation_key: str | None = None
        entity_registry_enabled_default: bool = True
        entity_category: object = None

    class EntityCategory:
        CONFIG = "config"
        DIAGNOSTIC = "diagnostic"

    class CoordinatorEntity(_Subscriptable):
        def __init__(self, coordinator: object) -> None:
            self.coordinator = coordinator

        @property
        def available(self) -> bool:
            return True

    class DeviceInfo(dict):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)

    class Platform:
        BINARY_SENSOR = "binary_sensor"
        BUTTON = "button"
        NUMBER = "number"
        SELECT = "select"
        SENSOR = "sensor"
        SWITCH = "switch"

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
    button = _stub(
        "homeassistant.components.button",
        ButtonEntity=object,
        ButtonEntityDescription=ButtonEntityDescription,
    )
    helpers = _stub("homeassistant.helpers")
    ha.const = const
    ha.exceptions = exceptions
    ha.components = components
    ha.helpers = helpers
    components.button = button
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
    from catgenie.auth import Credentials
    from catgenie.const import ENDPOINT_DEVICE_OPERATION
    from catgenie.exceptions import CatGenieAPIError, CatGenieException
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.catgenie.button import BUTTONS, CatGenieButton, async_setup_entry
    from custom_components.catgenie.client import HomeAssistantCatGenieClient
    from custom_components.catgenie.operation_state import TolerantDevice
    from custom_components.catgenie.operation_status import explicit_online

    try:
        from custom_components.catgenie.abort import post_abort
    except ImportError:
        post_abort = None
    try:
        from custom_components.catgenie.no_scoop import (
            post_no_scoop,
            special_cycle_firmware_eligible,
        )
    except ImportError:
        post_no_scoop = None
        special_cycle_firmware_eligible = None
    try:
        from custom_components.catgenie.operation_post import (
            OperationNotSent,
            post_allowed_operation,
            post_literal_state,
        )
    except ImportError:
        post_allowed_operation = None
        post_literal_state = None

_MODULES_AFTER = {
    name: module
    for name, module in sys.modules.items()
    if any(name == prefix or name.startswith(prefix + ".") for prefix in _SEAM_PREFIXES)
}
_PATH_AFTER = tuple(sys.path)


def _payload(
    manufacturer_id: str,
    state: int,
    reported: object = "connected",
    fw: str = "8.7.205R",
) -> dict:
    payload: dict = {
        "_fixture": FIXTURE,
        "manufacturerId": manufacturer_id,
        "name": f"{FIXTURE}-{manufacturer_id}",
        "macAddress": "aa:bb:cc:dd:ee:ff",
        "hwRevision": "1",
        "fwVersion": fw,
        "status": state,
        "operationStatus": {"state": state, "progress": 0},
    }
    if reported is not _OMIT:
        payload["reportedStatus"] = reported
    return payload


class _Omit:
    pass


_OMIT = _Omit()


def _device(
    manufacturer_id: str,
    state: int = 0,
    reported: object = "connected",
    fw: str = "8.7.205R",
):
    return TolerantDevice.model_validate(_payload(manufacturer_id, state, reported, fw))


class _Coordinator:
    def __init__(self, device, client) -> None:
        self.data = {device.manufacturer_id: device}
        self.client = client
        self.refreshes = 0

    async def async_request_refresh(self) -> None:
        self.refreshes += 1


class _Writer:
    def __init__(self, error: BaseException | None = None) -> None:
        self.calls: list[tuple] = []
        self.start_calls: list[str] = []
        self.stop_calls: list[str] = []
        self.error = error

    async def _request(self, method, path, body=None, params=None):
        self.calls.append((method, path, None if body is None else dict(body), params))
        if self.error is not None:
            raise self.error
        return {"fixture": FIXTURE}

    async def start_cleaning(self, device_id: str):
        self.start_calls.append(device_id)
        raise AssertionError("cycle control must not call start_cleaning")

    async def stop_cleaning(self, device_id: str):
        self.stop_calls.append(device_id)
        raise AssertionError("cycle control must not call stop_cleaning")


def _button(key: str, device, client) -> CatGenieButton:
    description = next(item for item in BUTTONS if item.key == key)
    return CatGenieButton(_Coordinator(device, client), device.manufacturer_id, description)


class CycleControlTests(unittest.TestCase):
    def test_import_seams_restore(self) -> None:
        self.assertEqual(_MODULES_AFTER, _MODULES_BEFORE)
        self.assertEqual(_PATH_AFTER, _PATH_BEFORE)

    def test_abort_and_no_scoop_helpers_exist(self) -> None:
        self.assertIsNotNone(post_abort, "abort helper missing")
        self.assertIsNotNone(post_no_scoop, "no-scoop helper missing")
        self.assertIsNotNone(special_cycle_firmware_eligible, "firmware gate missing")
        self.assertIsNotNone(post_allowed_operation)
        self.assertIsNotNone(post_literal_state)

    def test_pinned_start_and_stop_stay_state_1_and_0(self) -> None:
        source = (Path(__import__("catgenie").__file__).parent / "client.py").read_text()
        tree = ast.parse(source)
        bodies = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name in {
                "start_cleaning",
                "stop_cleaning",
            }:
                bodies[node.name] = ast.unparse(node)
        self.assertEqual(ENDPOINT_DEVICE_OPERATION, OPERATION_PATH)
        self.assertIn("body={'state': 1}", bodies["start_cleaning"])
        self.assertIn("body={'state': 0}", bodies["stop_cleaning"])
        abort_text = (INTEGRATION / "abort.py").read_text()
        self.assertIn("{'state': 4}", ast.unparse(ast.parse(abort_text)))
        self.assertNotIn("client._request", abort_text)
        self.assertNotIn("start_cleaning", abort_text)
        self.assertNotIn("stop_cleaning", abort_text)
        self.assertNotIn("129", abort_text)
        no_scoop_text = (INTEGRATION / "no_scoop.py").read_text()
        self.assertIn("129", no_scoop_text)
        self.assertNotIn("client._request", no_scoop_text)
        self.assertNotIn("start_cleaning", no_scoop_text)
        self.assertNotIn("stop_cleaning", no_scoop_text)
        shared = (INTEGRATION / "operation_post.py").read_text()
        self.assertIn("client._request", shared)
        command_modules = (
            "abort.py",
            "no_scoop.py",
            "pause.py",
            "resume.py",
            "button.py",
            "operation_post.py",
        )
        request_sites = [
            name
            for name in command_modules
            if "client._request" in (INTEGRATION / name).read_text()
        ]
        self.assertEqual(request_sites, ["operation_post.py"])

    def test_button_ids_keep_start_stop_pause_resume_and_add_opt_in(self) -> None:
        keys = [item.key for item in BUTTONS]
        self.assertEqual(
            keys,
            [
                "start_cleaning",
                "stop_cleaning",
                PAUSE_KEY,
                RESUME_KEY,
                ABORT_KEY,
                NO_SCOOP_KEY,
            ],
        )
        by_key = {item.key: item for item in BUTTONS}
        self.assertTrue(by_key["start_cleaning"].entity_registry_enabled_default)
        self.assertTrue(by_key["stop_cleaning"].entity_registry_enabled_default)
        self.assertTrue(by_key["start_cleaning"].requires_explicit_online)
        self.assertTrue(by_key["stop_cleaning"].requires_explicit_online)
        self.assertFalse(by_key["start_cleaning"].requires_firmware_gate)
        self.assertFalse(by_key["stop_cleaning"].requires_firmware_gate)
        for key in (PAUSE_KEY, RESUME_KEY, ABORT_KEY, NO_SCOOP_KEY):
            item = by_key[key]
            self.assertEqual(item.translation_key, key)
            self.assertTrue(item.entity_registry_enabled_default)
            self.assertTrue(item.requires_explicit_online)
            self.assertIsNone(item.entity_category)
        self.assertFalse(by_key[ABORT_KEY].requires_firmware_gate)
        self.assertTrue(by_key[NO_SCOOP_KEY].requires_firmware_gate)
        self.assertIs(by_key[ABORT_KEY].press_fn, post_abort)
        self.assertIs(by_key[NO_SCOOP_KEY].press_fn, post_no_scoop)
        self.assertEqual(
            by_key[ABORT_KEY].offline_message,
            "CatGenie is not online; abort was not sent.",
        )
        self.assertEqual(
            by_key[NO_SCOOP_KEY].offline_message,
            "CatGenie is not online; no-scoop was not sent.",
        )
        device = _device("unit-a")
        self.assertEqual(_button(ABORT_KEY, device, _Writer())._attr_unique_id, "unit-a_abort_cleaning")
        self.assertEqual(
            _button(NO_SCOOP_KEY, device, _Writer())._attr_unique_id,
            "unit-a_no_scoop_cleaning",
        )
        self.assertEqual(_button("start_cleaning", device, _Writer())._attr_unique_id, "unit-a_start_cleaning")
        self.assertEqual(_button("stop_cleaning", device, _Writer())._attr_unique_id, "unit-a_stop_cleaning")
        self.assertEqual(_button(PAUSE_KEY, device, _Writer())._attr_unique_id, "unit-a_pause_cleaning")
        self.assertEqual(_button(RESUME_KEY, device, _Writer())._attr_unique_id, "unit-a_resume_cleaning")
        buttons = json.loads((INTEGRATION / "translations" / "en.json").read_text())["entity"]["button"]
        self.assertEqual(buttons["start_cleaning"]["name"], "Start cleaning")
        self.assertEqual(buttons["stop_cleaning"]["name"], "Stop cleaning")
        self.assertEqual(buttons[PAUSE_KEY]["name"], "Pause cleaning")
        self.assertEqual(buttons[RESUME_KEY]["name"], "Resume cleaning")
        self.assertEqual(buttons[ABORT_KEY]["name"], "Abort cleaning")
        self.assertEqual(buttons[NO_SCOOP_KEY]["name"], "No-scoop wash")
        self.assertEqual(set(buttons), set(keys))
        registry_writers = []
        # Reviewed settings actions read the entity registry for caller
        # permission and read device.disabled_by to refuse a disabled device.
        # They must not update the entity registry or assign disabled_by.
        read_only = {"action_permissions.py", "dnd_actions.py"}
        for path in (CANDIDATE / "custom_components" / "catgenie").glob("*.py"):
            text = path.read_text()
            if "async_update_entity" in text or "disabled_by=" in text or "disabled_by =" in text:
                registry_writers.append(path.name)
                continue
            hit = ("async_get(" in text and "entity_registry" in text) or "disabled_by" in text
            if hit and path.name not in read_only:
                registry_writers.append(path.name)
        self.assertEqual(registry_writers, [])
        self.assertIn(
            "entity_registry",
            (CANDIDATE / "custom_components" / "catgenie" / "action_permissions.py").read_text(),
        )
        self.assertIn(
            "getattr(device, \"disabled_by\", None)",
            (CANDIDATE / "custom_components" / "catgenie" / "dnd_actions.py").read_text(),
        )

    def test_setup_does_not_press_or_send(self) -> None:
        device = _device("unit-a", state=1)
        client = _Writer()
        coordinator = _Coordinator(device, client)

        class _Entry:
            runtime_data = coordinator

        added: list = []
        asyncio.run(async_setup_entry(object(), _Entry(), added.extend))
        self.assertEqual(
            [entity._attr_unique_id for entity in added],
            [
                "unit-a_start_cleaning",
                "unit-a_stop_cleaning",
                "unit-a_pause_cleaning",
                "unit-a_resume_cleaning",
                "unit-a_abort_cleaning",
                "unit-a_no_scoop_cleaning",
            ],
        )
        self.assertEqual(client.calls, [])
        self.assertEqual(client.start_calls, [])
        self.assertEqual(client.stop_calls, [])
        self.assertEqual(coordinator.refreshes, 0)

    def test_online_abort_sends_only_state_4(self) -> None:
        self.assertIsNotNone(post_abort)
        for state, fw in ((0, "1.0.0"), (1, "8.5.80"), (2, "8.7.205R"), (4, "9.0.0"), (129, "8.5.81")):
            with self.subTest(state=state, fw=fw):
                device = _device(f"unit-{state}", state=state, reported="Connected", fw=fw)
                writer = _Writer()
                entity = _button(ABORT_KEY, device, writer)
                snapshot = dict(entity.coordinator.data)
                self.assertTrue(entity.available)
                asyncio.run(entity.async_press())
                self.assertEqual(len(writer.calls), 1)
                method, path, body, params = writer.calls[0]
                self.assertEqual(method, "POST")
                self.assertEqual(path, OPERATION_PATH.format(device_id=device.manufacturer_id))
                self.assertEqual(body, {"state": 4})
                self.assertIs(type(body["state"]), int)
                self.assertIsNone(params)
                self.assertEqual(writer.start_calls, [])
                self.assertEqual(writer.stop_calls, [])
                self.assertEqual(entity.coordinator.refreshes, 1)
                self.assertEqual(entity.coordinator.data, snapshot)

    def test_abort_offline_does_not_send(self) -> None:
        for name, reported in {
            "disconnected": "disconnected",
            "empty": "",
            "omitted": _OMIT,
        }.items():
            with self.subTest(name=name):
                device = _device("unit-off", state=1, reported=reported, fw="8.7.205R")
                writer = _Writer()
                entity = _button(ABORT_KEY, device, writer)
                self.assertFalse(entity.available)
                with self.assertRaises(HomeAssistantError) as raised:
                    asyncio.run(entity.async_press())
                self.assertIn("abort was not sent", str(raised.exception).lower())
                self.assertEqual(writer.calls, [])
                self.assertEqual(writer.start_calls, [])
                self.assertEqual(writer.stop_calls, [])
                self.assertEqual(entity.coordinator.refreshes, 0)

    def test_stop_button_is_not_replaced_by_abort(self) -> None:
        device = _device("unit-a", state=1, reported="connected")
        writer = _Writer()

        async def stop_cleaning(device_id: str):
            writer.stop_calls.append(device_id)
            return {"stopped": FIXTURE}

        writer.stop_cleaning = stop_cleaning
        stop = _button("stop_cleaning", device, writer)
        abort = _button(ABORT_KEY, device, writer)
        self.assertTrue(stop.available)
        self.assertTrue(abort.available)
        asyncio.run(stop.async_press())
        self.assertEqual(writer.stop_calls, ["unit-a"])
        self.assertEqual(writer.calls, [])
        button_source = (INTEGRATION / "button.py").read_text()
        self.assertIn("client.stop_cleaning(mid)", button_source)
        self.assertIn("client.start_cleaning(mid)", button_source)
        self.assertNotIn("client.stop_cleaning", (INTEGRATION / "abort.py").read_text())

    def test_firmware_gate_boundaries(self) -> None:
        self.assertIsNotNone(special_cycle_firmware_eligible)
        eligible = (
            "8.5.81",
            "8.5.81R",
            "8.5.82",
            "8.6.0",
            "8.10.0",
            "9.0.0",
            "8.7.205R",
            "v8.5.81",
            "8.5.810",
            f"{_MAX_SAFE_COMPONENT}.0.0",
            f"8.{_MAX_SAFE_COMPONENT}.0",
            f"8.5.{_MAX_SAFE_COMPONENT}",
        )
        refused = (
            None,
            "",
            "R",
            "abc",
            "8.5.80",
            "8.5.80R",
            "8.5.9",
            "8.4.999",
            "7.9.999",
            "8.5",
            "8",
            "8.5.81.1",
            "08.5.81",
            "8.05.81",
            "8.5.081",
            " 8.5.81",
            "8.5.81 ",
            "8.5.81-rc1",
            "8.5.81+build",
            True,
            False,
            8,
            8.5,
            f"{_OVER_SAFE_COMPONENT}.0.0",
            f"8.{_OVER_SAFE_COMPONENT}.0",
            f"8.5.{_OVER_SAFE_COMPONENT}",
            _FIVE_THOUSAND_DIGITS,
            "9" * 257,
            _WITHIN_LENGTH_OVERSIZE,
        )
        for value in eligible:
            with self.subTest(eligible=_case_label(value)):
                self.assertTrue(special_cycle_firmware_eligible(value), _case_label(value))
        for value in refused:
            with self.subTest(refused=_case_label(value)):
                try:
                    eligible = special_cycle_firmware_eligible(value)
                except Exception as error:
                    self.fail(
                        f"{_case_label(value)} raised {type(error).__name__}: {error}"
                    )
                self.assertFalse(eligible, _case_label(value))


    def test_no_scoop_sends_129_only_when_gate_passes(self) -> None:
        self.assertIsNotNone(post_no_scoop)
        for fw in ("8.5.81", "8.5.81R", "8.6.0", "8.10.0", "8.7.205R", "9.0.0"):
            for state in (0, 1, 2, 3, 4, 129):
                with self.subTest(fw=fw, state=state):
                    device = _device(f"ok-{state}", state=state, reported="connected", fw=fw)
                    writer = _Writer()
                    entity = _button(NO_SCOOP_KEY, device, writer)
                    self.assertTrue(explicit_online(device))
                    self.assertTrue(entity.available)
                    snapshot = dict(entity.coordinator.data)
                    asyncio.run(entity.async_press())
                    self.assertEqual(writer.calls[0][2], {"state": 129})
                    self.assertIs(type(writer.calls[0][2]["state"]), int)
                    self.assertEqual(writer.calls[0][0], "POST")
                    self.assertEqual(
                        writer.calls[0][1],
                        OPERATION_PATH.format(device_id=device.manufacturer_id),
                    )
                    self.assertEqual(writer.start_calls, [])
                    self.assertEqual(writer.stop_calls, [])
                    self.assertEqual(entity.coordinator.refreshes, 1)
                    self.assertEqual(entity.coordinator.data, snapshot)

    def test_no_scoop_refuses_ineligible_or_malformed_without_request(self) -> None:
        self.assertIsNotNone(post_no_scoop)
        for fw in ("8.5.80", "8.5.9", "8.5", "08.5.81", "R", "", "8.5.81-rc1", " 8.5.81"):
            with self.subTest(fw=fw):
                device = _device("unit-low", state=1, reported="connected", fw=fw)
                writer = _Writer()
                entity = _button(NO_SCOOP_KEY, device, writer)
                self.assertTrue(explicit_online(device))
                self.assertFalse(entity.available)
                with self.assertRaises(HomeAssistantError) as raised:
                    asyncio.run(entity.async_press())
                message = str(raised.exception).lower()
                self.assertIn("not eligible", message)
                self.assertIn("nothing was sent", message)
                self.assertNotIn("not online", message)
                self.assertNotIn("water", message)
                self.assertNotIn("allowance", message)
                self.assertEqual(writer.calls, [])
                self.assertEqual(writer.start_calls, [])
                self.assertEqual(writer.stop_calls, [])
                self.assertEqual(entity.coordinator.refreshes, 0)
        writer = _Writer()
        for bad in (None, True, 8, "8.5.80", "abc"):
            with self.subTest(helper=bad):
                before = len(writer.calls)
                with self.assertRaises(OperationNotSent) as raised:
                    asyncio.run(post_no_scoop(writer, "unit-a", bad))
                self.assertIn("not sent", str(raised.exception).lower())
                self.assertEqual(len(writer.calls), before)
        self.assertEqual(writer.start_calls, [])
        self.assertEqual(writer.stop_calls, [])

    def test_no_scoop_offline_does_not_send_even_if_firmware_eligible(self) -> None:
        device = _device("unit-off", state=1, reported="disconnected", fw="8.7.205R")
        writer = _Writer()
        entity = _button(NO_SCOOP_KEY, device, writer)
        self.assertTrue(special_cycle_firmware_eligible(device.fw_version))
        self.assertFalse(entity.available)
        with self.assertRaises(HomeAssistantError) as raised:
            asyncio.run(entity.async_press())
        self.assertIn("no-scoop was not sent", str(raised.exception).lower())
        self.assertEqual(writer.calls, [])
        self.assertEqual(entity.coordinator.refreshes, 0)

    def test_ungated_writer_still_refuses_129(self) -> None:
        self.assertIsNotNone(post_allowed_operation)
        writer = _Writer()
        with self.assertRaises(OperationNotSent) as raised:
            asyncio.run(post_allowed_operation(writer, "unit-a", {"state": 129}, "no-scoop"))
        self.assertIn("not sent", str(raised.exception).lower())
        self.assertEqual(writer.calls, [])
        result = asyncio.run(post_allowed_operation(writer, "unit-a", {"state": 4}, "abort"))
        self.assertEqual(result, {"fixture": FIXTURE})
        self.assertEqual(writer.calls, [("POST", OPERATION_PATH.format(device_id="unit-a"), {"state": 4}, None)])

    def test_direct_literal_129_requires_firmware_before_any_write(self) -> None:
        """Exact SOL-01 repro: post_literal_state must not post 129 without a gate."""
        self.assertIsNotNone(post_literal_state)
        assert post_literal_state is not None
        writer = _Writer()
        with self.assertRaises(OperationNotSent) as raised:
            asyncio.run(post_literal_state(writer, "SYNTHETIC-unit", 129, "no-scoop"))
        self.assertIn("not sent", str(raised.exception).lower())
        self.assertEqual(writer.calls, [])
        self.assertEqual(writer.start_calls, [])
        self.assertEqual(writer.stop_calls, [])
        with self.assertRaises(OperationNotSent) as raised:
            asyncio.run(post_literal_state(writer, "SYNTHETIC-unit", 129, "pause"))
        self.assertIn("not sent", str(raised.exception).lower())
        self.assertEqual(writer.calls, [])
        refused = (
            None,
            "",
            "abc",
            "8.5",
            "08.5.81",
            "8.5.80",
            "8.5.9",
            "R",
            " 8.5.81",
            "8.5.81-rc1",
            True,
            8,
            f"{_OVER_SAFE_COMPONENT}.0.0",
            f"8.{_OVER_SAFE_COMPONENT}.0",
            f"8.5.{_OVER_SAFE_COMPONENT}",
            _FIVE_THOUSAND_DIGITS,
            _WITHIN_LENGTH_OVERSIZE,
        )
        for fw in refused:
            with self.subTest(fw=fw if not isinstance(fw, str) else fw[:32]):
                before = len(writer.calls)
                with self.assertRaises(OperationNotSent) as raised:
                    asyncio.run(
                        post_literal_state(
                            writer, "SYNTHETIC-unit", 129, "no-scoop", fw
                        )
                    )
                self.assertIn("not sent", str(raised.exception).lower())
                self.assertEqual(len(writer.calls), before)
        for state, label in ((2, "pause"), (3, "resume"), (4, "abort")):
            with self.subTest(ungated=state):
                result = asyncio.run(
                    post_literal_state(writer, "SYNTHETIC-unit", state, label)
                )
                self.assertEqual(result, {"fixture": FIXTURE})
        self.assertEqual(
            [call[2] for call in writer.calls],
            [{"state": 2}, {"state": 3}, {"state": 4}],
        )
        posted = asyncio.run(
            post_literal_state(writer, "SYNTHETIC-unit", 129, "no-scoop", "8.5.81")
        )
        self.assertEqual(posted, {"fixture": FIXTURE})
        self.assertEqual(writer.calls[-1][2], {"state": 129})
        self.assertEqual(writer.calls[-1][0], "POST")
        self.assertEqual(writer.start_calls, [])
        self.assertEqual(writer.stop_calls, [])

    def test_oversized_firmware_refuses_helper_availability_and_press(self) -> None:
        """Exact SOL-02 repros: oversized components and a 5000-digit string."""
        self.assertIsNotNone(special_cycle_firmware_eligible)
        self.assertIsNotNone(post_no_scoop)
        assert special_cycle_firmware_eligible is not None
        assert post_no_scoop is not None
        max_valid = f"{_MAX_SAFE_COMPONENT}.0.0"
        self.assertTrue(special_cycle_firmware_eligible(max_valid))
        invalid = (
            f"{_OVER_SAFE_COMPONENT}.0.0",
            f"8.{_OVER_SAFE_COMPONENT}.0",
            f"8.5.{_OVER_SAFE_COMPONENT}",
            _FIVE_THOUSAND_DIGITS,
            "9" * 257,
            _WITHIN_LENGTH_OVERSIZE,
        )
        for fw in invalid:
            with self.subTest(gate=fw[:32]):
                try:
                    eligible = special_cycle_firmware_eligible(fw)
                except Exception as error:
                    self.fail(
                        f"malformed firmware raised {type(error).__name__}: {error}"
                    )
                self.assertFalse(eligible)
        writer = _Writer()
        device = _device("unit-max", state=1, reported="connected", fw=max_valid)
        entity = _button(NO_SCOOP_KEY, device, writer)
        self.assertTrue(explicit_online(device))
        self.assertTrue(entity.available)
        asyncio.run(post_no_scoop(writer, device.manufacturer_id, max_valid))
        asyncio.run(entity.async_press())
        self.assertEqual([call[2] for call in writer.calls], [{"state": 129}, {"state": 129}])
        self.assertEqual(writer.start_calls, [])
        self.assertEqual(writer.stop_calls, [])
        for fw in invalid:
            with self.subTest(surface=fw[:32]):
                surface = _Writer()
                with self.assertRaises(OperationNotSent) as raised:
                    asyncio.run(post_no_scoop(surface, "unit-a", fw))
                self.assertIn("not sent", str(raised.exception).lower())
                self.assertEqual(surface.calls, [])
                device = _device("unit-over", state=1, reported="connected", fw=fw)
                entity = _button(NO_SCOOP_KEY, device, surface)
                self.assertTrue(explicit_online(device))
                self.assertFalse(entity.available)
                with self.assertRaises(HomeAssistantError) as raised:
                    asyncio.run(entity.async_press())
                message = str(raised.exception).lower()
                self.assertIn("not eligible", message)
                self.assertIn("nothing was sent", message)
                self.assertEqual(surface.calls, [])
                self.assertEqual(surface.start_calls, [])
                self.assertEqual(surface.stop_calls, [])
                self.assertEqual(entity.coordinator.refreshes, 0)

    def test_no_scoop_errors_once_without_retry_or_fallback(self) -> None:
        device = _device("unit-a", state=1, fw="8.7.205R")
        for error in (
            CatGenieAPIError("synthetic 500"),
            CatGenieException("synthetic library"),
            ConnectionError("synthetic network"),
        ):
            with self.subTest(error=type(error).__name__):
                writer = _Writer(error=error)
                entity = _button(NO_SCOOP_KEY, device, writer)
                snapshot = dict(entity.coordinator.data)
                with self.assertRaises(HomeAssistantError):
                    asyncio.run(entity.async_press())
                self.assertEqual(len(writer.calls), 1)
                self.assertEqual(writer.calls[0][2], {"state": 129})
                self.assertEqual(writer.start_calls, [])
                self.assertEqual(writer.stop_calls, [])
                self.assertEqual(entity.coordinator.refreshes, 0)
                self.assertEqual(entity.coordinator.data, snapshot)

        class _NoWriter:
            async def start_cleaning(self, device_id: str):
                raise AssertionError("fallback start")

            async def stop_cleaning(self, device_id: str):
                raise AssertionError("fallback stop")

        with self.assertRaises(OperationNotSent) as raised:
            asyncio.run(post_no_scoop(_NoWriter(), "unit-a", "8.7.205R"))
        self.assertIn("not sent", str(raised.exception).lower())
        with self.assertRaises(OperationNotSent):
            asyncio.run(post_abort(_NoWriter(), "unit-a"))

    def test_helpers_reuse_integration_writer_once(self) -> None:
        client = HomeAssistantCatGenieClient(Credentials())
        calls = []

        async def _request(method, path, body=None, params=None):
            calls.append((method, path, dict(body), params))
            return {"fixture": FIXTURE}

        client._request = _request
        asyncio.run(post_abort(client, "unit-a"))
        asyncio.run(post_no_scoop(client, "unit/a", "8.7.205R"))
        self.assertEqual(
            calls,
            [
                ("POST", "device/management/unit-a/operation", {"state": 4}, None),
                ("POST", "device/management/unit/a/operation", {"state": 129}, None),
            ],
        )
        with self.assertRaises(OperationNotSent):
            asyncio.run(post_no_scoop(client, "", "8.7.205R"))
        self.assertEqual(len(calls), 2)

    def test_docs_distinguish_code_from_installed_and_hold_acceptance(self) -> None:
        doc = (CANDIDATE / "docs" / "cycle-controls.md").read_text().lower()
        self.assertIn("behavior capabilities", doc)
        self.assertIn("state 4", doc)
        self.assertIn("state 129", doc)
        self.assertIn("8.5.81", doc)
        self.assertIn("fwversion", doc)
        self.assertIn("not proven", doc)
        self.assertIn("enabled by default", doc)
        self.assertIn("previously disabled", doc)
        self.assertNotIn("disabled by default", doc)
        self.assertNotIn("a8066c8", doc)
        self.assertNotIn("experimental", doc)
        self.assertIn("does not replace", doc)
        self.assertIn("not a finishing", doc)
        self.assertIn("does not recover a water-fill fault", doc)
        self.assertIn("does not restore cartridge allowance", doc)
        self.assertIn("missing", doc)
        self.assertIn("malformed", doc)
        readme = (CANDIDATE / "README.md").read_text()
        self.assertIn("Abort cleaning", readme)
        self.assertIn("No-scoop wash", readme)
        self.assertNotIn("Abort cleaning (experimental)", readme)
        self.assertNotIn("No-scoop wash (experimental)", readme)
        self.assertIn("owner-verified", readme.lower())
        coverage = (CANDIDATE / "docs" / "feature-coverage.md").read_text()
        self.assertNotIn("special cycle are not exposed", coverage)
        self.assertIn("validation scope", coverage.lower())
        machine = json.loads((CANDIDATE / "docs" / "feature-coverage.json").read_text())
        self.assertEqual(
            machine["disposition_counts"],
            dict(__import__('collections').Counter(e['disposition'] for e in machine['entries'])),
        )
        abort_topic = next(item for item in machine["entries"] if item["id"] == "CG-34")
        scoop_topic = next(item for item in machine["entries"] if item["id"] == "CG-36")
        self.assertEqual(abort_topic["disposition"], "HOLD")
        self.assertTrue(abort_topic["implemented"])
        self.assertIn("state 4", abort_topic["source"])
        self.assertIn("unproven", abort_topic["source"].lower())
        self.assertEqual(scoop_topic["disposition"], "HOLD")
        self.assertTrue(scoop_topic["implemented"])
        self.assertIn("129", scoop_topic["source"])
        self.assertIn("8.5.81", scoop_topic["source"])
        self.assertIn("unproven", scoop_topic["source"].lower())
        dnd_topic = next(item for item in machine["entries"] if item["id"] == "CG-09")
        schedule_topic = next(item for item in machine["entries"] if item["id"] == "CG-11")
        self.assertEqual(dnd_topic["disposition"], "local-action")
        self.assertTrue(dnd_topic["implemented"])
        self.assertEqual(schedule_topic["disposition"], "local-action")
        self.assertTrue(schedule_topic["implemented"])
        self.assertNotIn('install_status', machine)
        self.assertEqual(machine['validation_scope']['device_page_editor'], 'deferred')
        self.assertEqual({e['id'] for e in machine['entries']}, {f'CG-{n:02}' for n in range(1, 48)})
        self.assertEqual(machine['topic_count'], len(machine['entries']))
        guide = (CANDIDATE / "tests" / "README.md").read_text().lower()
        self.assertIn("state 4", guide)
        self.assertIn("state 129", guide)
        self.assertIn("8.5.81", guide)


if __name__ == "__main__":
    unittest.main()
