"""SYNTHETIC pending-display regressions. Not live vendor or device results.

An accepted PUT is not vendor confirmation. These tests require the select
and number to keep the requested value when the following GET is stale,
without patching coordinator device data.
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.unit_cases.test_settings_controls import (
    CatGenieException,
    CatGenieNumber,
    CatGenieSelect,
    HomeAssistantError,
    activation_label,
    display_volume,
    make_device,
)

INTEGRATION = Path(__file__).resolve().parents[2] / "custom_components" / "catgenie"
DEVICE_ID = "settings-device"


class _Client:
    def __init__(self) -> None:
        self.bodies: list[dict] = []
        self.methods: list[str] = []
        self.gates: list[asyncio.Event] = []
        self.fail_on: set[int] = set()
        self.calls = 0
        self.error: Exception | None = None
        self.ack = {"accepted": True, "not": "vendor-confirmation"}

    async def update_configuration(self, device_id: str, **body: object) -> dict:
        self.calls += 1
        call = self.calls
        self.methods.append("update_configuration")
        self.bodies.append({"device_id": device_id, **body})
        if self.gates:
            await self.gates.pop(0).wait()
        if self.error or call in self.fail_on:
            raise self.error or CatGenieException("synthetic failure")
        return dict(self.ack)

    async def set_cleaning_mode(self, *args: object, **kwargs: object) -> dict:
        raise AssertionError("library set_cleaning_mode must not be used")

    async def set_volume(self, *args: object, **kwargs: object) -> dict:
        raise AssertionError("unbounded library set_volume must not be used")

    async def set_schedule(self, *args: object, **kwargs: object) -> dict:
        raise AssertionError("schedule must not be created or rewritten")


class _Coordinator:
    """Applies a replacement device inside refresh so a stale GET is not a no-op."""

    def __init__(self, device: object) -> None:
        self.data = {DEVICE_ID: device}
        self.client = _Client()
        self.refreshes = 0
        self.refresh_error: Exception | None = None
        self.on_refresh = lambda: make_device()

    async def async_request_refresh(self) -> None:
        self.refreshes += 1
        if self.refresh_error:
            raise self.refresh_error
        replacement = self.on_refresh()
        if replacement is not None:
            self.data[DEVICE_ID] = replacement


def _select(coordinator: _Coordinator) -> CatGenieSelect:
    from tests.unit_cases.test_settings_controls import SELECTS

    description = next(item for item in SELECTS if item.key == "activation_mode")
    return CatGenieSelect(coordinator, DEVICE_ID, description)


def _number(coordinator: _Coordinator) -> CatGenieNumber:
    from tests.unit_cases.test_settings_controls import NUMBERS

    description = next(item for item in NUMBERS if item.key == "volume")
    return CatGenieNumber(coordinator, DEVICE_ID, description)


def _bind_clock(entity: object) -> dict[str, float]:
    box = {"t": 10_000.0}
    entity._pending._now = lambda: box["t"]
    return box


class SettingsFeedbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_ack_then_stale_get_holds_select_without_patching_device(self) -> None:
        original = make_device()
        coordinator = _Coordinator(original)
        entity = _select(coordinator)
        other = _select(coordinator)
        await entity.async_select_option("time")
        self.assertEqual(coordinator.refreshes, 1)
        self.assertEqual(coordinator.client.methods, ["update_configuration"])
        self.assertEqual(
            coordinator.client.bodies,
            [{"device_id": DEVICE_ID, "mode": 1, "manual": 0}],
        )
        self.assertIsNot(entity.device, original)
        self.assertEqual(activation_label(original), "cat")
        self.assertEqual(activation_label(entity.device), "cat")
        self.assertEqual(entity.device.configuration.volume_level, 7)
        self.assertEqual(entity.current_option, "time")
        self.assertEqual(entity.extra_state_attributes, {"pending_confirmation": True})
        self.assertNotIn("confirmed", entity.extra_state_attributes)
        self.assertEqual(other.current_option, "cat")
        self.assertIsNone(other.extra_state_attributes)

    async def test_matching_get_clears_pending_without_treating_ack_as_confirmation(self) -> None:
        coordinator = _Coordinator(make_device())
        entity = _select(coordinator)
        coordinator.on_refresh = lambda: make_device(
            configuration={"mode": 1, "manual": 0, "volumeLevel": 7}
        )
        await entity.async_select_option("time")
        self.assertEqual(activation_label(entity.device), "time")
        self.assertEqual(entity.current_option, "time")
        self.assertIsNone(entity.extra_state_attributes)
        self.assertEqual(coordinator.client.ack["not"], "vendor-confirmation")

    async def test_rejected_put_does_not_hold_or_refresh(self) -> None:
        coordinator = _Coordinator(make_device())
        entity = _select(coordinator)
        coordinator.client.error = CatGenieException("synthetic failure")
        with self.assertRaises(HomeAssistantError):
            await entity.async_select_option("manual")
        self.assertEqual(coordinator.refreshes, 0)
        self.assertEqual(entity.current_option, "cat")
        self.assertIsNone(entity.extra_state_attributes)
        self.assertEqual(activation_label(entity.device), "cat")

    async def test_refresh_failure_after_ack_holds_and_still_raises(self) -> None:
        coordinator = _Coordinator(make_device())
        entity = _select(coordinator)
        coordinator.refresh_error = RuntimeError("synthetic refresh failure")
        with self.assertRaises(RuntimeError):
            await entity.async_select_option("manual")
        self.assertEqual(coordinator.refreshes, 1)
        self.assertEqual(coordinator.client.methods, ["update_configuration"])
        self.assertEqual(activation_label(entity.device), "cat")
        self.assertEqual(entity.current_option, "manual")
        self.assertEqual(entity.extra_state_attributes, {"pending_confirmation": True})

    async def test_offline_refusal_and_missing_device_drop_pending(self) -> None:
        offline = _Coordinator(make_device(reportedStatus="disconnected"))
        refused = _select(offline)
        with self.assertRaises(HomeAssistantError) as raised:
            await refused.async_select_option("cat")
        self.assertIn("offline", str(raised.exception))
        self.assertIn("not changed", str(raised.exception))
        self.assertEqual(offline.client.bodies, [])
        self.assertEqual(offline.refreshes, 0)
        self.assertIsNone(refused.extra_state_attributes)

        coordinator = _Coordinator(make_device())
        entity = _select(coordinator)
        await entity.async_select_option("time")
        self.assertTrue(entity.available)
        self.assertEqual(entity.current_option, "time")
        del coordinator.data[DEVICE_ID]
        self.assertIsNone(entity.device)
        self.assertFalse(entity.available)
        self.assertIsNone(entity.current_option)
        self.assertIsNone(entity.extra_state_attributes)
        coordinator.data[DEVICE_ID] = make_device()
        self.assertEqual(activation_label(entity.device), "cat")
        self.assertEqual(entity.current_option, "cat")
        self.assertIsNone(entity.extra_state_attributes)
        self.assertTrue(entity.available)

    async def test_pending_expires_at_two_idle_intervals(self) -> None:
        coordinator = _Coordinator(make_device())
        entity = _select(coordinator)
        clock = _bind_clock(entity)
        self.assertEqual(entity._pending.window_seconds, 120.0)
        await entity.async_select_option("manual")
        self.assertEqual(entity.current_option, "manual")
        clock["t"] += 119
        self.assertEqual(entity.current_option, "manual")
        self.assertEqual(entity.extra_state_attributes, {"pending_confirmation": True})
        clock["t"] += 1
        self.assertEqual(activation_label(entity.device), "cat")
        self.assertEqual(entity.current_option, "cat")
        self.assertIsNone(entity.extra_state_attributes)

    async def test_latest_accepted_wins_over_stale_completion(self) -> None:
        coordinator = _Coordinator(make_device())
        entity = _select(coordinator)
        gate_a = asyncio.Event()
        gate_b = asyncio.Event()
        coordinator.client.gates = [gate_a, gate_b]
        task_a = asyncio.create_task(entity.async_select_option("manual"))
        await asyncio.sleep(0)
        self.assertEqual(entity.current_option, "cat")
        task_b = asyncio.create_task(entity.async_select_option("time"))
        await asyncio.sleep(0)
        self.assertEqual(entity.current_option, "cat")
        gate_a.set()
        await asyncio.wait_for(task_a, 3)
        self.assertEqual(entity.current_option, "manual")
        gate_b.set()
        await asyncio.wait_for(task_b, 3)
        self.assertEqual(coordinator.refreshes, 2)
        self.assertEqual(entity.current_option, "time")
        self.assertEqual(entity.extra_state_attributes, {"pending_confirmation": True})
        self.assertEqual(activation_label(entity.device), "cat")
        coordinator.data[DEVICE_ID] = make_device(
            configuration={"mode": 0, "manual": 1, "volumeLevel": 7}
        )
        self.assertEqual(activation_label(entity.device), "manual")
        self.assertEqual(entity.current_option, "time")
        coordinator.data[DEVICE_ID] = make_device(
            configuration={"mode": 1, "manual": 0, "volumeLevel": 7}
        )
        self.assertEqual(entity.current_option, "time")
        self.assertIsNone(entity.extra_state_attributes)

    async def test_later_failure_does_not_drop_earlier_accept(self) -> None:
        coordinator = _Coordinator(make_device())
        entity = _select(coordinator)
        gate_a = asyncio.Event()
        gate_b = asyncio.Event()
        coordinator.client.gates = [gate_a, gate_b]
        coordinator.client.fail_on.add(2)
        task_a = asyncio.create_task(entity.async_select_option("manual"))
        await asyncio.sleep(0)
        task_b = asyncio.create_task(entity.async_select_option("time"))
        await asyncio.sleep(0)
        gate_a.set()
        await asyncio.wait_for(task_a, 3)
        gate_b.set()
        with self.assertRaises(HomeAssistantError):
            await asyncio.wait_for(task_b, 3)
        self.assertEqual(entity.current_option, "manual")
        self.assertEqual(entity.extra_state_attributes, {"pending_confirmation": True})
        self.assertEqual(activation_label(entity.device), "cat")

    async def test_volume_stale_get_holds_integer_without_changing_polled_field(self) -> None:
        coordinator = _Coordinator(make_device())
        entity = _number(coordinator)
        await entity.async_set_native_value(4.0)
        self.assertEqual(coordinator.refreshes, 1)
        self.assertEqual(
            coordinator.client.bodies,
            [{"device_id": DEVICE_ID, "volumeLevel": 4}],
        )
        self.assertEqual(entity.device.configuration.volume_level, 7)
        self.assertEqual(display_volume(entity.device), 7)
        self.assertEqual(entity.native_value, 4)
        self.assertIs(type(entity.native_value), int)
        self.assertEqual(entity.native_min_value, 1)
        self.assertEqual(entity.native_max_value, 7)
        self.assertIsNone(entity.native_unit_of_measurement)
        self.assertEqual(entity.extra_state_attributes, {"pending_confirmation": True})
        same = _number(_Coordinator(make_device()))
        await same.async_set_native_value(7)
        self.assertEqual(same.native_value, 7)
        self.assertIsNone(same.extra_state_attributes)

    async def test_volume_match_rejection_and_timeout(self) -> None:
        matched = _Coordinator(make_device())
        matched.on_refresh = lambda: make_device(
            configuration={"mode": 0, "manual": 0, "volumeLevel": 2}
        )
        number = _number(matched)
        await number.async_set_native_value(2)
        self.assertEqual(number.native_value, 2)
        self.assertIsNone(number.extra_state_attributes)
        self.assertEqual(number.device.configuration.volume_level, 2)

        refused = _Coordinator(make_device())
        refused.client.error = CatGenieException("synthetic failure")
        entity = _number(refused)
        with self.assertRaises(HomeAssistantError):
            await entity.async_set_native_value(3)
        self.assertEqual(entity.native_value, 7)
        self.assertIsNone(entity.extra_state_attributes)
        self.assertEqual(refused.refreshes, 0)

        held = _number(_Coordinator(make_device()))
        clock = _bind_clock(held)
        await held.async_set_native_value(5)
        self.assertEqual(held.native_value, 5)
        clock["t"] += held._pending.window_seconds
        self.assertEqual(held.device.configuration.volume_level, 7)
        self.assertEqual(held.native_value, 7)
        self.assertIsNone(held.extra_state_attributes)

    async def test_expiry_timer_uses_ha_call_later_and_unloads(self) -> None:
        import sys
        import types

        import threading

        loop_thread = threading.get_ident()
        previous_core = sys.modules.get("homeassistant.core")
        core = types.ModuleType("homeassistant.core")

        def callback(func):
            func._hass_callback = True
            return func

        core.callback = callback
        sys.modules["homeassistant.core"] = core

        async def dispatch(action):
            if getattr(action, "_hass_callback", False):
                action(datetime.now(timezone.utc))
            else:
                await asyncio.to_thread(action, datetime.now(timezone.utc))

        recorded: list[dict] = []
        added: list[str] = []
        module = types.ModuleType("homeassistant.helpers.event")
        module.__package__ = "homeassistant.helpers"

        def async_call_later(hass: object, delay: float | timedelta, action: object):
            if not callable(action):
                raise TypeError("action must be callable")
            seconds = delay.total_seconds() if isinstance(delay, timedelta) else delay
            if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
                raise TypeError(type(delay))
            handle = {"cancelled": 0, "action": action, "delay": seconds, "hass": hass}

            def cancel() -> None:
                handle["cancelled"] += 1

            handle["cancel"] = cancel
            recorded.append(handle)
            return cancel

        module.async_call_later = async_call_later
        def unexpected_poll(*args, **kwargs):
            self.fail("timer seam must not add a poll")

        module.async_track_time_interval = unexpected_poll
        previous = sys.modules.get("homeassistant.helpers.event")
        for name in ("homeassistant", "homeassistant.helpers"):
            if name not in sys.modules:
                parent = types.ModuleType(name)
                parent.__path__ = []
                parent.__package__ = name
                sys.modules[name] = parent
                added.append(name)
        sys.modules["homeassistant"].helpers = sys.modules["homeassistant.helpers"]
        sys.modules["homeassistant.helpers"].event = module
        sys.modules["homeassistant.helpers.event"] = module
        try:
            coordinator = _Coordinator(make_device())
            entity = _select(coordinator)
            writes: list[str] = []
            unloads: list[object] = []
            entity.hass = object()
            def write_state():
                if threading.get_ident() != loop_thread:
                    raise RuntimeError("async_write_ha_state called outside event loop")
                writes.append("write")

            entity.async_write_ha_state = write_state
            entity.async_on_remove = unloads.append
            await entity.async_select_option("manual")
            self.assertEqual(len(recorded), 1)
            self.assertEqual(recorded[0]["delay"], 120.0)
            self.assertIs(recorded[0]["hass"], entity.hass)
            self.assertEqual(writes, ["write"])
            self.assertEqual(len(unloads), 1)
            self.assertEqual(entity.current_option, "manual")
            await entity.async_select_option("time")
            self.assertEqual(recorded[0]["cancelled"], 1)
            self.assertEqual(len(recorded), 2)
            self.assertEqual(len(unloads), 1)
            await dispatch(recorded[0]["action"])
            self.assertEqual(entity.current_option, "time")
            await dispatch(recorded[1]["action"])
            self.assertEqual(entity.current_option, "cat")
            self.assertIsNone(entity.extra_state_attributes)
            unloads[0]()
            self.assertEqual(recorded[1]["cancelled"], 1)
            unloads[0]()
            self.assertEqual(recorded[1]["cancelled"], 1)
        finally:
            if previous_core is None:
                sys.modules.pop("homeassistant.core", None)
            else:
                sys.modules["homeassistant.core"] = previous_core
            if previous is None:
                sys.modules.pop("homeassistant.helpers.event", None)
            else:
                sys.modules["homeassistant.helpers.event"] = previous
            for name in added:
                sys.modules.pop(name, None)

    def test_write_path_keeps_one_refresh_and_two_idle_window(self) -> None:
        select_src = (INTEGRATION / "select.py").read_text()
        number_src = (INTEGRATION / "number.py").read_text()
        entity_src = (INTEGRATION / "entity.py").read_text()
        pending_src = (INTEGRATION / "settings_pending.py").read_text()
        for src in (select_src, number_src, pending_src):
            self.assertNotIn("async_request_refresh", src)
            self.assertNotIn("async_track_time_interval", src)
        self.assertEqual(entity_src.count("async_request_refresh"), 1)
        self.assertIn("async_run_command", select_src)
        self.assertIn("async_run_command", number_src)
        self.assertIn("SCAN_INTERVAL_IDLE * 2", pending_src)
        self.assertIn("async_call_later", pending_src)
        self.assertIn("async_on_remove", pending_src)
        resolve = pending_src.split("def resolve", 1)[1].split(
            "def cancel_settings_pending_timer", 1
        )[0]
        self.assertNotIn("_baseline", resolve)
        self.assertIn("intermediate GET from an older write", resolve)


def _registered(coordinator: object, kind: str, key: str):
    added: list[object] = []

    class _Entry:
        runtime_data = coordinator

    entity_cls = CatGenieNumber if kind == "number" else CatGenieSelect
    method = (
        entity_cls.async_set_native_value
        if kind == "number"
        else entity_cls.async_select_option
    )
    setup = method.__globals__["async_setup_entry"]

    async def _add() -> object:
        await setup(None, _Entry(), lambda entities: added.extend(entities))
        return next(item for item in added if item.entity_description.key == key)

    return _add()


def _replace_and_notify(coordinator: _Coordinator, device: object, listeners: list) -> list:
    """Data is replaced before listeners run. A listener is not a new poll."""
    coordinator.data[DEVICE_ID] = device
    return [listener() for listener in listeners]


def _number_state(entity: CatGenieNumber, *, attributes_first: bool = False):
    """HA state write reads the value, then extra attributes. Both orders are checked."""
    if attributes_first:
        attrs = entity.extra_state_attributes
        value = entity.native_value
    else:
        value = entity.native_value
        attrs = entity.extra_state_attributes
    return value, attrs


class ControlReconciliationTests(unittest.IsolatedAsyncioTestCase):
    """Registered number/select hold after a coordinator data replace.

    SYNTHETIC. Not a live timing measurement and not a vendor confirmation.
    The reported delay sensor reads ``configuration.cat_delay`` in seconds.
    """

    async def test_confirmed_delay_follows_later_cloud_on_that_notification(self) -> None:
        import tests.unit_cases.test_settings_controls as controls

        coordinator = controls._Coordinator(make_device())
        entity = await _registered(coordinator, "number", "cat_activation_delay")
        self.assertEqual(entity.native_value, 30)
        await entity.async_set_native_value(20)
        self.assertEqual(entity._pending._baseline, 30)
        self.assertEqual(_number_state(entity), (20, {"pending_confirmation": True}))
        self.assertEqual(entity.device.configuration.cat_delay, 1800)
        self.assertEqual(coordinator.client.methods, ["get_devices", "update_configuration"])
        self.assertEqual(coordinator.refreshes, 1)

        order: list[tuple] = []

        def sensor() -> None:
            order.append(("sensor", coordinator.data[DEVICE_ID].configuration.cat_delay))

        def number() -> None:
            order.append(("number",) + _number_state(entity, attributes_first=True))

        _replace_and_notify(
            coordinator, make_device(configuration={"catDelay": 1200}), [sensor, number]
        )
        self.assertEqual(order, [("sensor", 1200), ("number", 20, None)])
        self.assertFalse(entity._pending.active)

        order.clear()

        def number_then_sensor() -> None:
            order.append(("number",) + _number_state(entity))

        def sensor_after() -> None:
            order.append(("sensor", coordinator.data[DEVICE_ID].configuration.cat_delay))

        _replace_and_notify(
            coordinator,
            make_device(configuration={"catDelay": 600}),
            [number_then_sensor, sensor_after],
        )
        self.assertEqual(order, [("number", 10, None), ("sensor", 600)])
        self.assertIs(type(entity.native_value), int)
        self.assertEqual(entity.native_unit_of_measurement, "min")
        self.assertEqual(coordinator.refreshes, 1)
        self.assertEqual(coordinator.client.methods.count("get_devices"), 1)

    async def test_unconfirmed_nonmatch_keeps_hold_until_two_idle_intervals(self) -> None:
        import tests.unit_cases.test_settings_controls as controls

        cached = make_device()
        fresh = make_device(
            configuration={
                "dndFrom": "22:15:00",
                "dndTo": "02:45:09",
                "catDelay": 600,
                "schedule": [{"hour": 7, "minute": 30, "time": "07:30:00"}],
            }
        )
        coordinator = controls._Coordinator(cached)
        coordinator.client.fresh_devices = [fresh]
        entity = await _registered(coordinator, "number", "cat_activation_delay")
        clock = _bind_clock(entity)
        await entity.async_set_native_value(15)
        self.assertEqual(entity._pending._baseline, 30)
        self.assertIs(coordinator.data[DEVICE_ID], cached)
        self.assertEqual(cached.configuration.cat_delay, 1800)
        body = coordinator.client.bodies[0]
        self.assertEqual(body["catDelay"], 900)
        self.assertIs(body["dndFrom"], fresh.configuration.model_extra["dndFrom"])
        self.assertEqual(coordinator.client.methods.count("get_devices"), 1)

        reads: list[tuple] = []

        def sensor() -> None:
            reads.append(("sensor", coordinator.data[DEVICE_ID].configuration.cat_delay))

        def number() -> None:
            reads.append(("number",) + _number_state(entity))

        def reverse() -> None:
            reads.append(("reverse",) + _number_state(entity, attributes_first=True))

        _replace_and_notify(
            coordinator,
            make_device(configuration={"catDelay": 600, "dndFrom": "22:15:00", "dndTo": "02:45:09"}),
            [sensor, number],
        )
        self.assertEqual(reads, [
            ("sensor", 600),
            ("number", 15, {"pending_confirmation": True}),
        ])
        self.assertTrue(entity._pending.active)

        reads.clear()
        _replace_and_notify(
            coordinator, make_device(configuration={"catDelay": 1800}), [reverse, sensor]
        )
        self.assertEqual(reads[0], ("reverse", 15, {"pending_confirmation": True}))
        self.assertEqual(coordinator.data[DEVICE_ID].configuration.cat_delay, 1800)

        _replace_and_notify(
            coordinator, make_device(configuration={"catDelay": 1200}), [number, sensor]
        )
        self.assertEqual(entity.native_value, 15)
        self.assertEqual(coordinator.data[DEVICE_ID].configuration.cat_delay, 1200)
        _replace_and_notify(
            coordinator, make_device(configuration={"catDelay": 100}), [sensor, number]
        )
        self.assertEqual(entity.native_value, 15)
        self.assertEqual(coordinator.data[DEVICE_ID].configuration.cat_delay, 100)

        app_shaped = make_device(configuration={"catDelay": 1200})
        _replace_and_notify(coordinator, app_shaped, [sensor])
        clock["t"] += 119
        self.assertEqual(_number_state(entity), (15, {"pending_confirmation": True}))
        clock["t"] += 1
        self.assertEqual(_number_state(entity), (20, None))
        self.assertFalse(entity._pending.active)
        self.assertEqual(coordinator.refreshes, 1)

    async def test_failed_put_and_missing_device_drop_before_a_later_read(self) -> None:
        import tests.unit_cases.test_settings_controls as controls

        coordinator = controls._Coordinator(make_device())
        entity = await _registered(coordinator, "number", "cat_activation_delay")
        coordinator.client.error = CatGenieException("synthetic failure")
        with self.assertRaises(HomeAssistantError):
            await entity.async_set_native_value(20)
        self.assertEqual(coordinator.refreshes, 0)
        self.assertEqual(coordinator.client.methods, ["get_devices", "update_configuration"])
        self.assertEqual(entity.native_value, 30)
        self.assertIsNone(entity.extra_state_attributes)
        self.assertFalse(entity._pending.active)
        self.assertEqual(entity.device.configuration.cat_delay, 1800)

        held = controls._Coordinator(make_device())
        number = await _registered(held, "number", "cat_activation_delay")
        await number.async_set_native_value(20)
        del held.data[DEVICE_ID]
        self.assertIsNone(number.device)
        self.assertFalse(number.available)
        self.assertEqual(_number_state(number), (None, None))
        self.assertFalse(number._pending.active)
        held.data[DEVICE_ID] = make_device(configuration={"catDelay": 600})
        self.assertEqual(_number_state(number), (10, None))

    async def test_latest_delay_ack_survives_intermediate_older_cloud(self) -> None:
        import tests.unit_cases.test_settings_controls as controls

        coordinator = controls._Coordinator(make_device())
        entity = await _registered(coordinator, "number", "cat_activation_delay")
        opened: list[asyncio.Event] = []
        original = coordinator.client.update_configuration

        async def gated(device_id: str, **body: object) -> dict:
            gate = asyncio.Event()
            opened.append(gate)
            await gate.wait()
            return await original(device_id, **body)

        coordinator.client.update_configuration = gated
        older = asyncio.create_task(entity.async_set_native_value(20))
        await asyncio.sleep(0)
        self.assertEqual(len(opened), 1)
        self.assertEqual(entity.native_value, 30)
        latest = asyncio.create_task(entity.async_set_native_value(10))
        await asyncio.sleep(0)
        self.assertEqual(len(opened), 1)  # second transaction waits before GET
        opened[0].set()
        await asyncio.wait_for(older, 3)
        self.assertEqual(len(opened), 2)
        self.assertEqual(_number_state(entity), (20, {"pending_confirmation": True}))
        opened[1].set()
        await asyncio.wait_for(latest, 3)
        self.assertEqual(entity.native_value, 10)
        self.assertEqual(coordinator.refreshes, 2)
        _replace_and_notify(
            coordinator, make_device(configuration={"catDelay": 1200}), []
        )
        self.assertEqual(_number_state(entity), (10, {"pending_confirmation": True}))
        self.assertEqual(entity.device.configuration.cat_delay, 1200)
        _replace_and_notify(
            coordinator, make_device(configuration={"catDelay": 1800}), []
        )
        self.assertEqual(entity.native_value, 10)
        _replace_and_notify(
            coordinator, make_device(configuration={"catDelay": 600}), []
        )
        self.assertEqual(_number_state(entity), (10, None))
        self.assertEqual(coordinator.client.methods.count("get_devices"), 2)

    async def test_registered_select_follows_only_after_confirmation(self) -> None:
        import tests.unit_cases.test_settings_controls as controls

        coordinator = controls._Coordinator(make_device())
        entity = await _registered(coordinator, "select", "activation_mode")
        await entity.async_select_option("time")
        manual = make_device(configuration={"mode": 0, "manual": 1, "volumeLevel": 7})
        _replace_and_notify(coordinator, manual, [])
        self.assertEqual(activation_label(entity.device), "manual")
        self.assertEqual(entity.current_option, "time")
        self.assertEqual(entity.extra_state_attributes, {"pending_confirmation": True})
        confirmed = make_device(configuration={"mode": 1, "manual": 0, "volumeLevel": 7})
        _replace_and_notify(coordinator, confirmed, [])
        self.assertEqual(entity.current_option, "time")
        self.assertIsNone(entity.extra_state_attributes)
        _replace_and_notify(coordinator, manual, [])
        self.assertEqual(entity.current_option, "manual")
        self.assertIsNone(entity.extra_state_attributes)
