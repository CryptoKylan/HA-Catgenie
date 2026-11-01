"""SYNTHETIC pause and resume regressions. Not a live device command.

Payloads use the pinned CatGenie models. Home Assistant and HTTP are stubbed.
A constructed state-2 or state-3 body is not proof the firmware accepted it.
Outbound state 2 is the app SUSPENDED command. It is not a reported-integer contract.
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
OPERATION_PATH = "device/management/{device_id}/operation"


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
        from custom_components.catgenie.resume import post_resume
    except ImportError:
        post_resume = None
    try:
        from custom_components.catgenie.pause import post_pause
    except ImportError:
        post_pause = None
    try:
        from custom_components.catgenie.operation_post import OperationNotSent, post_allowed_operation
    except ImportError:
        post_allowed_operation = None

_MODULES_AFTER = {
    name: module
    for name, module in sys.modules.items()
    if any(name == prefix or name.startswith(prefix + ".") for prefix in _SEAM_PREFIXES)
}
_PATH_AFTER = tuple(sys.path)


def _payload(manufacturer_id: str, state: int, reported: object = "connected") -> dict:
    payload: dict = {
        "_fixture": FIXTURE,
        "manufacturerId": manufacturer_id,
        "name": f"{FIXTURE}-{manufacturer_id}",
        "macAddress": "aa:bb:cc:dd:ee:ff",
        "hwRevision": "1",
        "fwVersion": "8.7.205R",
        "status": state,
        "operationStatus": {"state": state, "progress": 0},
    }
    if reported is not _OMIT:
        payload["reportedStatus"] = reported
    return payload


class _Omit:
    pass


_OMIT = _Omit()


def _device(manufacturer_id: str, state: int = 0, reported: object = "connected"):
    return TolerantDevice.model_validate(_payload(manufacturer_id, state, reported))


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
        raise AssertionError("resume must not call start_cleaning")

    async def stop_cleaning(self, device_id: str):
        self.stop_calls.append(device_id)
        raise AssertionError("resume must not call stop_cleaning")


def _button(key: str, device, client) -> CatGenieButton:
    description = next(item for item in BUTTONS if item.key == key)
    return CatGenieButton(_Coordinator(device, client), device.manufacturer_id, description)


class ResumeControlTests(unittest.TestCase):
    def test_import_seams_restore(self) -> None:
        self.assertEqual(_MODULES_AFTER, _MODULES_BEFORE)
        self.assertEqual(_PATH_AFTER, _PATH_BEFORE)

    def test_pinned_writer_is_reusable_for_literal_state_3(self) -> None:
        source = (Path(__import__("catgenie").__file__).parent / "client.py").read_text()
        tree = ast.parse(source)
        bodies = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name in {
                "start_cleaning",
                "stop_cleaning",
            }:
                bodies[node.name] = ast.unparse(node)
        self.assertEqual(
            ENDPOINT_DEVICE_OPERATION,
            OPERATION_PATH,
            "pinned operation endpoint drifted; refuse resume rather than invent a writer",
        )
        self.assertIn("body={'state': 1}", bodies["start_cleaning"])
        self.assertIn("self._request('POST', path, body={'state': 1})", bodies["start_cleaning"])
        self.assertIn("body={'state': 0}", bodies["stop_cleaning"])
        self.assertIn("self._request('POST', path, body={'state': 0})", bodies["stop_cleaning"])
        self.assertNotIn("credentials", bodies["start_cleaning"].lower())
        helper = INTEGRATION / "resume.py"
        self.assertTrue(helper.is_file(), "resume helper missing")
        helper_tree = ast.parse(helper.read_text())
        helper_text = ast.unparse(helper_tree)
        self.assertIn("post_resume", helper_text)
        self.assertIn("{'state': 3}", helper_text)
        self.assertIn("post_allowed_operation", helper_text)
        self.assertNotIn("_request", helper_text)
        self.assertNotIn("start_cleaning", helper_text)
        self.assertNotIn("stop_cleaning", helper_text)
        self.assertNotIn("Credentials", helper_text)
        self.assertNotIn("access_token", helper_text)
        self.assertNotIn("refresh_token", helper_text)
        self.assertNotIn("monkeypatch", helper_text.lower())
        self.assertNotIn("if body !=", helper.read_text())
        for forbidden in ("state\": 0", "state\": 1", "state\": 2", "state\": 4", "129"):
            self.assertNotIn(forbidden, helper.read_text())
        pause_helper = INTEGRATION / "pause.py"
        shared = INTEGRATION / "operation_post.py"
        self.assertTrue(pause_helper.is_file(), "pause helper missing")
        self.assertTrue(shared.is_file(), "shared operation writer missing")
        pause_text = ast.unparse(ast.parse(pause_helper.read_text()))
        shared_text = ast.unparse(ast.parse(shared.read_text()))
        self.assertIn("post_pause", pause_text)
        self.assertIn("{'state': 2}", pause_text)
        self.assertIn("post_allowed_operation", pause_text)
        self.assertNotIn("_request", pause_text)
        self.assertNotIn("{'state': 3}", pause_text)
        self.assertNotIn("start_cleaning", pause_text)
        self.assertNotIn("stop_cleaning", pause_text)
        self.assertIn("_request", shared_text)
        self.assertIn("ENDPOINT_DEVICE_OPERATION", shared_text)
        self.assertNotIn("start_cleaning", shared_text)
        self.assertNotIn("stop_cleaning", shared_text)
        self.assertNotIn("Credentials", shared_text)
        self.assertNotIn("access_token", shared_text)
        self.assertNotIn("refresh_token", shared_text)
        self.assertNotIn("if body !=", shared.read_text())
        self.assertNotIn("if body !=", pause_helper.read_text())
        request_sites = [
            path.name
            for path in (
                INTEGRATION / "pause.py",
                INTEGRATION / "resume.py",
                INTEGRATION / "operation_post.py",
                INTEGRATION / "button.py",
            )
            if path.is_file() and "client._request" in path.read_text()
        ]
        self.assertEqual(request_sites, ["operation_post.py"])

    def test_existing_button_ids_stay_and_resume_is_opt_in(self) -> None:
        keys = [item.key for item in BUTTONS]
        self.assertEqual(keys, ["start_cleaning", "stop_cleaning", PAUSE_KEY, RESUME_KEY, "abort_cleaning", "no_scoop_cleaning"])
        by_key = {item.key: item for item in BUTTONS}
        self.assertEqual(by_key["start_cleaning"].translation_key, "start_cleaning")
        self.assertEqual(by_key["stop_cleaning"].translation_key, "stop_cleaning")
        self.assertTrue(by_key["start_cleaning"].entity_registry_enabled_default)
        self.assertTrue(by_key["stop_cleaning"].entity_registry_enabled_default)
        self.assertTrue(by_key["start_cleaning"].requires_explicit_online)
        self.assertTrue(by_key["stop_cleaning"].requires_explicit_online)
        resume = by_key[RESUME_KEY]
        self.assertEqual(resume.translation_key, RESUME_KEY)
        self.assertTrue(resume.entity_registry_enabled_default)
        self.assertTrue(resume.requires_explicit_online)
        self.assertIs(resume.press_fn, post_resume)
        self.assertIsNone(resume.entity_category)
        self.assertEqual(resume.offline_message, "CatGenie is not online; resume was not sent.")
        pause = by_key[PAUSE_KEY]
        self.assertEqual(pause.translation_key, PAUSE_KEY)
        self.assertTrue(pause.entity_registry_enabled_default)
        self.assertTrue(pause.requires_explicit_online)
        self.assertIs(pause.press_fn, post_pause)
        self.assertIsNone(pause.entity_category)
        self.assertEqual(pause.offline_message, "CatGenie is not online; pause was not sent.")
        device = _device("unit-a", state=2)
        start = _button("start_cleaning", device, _Writer())
        stop = _button("stop_cleaning", device, _Writer())
        entity = _button(RESUME_KEY, device, _Writer())
        self.assertEqual(start._attr_unique_id, "unit-a_start_cleaning")
        self.assertEqual(stop._attr_unique_id, "unit-a_stop_cleaning")
        self.assertEqual(entity._attr_unique_id, "unit-a_resume_cleaning")
        self.assertTrue(entity._attr_entity_registry_enabled_default)
        paused = _button(PAUSE_KEY, device, _Writer())
        self.assertEqual(paused._attr_unique_id, "unit-a_pause_cleaning")
        self.assertTrue(paused._attr_entity_registry_enabled_default)
        translation = json.loads((INTEGRATION / "translations" / "en.json").read_text())
        buttons = translation["entity"]["button"]
        self.assertEqual(buttons["start_cleaning"]["name"], "Start cleaning")
        self.assertEqual(buttons["stop_cleaning"]["name"], "Stop cleaning")
        self.assertEqual(buttons[RESUME_KEY]["name"], "Resume cleaning")
        self.assertEqual(buttons[PAUSE_KEY]["name"], "Pause cleaning")
        self.assertEqual(
            set(buttons),
            {"start_cleaning", "stop_cleaning", PAUSE_KEY, RESUME_KEY, "abort_cleaning", "no_scoop_cleaning"},
        )

    def test_setup_does_not_press_or_send(self) -> None:
        device = _device("unit-a", state=2)
        client = _Writer()
        coordinator = _Coordinator(device, client)
        added: list = []

        class _Entry:
            runtime_data = coordinator

        asyncio.run(async_setup_entry(object(), _Entry(), added.extend))
        self.assertEqual([entity._attr_unique_id for entity in added], [
            "unit-a_start_cleaning",
            "unit-a_stop_cleaning",
            "unit-a_pause_cleaning",
            "unit-a_resume_cleaning",
            "unit-a_abort_cleaning",
            "unit-a_no_scoop_cleaning",
        ])
        self.assertEqual(client.calls, [])
        self.assertEqual(client.start_calls, [])
        self.assertEqual(client.stop_calls, [])
        self.assertEqual(coordinator.refreshes, 0)
        self.assertEqual(coordinator.data[device.manufacturer_id], device)

    def test_online_press_sends_only_state_3_then_refreshes(self) -> None:
        self.assertIsNotNone(post_resume)
        for state in (0, 1, 2, 3, 4, 129):
            with self.subTest(state=state):
                device = _device(f"unit-{state}", state=state, reported="Connected")
                self.assertTrue(explicit_online(device))
                writer = _Writer()
                before = dict(writer.calls)
                entity = _button(RESUME_KEY, device, writer)
                snapshot = dict(entity.coordinator.data)
                self.assertTrue(entity.available)
                asyncio.run(entity.async_press())
                self.assertEqual(len(writer.calls), 1)
                method, path, body, params = writer.calls[0]
                self.assertEqual(method, "POST")
                self.assertEqual(
                    path,
                    ENDPOINT_DEVICE_OPERATION.format(device_id=device.manufacturer_id),
                )
                self.assertEqual(body, {"state": 3})
                self.assertIs(type(body["state"]), int)
                self.assertIsNone(params)
                self.assertEqual(writer.start_calls, [])
                self.assertEqual(writer.stop_calls, [])
                self.assertEqual(entity.coordinator.refreshes, 1)
                self.assertEqual(entity.coordinator.data, snapshot)

                self.assertIs(entity.coordinator.data[device.manufacturer_id], device)

    def test_reported_integers_do_not_gate_resume(self) -> None:
        online = _device("online-idle", state=0)
        suspended_looking = _device("online-2", state=2)
        resumed_looking = _device("online-3", state=3)
        for device in (online, suspended_looking, resumed_looking):
            entity = _button(RESUME_KEY, device, _Writer())
            self.assertTrue(entity.available, device.manufacturer_id)
        offline_suspended = _device("offline-2", state=2, reported="disconnected")
        entity = _button(RESUME_KEY, offline_suspended, _Writer())
        self.assertFalse(entity.available)
        self.assertFalse(explicit_online(offline_suspended))

    def test_integer_reported_status_wire_is_rejected_before_controls(self) -> None:
        from pydantic import ValidationError
        for state in (1, 2):
            with self.subTest(state=state):
                # Wire validation fails before an entity or writer is constructed.
                with self.assertRaises(ValidationError) as caught:
                    _device("invalid-wire", state=state, reported=1)
                self.assertIn("reportedStatus", str(caught.exception))

    def test_offline_or_missing_status_does_not_send(self) -> None:
        cases = {
            "disconnected": "disconnected",
            "empty": "",
            "omitted": _OMIT,
        }
        for name, reported in cases.items():
            with self.subTest(name=name):
                device = _device("unit-off", state=2, reported=reported)
                writer = _Writer()
                entity = _button(RESUME_KEY, device, writer)
                self.assertFalse(entity.available)
                with self.assertRaises(HomeAssistantError) as raised:
                    asyncio.run(entity.async_press())
                self.assertIn("not online", str(raised.exception).lower())
                self.assertNotIn("water", str(raised.exception).lower())
                self.assertNotIn("allowance", str(raised.exception).lower())
                self.assertEqual(writer.calls, [])
                self.assertEqual(writer.start_calls, [])
                self.assertEqual(writer.stop_calls, [])
                self.assertEqual(entity.coordinator.refreshes, 0)

    def test_missing_device_does_not_send(self) -> None:
        device = _device("unit-a", state=1)
        writer = _Writer()
        entity = _button(RESUME_KEY, device, writer)
        del entity.coordinator.data[device.manufacturer_id]
        self.assertFalse(entity.available)
        with self.assertRaises(HomeAssistantError):
            asyncio.run(entity.async_press())
        self.assertEqual(writer.calls, [])
        self.assertEqual(entity.coordinator.refreshes, 0)

    def test_errors_surface_once_without_retry_or_state_mutation(self) -> None:
        device = _device("unit-a", state=1)
        for error in (
            CatGenieAPIError("synthetic 500"),
            CatGenieException("synthetic library"),
            ConnectionError("synthetic network"),
        ):
            with self.subTest(error=type(error).__name__):
                writer = _Writer(error=error)
                entity = _button(RESUME_KEY, device, writer)
                snapshot = dict(entity.coordinator.data)
                with self.assertRaises(HomeAssistantError):
                    asyncio.run(entity.async_press())
                self.assertEqual(len(writer.calls), 1)
                self.assertEqual(writer.calls[0][2], {"state": 3})
                self.assertEqual(writer.start_calls, [])
                self.assertEqual(writer.stop_calls, [])
                self.assertEqual(entity.coordinator.refreshes, 0)
                self.assertEqual(entity.coordinator.data, snapshot)

    def test_helper_refuses_incompatible_writer_without_fallback(self) -> None:
        self.assertIsNotNone(post_resume)

        class _NoWriter:
            async def start_cleaning(self, device_id: str):
                raise AssertionError("fallback start")

            async def stop_cleaning(self, device_id: str):
                raise AssertionError("fallback stop")

        with self.assertRaises(OperationNotSent) as raised:
            asyncio.run(post_resume(_NoWriter(), "unit-a"))
        self.assertIn("not sent", str(raised.exception).lower())

        writer = _Writer()
        result = asyncio.run(post_resume(writer, "unit/a"))
        self.assertEqual(result, {"fixture": FIXTURE})
        self.assertEqual(
            writer.calls,
            [("POST", OPERATION_PATH.format(device_id="unit/a"), {"state": 3}, None)],
        )
        with self.assertRaises(OperationNotSent):
            asyncio.run(post_resume(writer, ""))
        self.assertEqual(len(writer.calls), 1)

    def test_integration_client_reuses_instance_writer(self) -> None:
        self.assertIsNotNone(post_resume)
        client = HomeAssistantCatGenieClient(Credentials())
        calls = []

        async def _request(method, path, body=None, params=None):
            calls.append((method, path, dict(body), params))
            return {"fixture": FIXTURE}

        client._request = _request
        asyncio.run(post_resume(client, "unit-a"))
        self.assertEqual(
            calls,
            [("POST", "device/management/unit-a/operation", {"state": 3}, None)],
        )

    def test_online_start_and_stop_commands_are_unchanged(self) -> None:
        device = _device("unit-a", state=0, reported="connected")
        writer = _Writer()

        async def start_cleaning(device_id: str):
            writer.start_calls.append(device_id)
            return {"started": FIXTURE}

        async def stop_cleaning(device_id: str):
            writer.stop_calls.append(device_id)
            return {"stopped": FIXTURE}

        writer.start_cleaning = start_cleaning
        writer.stop_cleaning = stop_cleaning
        start = _button("start_cleaning", device, writer)
        stop = _button("stop_cleaning", device, writer)
        self.assertTrue(start.available)
        self.assertTrue(stop.available)
        asyncio.run(start.async_press())
        asyncio.run(stop.async_press())
        self.assertEqual(writer.start_calls, ["unit-a"])
        self.assertEqual(writer.stop_calls, ["unit-a"])
        self.assertEqual(writer.calls, [])
        self.assertEqual(start.coordinator.refreshes, 1)
        self.assertEqual(stop.coordinator.refreshes, 1)

    def test_docs_do_not_promise_recovery_or_other_commands(self) -> None:
        doc = (CANDIDATE / "docs" / "pause-resume-control.md").read_text()
        lowered = doc.lower()
        self.assertIn("firmware acceptance", lowered)
        self.assertIn("not proven", lowered)
        self.assertIn("state 2", lowered)
        self.assertIn("state 3", lowered)
        self.assertIn("suspended", lowered)
        self.assertIn("enabled by default", lowered)
        self.assertIn("new registration", lowered)
        self.assertIn("previously disabled", lowered)
        self.assertIn("does not read or write the registry", lowered)
        self.assertNotIn("disabled by default", lowered)
        self.assertNotIn("experimental", lowered)
        self.assertIn("does not recover a water-fill fault", lowered)
        self.assertIn("does not restore cartridge allowance", lowered)
        self.assertIn("not abort", lowered)
        self.assertIn("not a special cycle", lowered)
        self.assertIn("reported integer", lowered)
        self.assertNotIn("abort_cleaning", doc)
        self.assertNotIn("play_special", lowered)
        self.assertNotIn("if body !=", doc)
        readme = (CANDIDATE / "README.md").read_text()
        self.assertIn("Pause cleaning", readme)
        self.assertIn("Resume cleaning", readme)
        self.assertNotIn("Pause cleaning (experimental)", readme)
        self.assertNotIn("Resume cleaning (experimental)", readme)
        self.assertIn("four cycle controls are enabled by default", readme.lower())
        self.assertIn("state 2", readme.lower())
        self.assertIn("state 3", readme.lower())
        self.assertIn("docs/pause-resume-control.md", readme)
        coverage = (CANDIDATE / "docs" / "feature-coverage.md").read_text()
        self.assertNotIn("pause are not exposed", coverage)
        self.assertIn("validation scope", coverage.lower())
        self.assertNotIn("special cycle are not exposed", coverage)
        self.assertIn("| CG-34 | HOLD | Pause / resume / stage commands |", coverage)
        machine = json.loads((CANDIDATE / "docs" / "feature-coverage.json").read_text())
        self.assertEqual(
            machine["disposition_counts"],
            dict(__import__('collections').Counter(e['disposition'] for e in machine['entries'])),
        )
        topic = next(item for item in machine["entries"] if item["id"] == "CG-34")
        self.assertEqual(topic["disposition"], "HOLD")
        self.assertTrue(topic["implemented"])
        self.assertIn("state 2", topic["source"])
        self.assertIn("state 3", topic["source"])
        self.assertIn("HOLD", topic["source"])
        button_source = (INTEGRATION / "button.py").read_text()
        self.assertIn("pause_cleaning", button_source)
        self.assertIn("resume_cleaning", button_source)
        self.assertIn("abort_cleaning", button_source)
        self.assertNotIn("play_special", button_source.lower())
        self.assertNotIn("state\": 129", button_source)
        self.assertNotIn("state\": 4", button_source)
        called = []
        for path in INTEGRATION.glob("*.py"):
            if path.name == "resume.py":
                continue
            text = path.read_text()
            if "post_resume" in text:
                called.append(path.name)
        self.assertEqual(called, ["button.py"])
        pause_callers = []
        for path in INTEGRATION.glob("*.py"):
            if path.name == "pause.py":
                continue
            if "post_pause" in path.read_text():
                pause_callers.append(path.name)
        self.assertEqual(pause_callers, ["button.py"])
        guide = (CANDIDATE / "tests" / "README.md").read_text()
        self.assertIn("state 2", guide)
        self.assertIn("state 3", guide)
        self.assertIn("enabled by default", guide.lower())
        self.assertNotIn("experimental", guide.lower())

    def test_online_press_sends_only_state_2_then_refreshes(self) -> None:
        self.assertIsNotNone(post_pause)
        for state in (0, 1, 2, 3, 4, 129):
            with self.subTest(state=state):
                device = _device(f"unit-{state}", state=state, reported="Connected")
                self.assertTrue(explicit_online(device))
                writer = _Writer()
                entity = _button(PAUSE_KEY, device, writer)
                snapshot = dict(entity.coordinator.data)
                self.assertTrue(entity.available)
                asyncio.run(entity.async_press())
                self.assertEqual(len(writer.calls), 1)
                method, path, body, params = writer.calls[0]
                self.assertEqual(method, "POST")
                self.assertEqual(
                    path,
                    ENDPOINT_DEVICE_OPERATION.format(device_id=device.manufacturer_id),
                )
                self.assertEqual(body, {"state": 2})
                self.assertIs(type(body["state"]), int)
                self.assertIsNone(params)
                self.assertEqual(writer.start_calls, [])
                self.assertEqual(writer.stop_calls, [])
                self.assertEqual(entity.coordinator.refreshes, 1)
                self.assertEqual(entity.coordinator.data, snapshot)
                self.assertIs(entity.coordinator.data[device.manufacturer_id], device)

    def test_reported_integers_do_not_gate_pause(self) -> None:
        for state in (0, 1, 2, 3, 4, 129):
            device = _device(f"online-{state}", state=state)
            entity = _button(PAUSE_KEY, device, _Writer())
            self.assertTrue(entity.available, device.manufacturer_id)
        offline = _device("offline-2", state=2, reported="disconnected")
        entity = _button(PAUSE_KEY, offline, _Writer())
        self.assertFalse(entity.available)
        self.assertFalse(explicit_online(offline))

    def test_pause_offline_or_missing_status_does_not_send(self) -> None:
        cases = {
            "disconnected": "disconnected",
            "empty": "",
            "omitted": _OMIT,
        }
        for name, reported in cases.items():
            with self.subTest(name=name):
                device = _device("unit-off", state=1, reported=reported)
                writer = _Writer()
                entity = _button(PAUSE_KEY, device, writer)
                self.assertFalse(entity.available)
                with self.assertRaises(HomeAssistantError) as raised:
                    asyncio.run(entity.async_press())
                self.assertIn("not online", str(raised.exception).lower())
                self.assertIn("pause was not sent", str(raised.exception).lower())
                self.assertNotIn("resume", str(raised.exception).lower())
                self.assertNotIn("water", str(raised.exception).lower())
                self.assertNotIn("allowance", str(raised.exception).lower())
                self.assertEqual(writer.calls, [])
                self.assertEqual(writer.start_calls, [])
                self.assertEqual(writer.stop_calls, [])
                self.assertEqual(entity.coordinator.refreshes, 0)

    def test_pause_missing_device_does_not_send(self) -> None:
        device = _device("unit-a", state=1)
        writer = _Writer()
        entity = _button(PAUSE_KEY, device, writer)
        del entity.coordinator.data[device.manufacturer_id]
        self.assertFalse(entity.available)
        with self.assertRaises(HomeAssistantError):
            asyncio.run(entity.async_press())
        self.assertEqual(writer.calls, [])
        self.assertEqual(entity.coordinator.refreshes, 0)

    def test_pause_errors_surface_once_without_retry_or_state_mutation(self) -> None:
        device = _device("unit-a", state=1)
        for error in (
            CatGenieAPIError("synthetic 500"),
            CatGenieException("synthetic library"),
            ConnectionError("synthetic network"),
        ):
            with self.subTest(error=type(error).__name__):
                writer = _Writer(error=error)
                entity = _button(PAUSE_KEY, device, writer)
                snapshot = dict(entity.coordinator.data)
                with self.assertRaises(HomeAssistantError):
                    asyncio.run(entity.async_press())
                self.assertEqual(len(writer.calls), 1)
                self.assertEqual(writer.calls[0][2], {"state": 2})
                self.assertEqual(writer.start_calls, [])
                self.assertEqual(writer.stop_calls, [])
                self.assertEqual(entity.coordinator.refreshes, 0)
                self.assertEqual(entity.coordinator.data, snapshot)

    def test_pause_and_resume_posts_stay_distinct(self) -> None:
        self.assertIsNotNone(post_pause)
        self.assertIsNotNone(post_resume)
        device = _device("unit-a", state=1, reported="connected")
        writer = _Writer()
        coordinator = _Coordinator(device, writer)
        pause_description = next(item for item in BUTTONS if item.key == PAUSE_KEY)
        resume_description = next(item for item in BUTTONS if item.key == RESUME_KEY)
        pause = CatGenieButton(coordinator, device.manufacturer_id, pause_description)
        resume = CatGenieButton(coordinator, device.manufacturer_id, resume_description)
        asyncio.run(pause.async_press())
        asyncio.run(resume.async_press())
        self.assertEqual(
            [call[2] for call in writer.calls],
            [{"state": 2}, {"state": 3}],
        )
        self.assertEqual(writer.start_calls, [])
        self.assertEqual(writer.stop_calls, [])
        self.assertEqual(coordinator.refreshes, 2)
        self.assertEqual(coordinator.data[device.manufacturer_id], device)

    def test_shared_writer_refuses_other_states_without_fallback(self) -> None:
        self.assertIsNotNone(post_allowed_operation)
        self.assertIsNotNone(post_pause)
        writer = _Writer()
        refused = (
            {"state": 0},
            {"state": 1},
            {"state": 129},
            {"state": True},
            {"state": 2.0},
            {"state": 2, "progress": 0},
            {"State": 2},
            None,
        )
        for body in refused:
            with self.subTest(body=body):
                before = len(writer.calls)
                with self.assertRaises(OperationNotSent) as raised:
                    asyncio.run(post_allowed_operation(writer, "unit-a", body, "pause"))
                self.assertIn("not sent", str(raised.exception).lower())
                self.assertEqual(len(writer.calls), before)
        self.assertEqual(writer.start_calls, [])
        self.assertEqual(writer.stop_calls, [])
        with self.assertRaises(OperationNotSent):
            asyncio.run(post_pause(writer, ""))
        self.assertEqual(writer.calls, [])
        result = asyncio.run(post_pause(writer, "unit/a"))
        self.assertEqual(result, {"fixture": FIXTURE})
        self.assertEqual(
            writer.calls,
            [("POST", OPERATION_PATH.format(device_id="unit/a"), {"state": 2}, None)],
        )

    def test_pause_refuses_incompatible_writer_without_fallback(self) -> None:
        self.assertIsNotNone(post_pause)

        class _NoWriter:
            async def start_cleaning(self, device_id: str):
                raise AssertionError("fallback start")

            async def stop_cleaning(self, device_id: str):
                raise AssertionError("fallback stop")

            async def resume(self, device_id: str):
                raise AssertionError("fallback resume")

        with self.assertRaises(OperationNotSent) as raised:
            asyncio.run(post_pause(_NoWriter(), "unit-a"))
        self.assertIn("not sent", str(raised.exception).lower())
        self.assertIn("pause", str(raised.exception).lower())

    def test_pause_reuses_integration_client_writer(self) -> None:
        self.assertIsNotNone(post_pause)
        client = HomeAssistantCatGenieClient(Credentials())
        calls = []

        async def _request(method, path, body=None, params=None):
            calls.append((method, path, dict(body), params))
            return {"fixture": FIXTURE}

        client._request = _request
        asyncio.run(post_pause(client, "unit-a"))
        self.assertEqual(
            calls,
            [("POST", "device/management/unit-a/operation", {"state": 2}, None)],
        )


if __name__ == "__main__":
    unittest.main()
