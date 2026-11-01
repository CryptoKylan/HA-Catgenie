"""Offline regressions using real HA and pinned catgenie, never credentials.

Run in a fresh process, not under the legacy stub harness. Network is denied.
"""
from __future__ import annotations

import asyncio
from contextlib import ExitStack
import io
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import time
from types import MappingProxyType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(os.environ.get("CATGENIE_RUNTIME_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
if dependency := os.environ.get("CATGENIE_TEST_DEPENDENCY"):
    sys.path.insert(0, dependency)

from catgenie import CatGenieAPIError, CatGenieAuthenticationError, CatGenieAuth, Credentials
from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import RequestException
from homeassistant import loader
from homeassistant.config_entries import ConfigEntries, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import frame
from homeassistant.helpers.update_coordinator import UpdateFailed
from pydantic import ValidationError
from pydantic_core import InitErrorDetails, PydanticCustomError

from custom_components.catgenie import config_flow as cf
from custom_components.catgenie.client import HomeAssistantCatGenieClient
from custom_components.catgenie.coordinator import CatGenieCoordinator
from custom_components.catgenie.entity import CatGenieEntity, async_run_command
from custom_components.catgenie.history_coordinator import history_failure
from custom_components.catgenie.operation_state import TolerantDevice

MARK = "SYNTHETIC-PRIVATE-VENDOR-SERIAL"


def entry_for(account="synthetic-account"):
    return ConfigEntry(data={"refresh_token": "synthetic-old", "account_id": account},
        discovery_keys=MappingProxyType({}), domain="catgenie", minor_version=1,
        options={}, source="user", subentries_data=None, title="Synthetic",
        unique_id=account, version=1)


class RuntimeCases(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.network = patch.object(AsyncSession, "request", side_effect=AssertionError("network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.tmp = tempfile.TemporaryDirectory(prefix="catgenie-runtime-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.tmp.cleanup)
        self.hass = HomeAssistant(self.tmp.name)
        loader.async_setup(self.hass)
        frame.async_setup(self.hass)
        self.hass.config.skip_pip = True
        self.hass.config_entries = ConfigEntries(self.hass, {})
        await self.hass.config_entries.async_initialize()

    async def asyncTearDown(self):
        await self.hass.async_stop()

    def flow(self, entry=None):
        flow = cf.CatGenieConfigFlow()
        flow.hass = self.hass
        flow.handler = "catgenie"
        flow.flow_id = "synthetic-flow"
        flow.context = {"source": "user"}
        if entry:
            self.hass.config_entries._entries[entry.entry_id] = entry
            flow.context = {"source": "reauth", "entry_id": entry.entry_id, "unique_id": entry.unique_id}
        return flow

    async def test_validation_api_generic_and_history_error_privacy(self):
        custom = ValidationError.from_exception_data("Synthetic", [InitErrorDetails(
            type=PydanticCustomError(MARK, "Bad {vendor}", {"vendor": MARK}),
            loc=(MARK,), input={MARK: MARK})])
        for err in (custom, CatGenieAPIError(MARK), RequestException(MARK), RuntimeError(MARK)):
            with self.subTest(error=type(err).__name__):
                coord = CatGenieCoordinator(self.hass, entry_for(), SimpleNamespace(get_devices=AsyncMock(side_effect=err)))
                with self.assertRaises(UpdateFailed) as caught:
                    await coord._async_update_data()
                self.assertNotIn(MARK, str(caught.exception))
                self.assertTrue(caught.exception.__suppress_context__)
                with self.assertLogs("custom_components.catgenie.coordinator", level="ERROR") as captured:
                    await coord.async_refresh()
                self.assertNotIn(MARK, "\n".join(captured.output))
        self.assertNotIn(MARK, str(history_failure(CatGenieAuthenticationError(MARK))))
        from custom_components.catgenie.history_coordinator import CatGenieHistoryCoordinator
        history = CatGenieHistoryCoordinator(self.hass, entry_for(), None)
        with patch("custom_components.catgenie.history_coordinator.load_window", AsyncMock(side_effect=CatGenieAuthenticationError(MARK))):
            from contextlib import ExitStack
            hooks = [name for name in ("async_start_reauth_if_available", "async_start_reauth")
                     if hasattr(ConfigEntry, name)]
            self.assertTrue(hooks, "No known actual HA reauthentication hook")
            with ExitStack() as stack:
                reauth_spies = [stack.enter_context(patch.object(ConfigEntry, name)) for name in hooks]
                captured = stack.enter_context(self.assertLogs("custom_components.catgenie.history_coordinator", level="ERROR"))
                await history.async_refresh()
            for reauth in reauth_spies:
                reauth.assert_not_called()
        self.assertNotIn(MARK, "\n".join(captured.output))
        self.assertIsInstance(history.last_exception, UpdateFailed)
        self.assertNotIsInstance(history.last_exception, ConfigEntryAuthFailed)

    def lifecycle_patches(self, session, entry, callbacks=None):
        """Keep actual HA entry/task behavior; replace only offline I/O seams."""
        import custom_components.catgenie as integration
        from custom_components.catgenie import history_coordinator, read_information_coordinator, services
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(integration, "AsyncSession", return_value=session))
        stack.enter_context(patch.object(CatGenieCoordinator, "async_config_entry_first_refresh", AsyncMock()))
        stack.enter_context(patch.object(self.hass.config_entries, "async_forward_entry_setups", AsyncMock()))
        stack.enter_context(patch.object(self.hass.config_entries, "async_unload_platforms", AsyncMock(return_value=True)))
        stack.enter_context(patch.object(services, "async_setup_actions"))
        stack.enter_context(patch.object(history_coordinator.CatGenieHistoryCoordinator, "async_refresh", AsyncMock()))
        stack.enter_context(patch.object(read_information_coordinator.CatGenieReadCoordinator, "async_refresh", AsyncMock()))
        if callbacks is not None:
            stack.enter_context(patch.object(entry, "async_on_unload", side_effect=callbacks.append))
        return stack

    async def test_setup_failure_boundaries_close_once_and_preserve_error(self):
        import custom_components.catgenie as integration
        from custom_components.catgenie import history_coordinator, read_information_coordinator, services
        from homeassistant.helpers import event
        boundaries = (
            (integration, "HomeAssistantCatGenieAuth", False),
            (integration, "HomeAssistantCatGenieClient", False),
            (integration, "CatGenieCoordinator", False),
            (CatGenieCoordinator, "async_config_entry_first_refresh", True),
            (history_coordinator, "CatGenieHistoryCoordinator", False),
            (history_coordinator, "bind_history", False),
            (read_information_coordinator, "CatGenieReadCoordinator", False),
            (read_information_coordinator, "bind_read_information", False),
            (self.hass.config_entries, "async_forward_entry_setups", True),
            (services, "async_setup_actions", False),
            (event, "async_track_time_interval", False),
        )
        for owner, name, is_async in boundaries:
            with self.subTest(boundary=name):
                original = RuntimeError("synthetic setup failure")
                session = SimpleNamespace(close=AsyncMock())
                entry, callbacks = entry_for(), []
                with self.lifecycle_patches(session, entry, callbacks), \
                     patch.object(owner, name, **({"new": AsyncMock(side_effect=original)} if is_async else {"side_effect": original})):
                    with self.assertRaises(RuntimeError) as caught:
                        await integration.async_setup_entry(self.hass, entry)
                    self.assertIs(caught.exception, original)
                    session.close.assert_awaited_once()
                    close = next(cb for cb in callbacks if cb.__name__ == "_close_session")
                    await close()
                    await close()
                    session.close.assert_awaited_once()

    async def test_unload_registration_and_missing_credentials_fail_closed(self):
        import custom_components.catgenie as integration
        for stage in ("callback", "credentials"):
            with self.subTest(stage=stage):
                entry = entry_for()
                session = SimpleNamespace(close=AsyncMock())
                with self.lifecycle_patches(session, entry) as stack:
                    if stage == "callback":
                        original = RuntimeError("synthetic registration failure")
                        stack.enter_context(patch.object(entry, "async_on_unload", side_effect=original))
                        expected = RuntimeError
                    else:
                        entry = entry_for()
                        object.__setattr__(entry, "data", {})
                        expected = KeyError
                    with self.assertRaises(expected):
                        await integration.async_setup_entry(self.hass, entry)
                    session.close.assert_awaited_once()

    async def test_failed_close_callback_reentry_is_safe_and_logged_once(self):
        import custom_components.catgenie as integration
        from custom_components.catgenie import services
        original = RuntimeError("synthetic original")
        for failure in (True, False):
            with self.subTest(setup_failure=failure):
                entry, callbacks = entry_for(), []
                session = SimpleNamespace(close=AsyncMock(side_effect=OSError(MARK)))
                with self.lifecycle_patches(session, entry, callbacks) as stack:
                    if failure:
                        stack.enter_context(patch.object(services, "async_setup_actions", side_effect=original))
                    with self.assertLogs("custom_components.catgenie", level="WARNING") as logs:
                        if failure:
                            with self.assertRaises(RuntimeError) as caught:
                                await integration.async_setup_entry(self.hass, entry)
                            self.assertIs(caught.exception, original)
                        else:
                            await integration.async_setup_entry(self.hass, entry)
                        close = next(cb for cb in callbacks if cb.__name__ == "_close_session")
                        await asyncio.gather(close(), close())
                        await close()
                    session.close.assert_awaited_once()
                    self.assertEqual(len(logs.records), 1)
                    self.assertIn("OSError", logs.output[0])
                    self.assertNotIn(MARK, logs.output[0])
                    self.assertIsNone(logs.records[0].exc_info)

    async def test_setup_cancellation_propagates_and_close_survives_second_cancel(self):
        import custom_components.catgenie as integration
        entered, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def refresh():
            entered.set()
            await asyncio.Event().wait()

        async def close_session():
            closing.set()
            await release.wait()

        entry, callbacks = entry_for(), []
        session = SimpleNamespace(close=AsyncMock(side_effect=close_session))
        with self.lifecycle_patches(session, entry, callbacks), \
             patch.object(CatGenieCoordinator, "async_config_entry_first_refresh", AsyncMock(side_effect=refresh)):
            setup = asyncio.create_task(integration.async_setup_entry(self.hass, entry))
            await asyncio.wait_for(entered.wait(), 2)
            setup.cancel()
            try:
                await asyncio.wait_for(closing.wait(), 2)
                setup.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await setup
            finally:
                release.set()
            await next(cb for cb in callbacks if cb.__name__ == "_close_session")()
            session.close.assert_awaited_once()

    async def test_late_setup_failure_cancels_updates_and_preserves_original(self):
        import custom_components.catgenie as integration
        from custom_components.catgenie import services
        from homeassistant.const import EVENT_HOMEASSISTANT_STOP
        from homeassistant.helpers import event
        from unittest.mock import Mock
        entry, callbacks = entry_for(), []
        session = SimpleNamespace(close=AsyncMock(side_effect=OSError(MARK)))
        original = RuntimeError("synthetic late setup failure")
        cancel_timer = Mock()
        before = self.hass.bus.async_listeners().get(EVENT_HOMEASSISTANT_STOP, 0)
        tasks = []
        create_background = entry.async_create_background_task

        def record_background(*args, **kwargs):
            task = create_background(*args, **kwargs)
            tasks.append(task)
            return task

        with self.lifecycle_patches(session, entry, callbacks), \
             patch.object(event, "async_track_time_interval", side_effect=[cancel_timer, original]), \
             patch.object(entry, "async_create_background_task", side_effect=record_background), \
             patch.object(services, "async_unload_actions") as unload_actions, \
             patch.object(self.hass.config_entries, "async_unload_platforms", AsyncMock(side_effect=ValueError(MARK))):
            with self.assertLogs("custom_components.catgenie", level="WARNING") as logs:
                with self.assertRaises(RuntimeError) as caught:
                    await integration.async_setup_entry(self.hass, entry)
                await next(cb for cb in callbacks if cb.__name__ == "_close_session")()
            self.assertIs(caught.exception, original)
            cancel_timer.assert_called_once()
            unload_actions.assert_called_once_with(self.hass, entry)
            self.assertEqual(len(tasks), 1)
            self.assertTrue(all(task.done() for task in tasks))
            session.close.assert_awaited_once()
            self.assertEqual(len(logs.records), 2)
            self.assertNotIn(MARK, "\n".join(logs.output))
            self.assertTrue(all(record.exc_info is None for record in logs.records))
            self.assertEqual(self.hass.bus.async_listeners().get(EVENT_HOMEASSISTANT_STOP, 0), before)

    async def test_shutdown_closes_once_then_unload_callback_reentry(self):
        import custom_components.catgenie as integration
        for close_error in (None, OSError(MARK)):
            with self.subTest(close_error=type(close_error).__name__):
                # A fresh local core is required for each shutdown.
                if self.hass.is_stopping:
                    self.hass = HomeAssistant(self.tmp.name)
                    loader.async_setup(self.hass)
                    frame.async_setup(self.hass)
                    self.hass.config_entries = ConfigEntries(self.hass, {})
                    await self.hass.config_entries.async_initialize()
                entry, callbacks = entry_for(), []
                session = SimpleNamespace(close=AsyncMock(side_effect=close_error))
                with self.lifecycle_patches(session, entry, callbacks):
                    await self.hass.async_start()
                    await integration.async_setup_entry(self.hass, entry)
                    session.close.assert_not_awaited()
                    with self.assertNoLogs("homeassistant.core", level="ERROR"):
                        await self.hass.async_stop()
                    session.close.assert_awaited_once()
                    await next(cb for cb in callbacks if cb.__name__ == "_close_session")()
                    session.close.assert_awaited_once()

    async def test_first_refresh_auth_and_retry_errors_are_preserved(self):
        import custom_components.catgenie as integration
        from homeassistant.exceptions import ConfigEntryNotReady
        for original in (ConfigEntryAuthFailed("synthetic"), ConfigEntryNotReady("synthetic")):
            with self.subTest(error=type(original).__name__):
                session = SimpleNamespace(close=AsyncMock())
                entry, callbacks = entry_for(), []
                with self.lifecycle_patches(session, entry, callbacks), \
                     patch.object(CatGenieCoordinator, "async_config_entry_first_refresh", AsyncMock(side_effect=original)):
                    with self.assertRaises(type(original)) as caught:
                        await integration.async_setup_entry(self.hass, entry)
                    self.assertIs(caught.exception, original)
                    session.close.assert_awaited_once()
                    self.hass.config_entries.async_forward_entry_setups.assert_not_awaited()

    async def test_framework_failed_forward_cleanup_and_normal_unload(self):
        import custom_components.catgenie as integration
        # Exercise actual ConfigEntry setup/error/unload dispatch in both HA versions.
        root = Path(self.tmp.name) / "custom_components"
        root.mkdir(exist_ok=True)
        (root / "catgenie").symlink_to(ROOT / "custom_components/catgenie")
        for failure, close_failure in ((True, False), (True, True), (False, False), (False, True)):
            with self.subTest(forward_failure=failure, close_failure=close_failure):
                entry = entry_for(f"synthetic-{failure}-{close_failure}")
                session = SimpleNamespace(close=AsyncMock(side_effect=OSError(MARK) if close_failure else None))
                with self.lifecycle_patches(session, entry) as stack:
                    if failure:
                        stack.enter_context(patch.object(self.hass.config_entries, "async_forward_entry_setups", AsyncMock(side_effect=RuntimeError("synthetic forward failure"))))
                    await self.hass.config_entries.async_add(entry)
                    await self.hass.async_block_till_done(wait_background_tasks=True)
                    self.assertEqual(entry.state.value, "setup_error" if failure else "loaded")
                    if not failure:
                        session.close.assert_not_awaited()
                        self.assertTrue(await self.hass.config_entries.async_unload(entry.entry_id))
                    session.close.assert_awaited_once()
                    await entry._async_process_on_unload(self.hass)
                    session.close.assert_awaited_once()

    async def test_session_close_is_shared_and_survives_waiter_cancellation(self):
        import custom_components.catgenie as integration
        callbacks = []
        started, release = asyncio.Event(), asyncio.Event()

        async def delayed_close():
            started.set()
            await release.wait()

        session = SimpleNamespace(close=AsyncMock(side_effect=delayed_close))
        entry = entry_for()
        with self.lifecycle_patches(session, entry, callbacks):
            self.assertTrue(await integration.async_setup_entry(self.hass, entry))
        close = next(callback for callback in callbacks if callback.__name__ == "_close_session")
        first = asyncio.create_task(close())
        await started.wait()
        second = asyncio.create_task(close())
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.assertFalse(second.done())
        release.set()
        await second
        await close()
        session.close.assert_awaited_once()

    async def test_cleanup_error_does_not_replace_original_setup_error(self):
        import custom_components.catgenie as integration
        from custom_components.catgenie import services
        original = RuntimeError("synthetic action setup error")
        session = SimpleNamespace(close=AsyncMock(side_effect=OSError(MARK)))
        with patch.object(integration, "AsyncSession", return_value=session), \
             patch.object(CatGenieCoordinator, "async_config_entry_first_refresh", AsyncMock()), \
             patch.object(self.hass.config_entries, "async_forward_entry_setups", AsyncMock()), \
             patch.object(self.hass.config_entries, "async_unload_platforms", AsyncMock(return_value=True)), \
             patch.object(services, "async_setup_actions", side_effect=original):
            with self.assertLogs("custom_components.catgenie", level="WARNING") as logs:
                with self.assertRaises(RuntimeError) as caught:
                    await integration.async_setup_entry(self.hass, entry_for())
        self.assertIs(caught.exception, original)
        session.close.assert_awaited_once()
        self.assertIn("OSError", "\n".join(logs.output))
        self.assertNotIn(MARK, "\n".join(logs.output))

    async def test_existing_controls_command_privacy_is_reused(self):
        async def fail():
            raise CatGenieAPIError(MARK)
        coord = SimpleNamespace(async_request_refresh=AsyncMock())
        with self.assertRaises(HomeAssistantError) as caught:
            await async_run_command(coord, fail())
        self.assertNotIn(MARK, str(caught.exception))
        coord.async_request_refresh.assert_not_awaited()

    async def test_user_login_code_response_status_and_shape(self):
        for result in ({"status": 200}, {"status": 299}, {"status": 199}, {"status": 300},
                       {"status": 503}, {"status": "200"}, {"status": True}, {"status": None}, {}, [], None):
            with self.subTest(result=result):
                auth = SimpleNamespace(request_login_code=AsyncMock(return_value=result), async_close=AsyncMock())
                with patch.object(cf, "CatGenieAuth", return_value=auth):
                    flow = self.flow()
                    answer = await flow.async_step_user({"country_code": "+1", "phone": "05550100"})
                valid = isinstance(result, dict) and type(result.get("status")) is int and 200 <= result["status"] < 300
                self.assertEqual(answer["step_id"], "code" if valid else "user")
                self.assertEqual(answer["errors"], {} if valid else {"base": "cannot_connect"})
                auth.async_close.assert_awaited_once()

    async def test_user_code_and_reauth_transport_mapping_and_safe_logs(self):
        logger = logging.getLogger(cf.__name__)
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        for reauth in (False, True):
            for step in ("user", "code"):
                for exc in (RequestException(MARK), TimeoutError(MARK), RuntimeError(MARK)):
                    with self.subTest(reauth=reauth, step=step, exc=type(exc).__name__):
                        flow = self.flow(entry_for() if reauth else None)
                        flow._country_code, flow._phone = 1, "5550100"
                        auth = SimpleNamespace(request_login_code=AsyncMock(side_effect=exc),
                            login=AsyncMock(side_effect=exc), async_close=AsyncMock())
                        with patch.object(cf, "CatGenieAuth", return_value=auth):
                            answer = await (flow.async_step_user({"country_code": "1", "phone": "5550100"})
                                if step == "user" else flow.async_step_code({"code": "synthetic-code"}))
                        self.assertEqual(answer["errors"], {"base": "unknown" if isinstance(exc, RuntimeError) else "cannot_connect"})
                        auth.async_close.assert_awaited_once()
        self.assertNotIn(MARK, output.getvalue())

    async def test_code_auth_success_failure_and_reauth_account_semantics(self):
        for reauth in (False, True):
            for account in ("synthetic-account", "synthetic-wrong"):
                flow = self.flow(entry_for() if reauth else None)
                if reauth:
                    self.assertEqual((await flow.async_step_reauth({}))["step_id"], "user")
                flow._country_code, flow._phone = 1, "5550100"
                creds = Credentials(refresh_token="synthetic-new", access_token="synthetic-access",
                    account_id=account, user_id="synthetic-user", tenant_id="synthetic-tenant")
                auth = SimpleNamespace(login=AsyncMock(return_value=creds), async_close=AsyncMock())
                with patch.object(cf, "CatGenieAuth", return_value=auth), patch.object(self.hass.config_entries, "async_schedule_reload") as reload:
                    if reauth and account != "synthetic-account":
                        with self.assertRaises(AbortFlow) as caught:
                            await flow.async_step_code({"code": "synthetic-code"})
                        self.assertEqual(caught.exception.reason, "wrong_account")
                        reload.assert_not_called()
                        self.assertEqual(flow._get_reauth_entry().data["refresh_token"], "synthetic-old")
                    else:
                        answer = await flow.async_step_code({"code": "synthetic-code"})
                        if reauth:
                            self.assertEqual(answer["reason"], "reauth_successful")
                            self.assertEqual(flow._get_reauth_entry().data["refresh_token"], "synthetic-new")
                            reload.assert_called_once_with(flow._get_reauth_entry().entry_id)
                        else:
                            self.assertEqual(answer["type"], "create_entry")
                            self.assertNotIn("access_token", answer["data"])
                auth.async_close.assert_awaited_once()
        for creds in (Credentials(), Credentials(refresh_token="synthetic-new")):
            flow = self.flow()
            flow._country_code, flow._phone = 1, "5550100"
            auth = SimpleNamespace(login=AsyncMock(return_value=creds), async_close=AsyncMock())
            with patch.object(cf, "CatGenieAuth", return_value=auth):
                self.assertEqual((await flow.async_step_code({"code": "synthetic-code"}))["errors"], {"base": "invalid_auth"})
        for exc, expected in ((CatGenieAuthenticationError(MARK), "invalid_auth"), (CatGenieAPIError(MARK), "cannot_connect")):
            flow = self.flow()
            flow._country_code, flow._phone = 1, "5550100"
            auth = SimpleNamespace(login=AsyncMock(side_effect=exc), async_close=AsyncMock())
            with patch.object(cf, "CatGenieAuth", return_value=auth):
                self.assertEqual((await flow.async_step_code({"code": "synthetic-code"}))["errors"], {"base": expected})
            auth.async_close.assert_awaited_once()

    async def test_mac_guard_preserves_identifiers_and_valid_connections(self):
        from custom_components.catgenie.activity import ACTIVITY_SENSORS, CatGenieActivitySensor
        from custom_components.catgenie.read_sensors import READ_SENSORS, CatGenieReadSensor
        for mac, expected in (("", set()), ("unknown", set()), ("zz:zz:zz:zz:zz:zz", set()),
            ("AABBCCDDEEFF", {("mac", "aa:bb:cc:dd:ee:ff")}),
            ("AA:BB:CC:DD:EE:FF", {("mac", "aa:bb:cc:dd:ee:ff")})):
            with self.subTest(mac=mac):
                device = TolerantDevice.model_validate({"manufacturerId": "synthetic-unit", "name": "Synthetic",
                    "macAddress": mac, "hwRevision": "1", "fwVersion": "1", "operationStatus": {"state": 0, "progress": 255}})
                coord = CatGenieCoordinator(self.hass, entry_for(), None)
                coord.async_set_updated_data({device.manufacturer_id: device})
                entities = (
                    CatGenieEntity(coord, device.manufacturer_id),
                    CatGenieActivitySensor(coord, coord, device.manufacturer_id, ACTIVITY_SENSORS[0]),
                    CatGenieReadSensor(coord, coord, device.manufacturer_id, READ_SENSORS[0]),
                )
                for entity in entities:
                    self.assertEqual(entity.device_info["connections"], expected)
                    self.assertEqual(entity.device_info["identifiers"], {("catgenie", "synthetic-unit")})
                    self.assertEqual(entity.device_info["serial_number"], "synthetic-unit")


class Response:
    def __init__(self, body):
        self.status_code = 200
        self.content = json.dumps(body).encode()
    def json(self):
        return json.loads(self.content)


class SyntheticSession:
    def __init__(self):
        self.refreshes = 0
        self.calls = []
        self.failure = None
        self.expires_in = 3600
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
    async def request(self, method, url, **kwargs):
        if "refreshToken" in url:
            self.refreshes += 1
            self.entered.set()
            await self.release.wait()
            await asyncio.sleep(0)
            if self.failure:
                raise self.failure
            return Response({"token": "synthetic-access", "expiration": (time.time() + self.expires_in) * 1000})
        self.calls.append((method, url, kwargs["headers"].get("authorization")))
        return Response({"thingList": []})


class RefreshCases(unittest.IsolatedAsyncioTestCase):
    def client(self):
        # Setup must use this subclass too; fallback makes the parent RED executable.
        from custom_components.catgenie import client as adapter
        cls = getattr(adapter, "HomeAssistantCatGenieAuth", CatGenieAuth)
        session = SyntheticSession()
        creds = Credentials(refresh_token="synthetic-refresh")
        auth = cls(session=session)
        auth.credentials = creds
        client = HomeAssistantCatGenieClient(creds, session=session)
        client.set_auth(auth)
        return session, creds, auth, client

    async def test_actual_adapter_concurrent_poll_history_feed_command_singleflight(self):
        from catgenie.const import ENDPOINT_NOTIFICATIONS, ENDPOINT_PET_STATS
        session, creds, auth, client = self.client()
        await asyncio.gather(client.get_devices(), client._request("GET", ENDPOINT_PET_STATS, params={"startTime": "2026-01-01T00:00:00Z"}),
            client._request("GET", ENDPOINT_NOTIFICATIONS), client.start_cleaning("synthetic-unit"))
        self.assertEqual(session.refreshes, 1)
        self.assertIs(auth.credentials, creds)
        self.assertIs(client._session, auth._session)
        self.assertTrue(all(row[2] == "Bearer synthetic-access" for row in session.calls))
        creds.token_expiration = 0
        await asyncio.gather(client.get_devices(), client.get_devices())
        self.assertEqual(session.refreshes, 2)

    async def test_explicit_refresh_with_valid_token_is_not_skipped(self):
        session, creds, auth, client = self.client()
        await client.get_devices()
        await auth.refresh()  # Library 401 retry must still refresh a valid token.
        self.assertEqual(session.refreshes, 2)

    async def test_waiter_rechecks_expiration_after_successful_refresh(self):
        session, creds, auth, client = self.client()
        session.expires_in = -10
        await asyncio.gather(auth.refresh(), auth.refresh())
        self.assertEqual(session.refreshes, 2)
        self.assertTrue(creds.is_token_expired)

    async def test_refresh_exception_and_cancellation_release_waiters(self):
        session, creds, auth, client = self.client()
        session.failure = RequestException("synthetic failure")
        results = await asyncio.gather(client.get_devices(), client.get_devices(), return_exceptions=True)
        self.assertTrue(all(isinstance(result, RequestException) for result in results))
        session.failure = None
        session.release.clear()
        session.entered.clear()
        first = asyncio.create_task(client.get_devices())
        await asyncio.wait_for(session.entered.wait(), 2)
        second = asyncio.create_task(client.get_devices())
        await asyncio.sleep(0)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        session.release.set()
        self.assertEqual(await asyncio.wait_for(second, 2), [])
        self.assertFalse(creds.is_token_expired)


class MetadataCases(unittest.TestCase):
    def test_reserved_module_and_generic_schedule_hold(self):
        self.assertFalse((ROOT / "custom_components/catgenie/diagnostics.py").exists())
        from custom_components.catgenie.reported_config import SCHEDULE_DISPLAY_HOLD
        self.assertIn("unverified", SCHEDULE_DISPLAY_HOLD["reason"])
        self.assertNotIn("-05:00", SCHEDULE_DISPLAY_HOLD["reason"])

    def test_ci_pins_commands_and_runtime_metadata(self):
        import yaml
        from importlib.metadata import metadata
        from packaging.specifiers import SpecifierSet
        workflow = yaml.safe_load((ROOT / ".github/workflows/pylint.yml").read_text())
        self.assertEqual(workflow.get("on", workflow.get(True)), ["push", "pull_request"])
        job = workflow["jobs"]["runtime-tests"]
        steps = job["steps"]
        setup = next(step for step in steps if step.get("uses", "").startswith("actions/setup-python@"))
        self.assertEqual(setup["with"]["python-version"], "3.14")
        commands = "\n".join(step.get("run", "") for step in steps)
        for token in ("homeassistant==2026.10.4", "catgenie==0.1.6", "-B -m unittest discover -s tests -q", "runtime_regression_cases.py", "read_information_ha_contract.py"):
            self.assertIn(token, commands)
        minimum = workflow["jobs"]["minimum-runtime-tests"]["steps"]
        minimum_setup = next(step for step in minimum if step.get("uses", "").startswith("actions/setup-python@"))
        self.assertEqual(minimum_setup["with"]["python-version"], "3.13")
        minimum_commands = "\n".join(step.get("run", "") for step in minimum)
        for token in ("homeassistant==2025.7.0", "catgenie==0.1.6", "probatio==0.13.0", "pycares==4.11.0", "pip check", "CATGENIE_REQUIRE_CONTRACTS=1", "runtime_regression_cases.py", "read_information_ha_contract.py"):
            self.assertIn(token, minimum_commands)
        # Match installed metadata to its own runtime job, not the other job.
        installed_ha = metadata("homeassistant")["Version"]
        matching = [text for text in (commands, minimum_commands)
                    if f"homeassistant=={installed_ha}" in text]
        self.assertEqual(len(matching), 1, f"Unrecorded HA test runtime: {installed_ha}")
        self.assertIn(f"catgenie=={metadata('catgenie')['Version']}", matching[0])
        if matching[0] == commands:
            for package in ("pydantic", "curl_cffi", "PyYAML"):
                self.assertIn(f"{package}=={metadata(package)['Version']}", commands)
            self.assertNotIn("3.13", SpecifierSet(metadata("homeassistant")["Requires-Python"]))
        else:
            from platform import python_version
            self.assertIn(python_version(), SpecifierSet(metadata("homeassistant")["Requires-Python"]))
            self.assertIn(f"pycares=={metadata('pycares')['Version']}", minimum_commands)
        compat_steps = workflow["jobs"]["dependency-compatibility"]["steps"]
        compat_commands = "\n".join(step.get("run", "") for step in compat_steps)
        self.assertNotIn("pip install homeassistant", compat_commands)
        self.assertIn("test_unknown_operation_state.py", compat_commands)
        for package in ("catgenie", "pydantic", "curl_cffi"):
            self.assertIn("3.13", SpecifierSet(metadata(package)["Requires-Python"]))
            self.assertIn(f"{package}=={metadata(package)['Version']}", compat_commands)
        init = (ROOT / "custom_components/catgenie/__init__.py").read_text()
        self.assertNotIn("integration 0.1.2", init)
        self.assertIn("| Version | v1.0.1 |", (ROOT / "README.md").read_text())
        strings = json.loads((ROOT / "custom_components/catgenie/translations/en.json").read_text())
        self.assertNotIn("back", strings["config"]["error"]["invalid_auth"].lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
