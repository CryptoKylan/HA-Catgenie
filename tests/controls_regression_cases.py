"""Offline synthetic controls cases using real HA and pinned Pydantic models."""
import asyncio
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

if dependency := os.environ.get("CATGENIE_TEST_DEPENDENCY"):
    sys.path.insert(0, dependency)
SOURCE = Path(os.environ.get("CATGENIE_CONTROLS_SOURCE", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(SOURCE))
from catgenie import CatGenieAPIError
from homeassistant.exceptions import HomeAssistantError
from custom_components.catgenie import button, dnd_actions, entity, number, schedule_actions, select, services, switch
from custom_components.catgenie.operation_post import OperationNotSent
from custom_components.catgenie.configuration import SettingsWriteRefused
from custom_components.catgenie.operation_state import TolerantDevice

MID = "SYNTH-CONTROLS"


def device(mid=MID, config=None, online=True):
    data = dict(manufacturerId=mid, name="Synthetic", macAddress="02:00:00:00:00:01",
                hwRevision="X", fwVersion="8.6.0", reportedStatus="Connected" if online else "Disconnected")
    if config is not None:
        data["configuration"] = config
    return TolerantDevice.model_validate(data)


def coordinator(client, devices):
    return SimpleNamespace(client=client, data={d.manufacturer_id: d for d in devices},
                           last_update_success=True, async_request_refresh=AsyncMock())


class Controls(unittest.IsolatedAsyncioTestCase):
    async def race(self, dnd_first):
        cfg = dict(dndFrom="", dndTo="", catDelay=600)
        first_read = asyncio.Event()
        release = asyncio.Event()
        second_started = asyncio.Event()
        reads = []
        puts = []

        async def get():
            snapshot = device(config=dict(cfg))
            reads.append(snapshot)
            first_read.set()
            await release.wait()
            return [snapshot]

        async def put(mid, **payload):
            puts.append(payload)
            cfg.update(payload)

        coord = coordinator(SimpleNamespace(get_devices=get, update_configuration=put), [device(config=cfg)])
        num = number.CatGenieNumber(coord, MID, number.NUMBERS[2])
        data = dict(device_id="synthetic", enabled=True, start_time="22:00:00", end_time="06:00:00", timezone="UTC", reference_date="2026-11-01")
        # Warm separately: executor scheduling is not a race ordering primitive.
        retained_zone = await dnd_actions._warm_dnd_zone(data)
        async def dnd():
            return await dnd_actions.async_apply_dnd(None, data)
        async def delay():
            return await num.async_set_native_value(15)
        funcs = (dnd, delay) if dnd_first else (delay, dnd)
        async def second():
            second_started.set()
            return await funcs[1]()
        with patch.object(dnd_actions, "resolve_target", return_value=dnd_actions.ResolvedTarget(coord, MID, coord.data[MID], "entry")), patch.object(dnd_actions, "_warm_dnd_zone", AsyncMock(return_value=retained_zone)):
            first = asyncio.create_task(funcs[0]())
            await asyncio.wait_for(first_read.wait(), 3)
            other = asyncio.create_task(second())
            await second_started.wait()
            # The event wakes this task after second runs to its first await.
            # Hold the first GET until the second has entered. Base captures
            # two old snapshots; repaired code waits on the same-device lock.
            release.set()
            await asyncio.wait_for(asyncio.gather(first, other), 5)
        print(json.dumps(dict(probe="dnd_first" if dnd_first else "delay_first", final=cfg, puts=puts)))
        self.assertEqual(cfg, dict(dndFrom="22:00:00", dndTo="06:00:00", catDelay=900), puts)
        self.assertEqual(len(reads), 2)
        self.assertEqual(len(puts), 2)

    async def test_race_delay_first(self):
        await self.race(False)

    async def test_race_dnd_first(self):
        await self.race(True)

    async def test_error_redaction_and_local_refusal(self):
        async def fail(exc):
            raise exc
        coord = coordinator(None, [])
        for exc in (CatGenieAPIError("POST device/management/SECRET-ID/operation status=500"), RuntimeError("SECRET-ID")):
            with self.assertRaises(HomeAssistantError) as caught:
                await entity.async_run_command(coord, fail(exc))
            self.assertNotIn("SECRET-ID", str(caught.exception))
            self.assertNotIn("device/management", str(caught.exception))
    async def test_local_refusal_is_not_connectivity_failure(self):
        async def fail(exc):
            raise exc
        coord = coordinator(None, [])
        for exc in (OperationNotSent("Pinned writer missing; pause was not sent."), SettingsWriteRefused("incomplete")):
            with self.assertRaises(HomeAssistantError) as caught:
                await entity.async_run_command(coord, fail(exc))
            self.assertNotIn("Could not reach", str(caught.exception))
            self.assertRegex(str(caught.exception), "not sent|not changed")

    async def test_offline_controls_never_send(self):
        client = SimpleNamespace(start_cleaning=AsyncMock(), stop_cleaning=AsyncMock(), set_child_lock=AsyncMock(), set_extra_dry=AsyncMock(), set_extra_wash=AsyncMock(), set_extra_shake=AsyncMock())
        coord = coordinator(client, [device(config={}, online=False)])
        for desc in button.BUTTONS[:2]:
            obj = button.CatGenieButton(coord, MID, desc)
            self.assertFalse(obj.available)
            with self.assertRaises(HomeAssistantError):
                await obj.async_press()
        for desc in switch.SWITCHES:
            obj = switch.CatGenieSwitch(coord, MID, desc)
            self.assertFalse(obj.available)
            with self.assertRaises(HomeAssistantError):
                await obj.async_turn_on()
        for method in vars(client).values():
            method.assert_not_awaited()

    async def test_switch_explicit_provenance(self):
        for cfg in (None, {}, {"binaryElements": {}}):
            coord = coordinator(None, [device(config=cfg)])
            for desc in switch.SWITCHES:
                self.assertIsNone(switch.CatGenieSwitch(coord, MID, desc).is_on, (cfg, desc.key))
        cfg = dict(childLock=1, extraDry=True, binaryElements=dict(EXTRA_WASH=False, EXTRA_SHAKE=True))
        coord = coordinator(None, [device(config=cfg)])
        self.assertEqual([switch.CatGenieSwitch(coord, MID, desc).is_on for desc in switch.SWITCHES], [True, True, False, True])

    async def test_schedule_authorizes_before_any_preparation(self):
        call = SimpleNamespace(hass=None, data=dict(device_id="synthetic", times=[], zone="Not/AZone"))
        with patch("custom_components.catgenie.action_permissions.async_check_device_control", AsyncMock(side_effect=HomeAssistantError("Unauthorized"))) as auth, patch.object(schedule_actions, "async_iana_zones", AsyncMock()) as zones, patch.object(schedule_actions, "_prepare") as prepare:
            with self.assertRaisesRegex(HomeAssistantError, "Unauthorized"):
                await schedule_actions.async_handle_set_schedule(call, AsyncMock())
            auth.assert_awaited_once_with(call, "synthetic")
            zones.assert_not_awaited()
            prepare.assert_not_called()

    async def test_optional_null_schema(self):
        parsed = services.build_registered_schema()(dict(device_id="synthetic", enabled=False, start_time=None, end_time=None, timezone=None, reference_date=None))
        self.assertFalse(dnd_actions.validate_call(parsed).enabled)

    async def test_dnd_miss_cache_is_bounded(self):
        dnd_actions._ZONE_MISSES.clear()
        with patch.object(dnd_actions, "_construct_zone", return_value=None):
            for index in range(300):
                await dnd_actions._warm_dnd_zone({"timezone": f"Invalid/Zone{index}"})
        self.assertLessEqual(len(dnd_actions._ZONE_MISSES), 128)
        dnd_actions._ZONE_MISSES.clear()

    async def test_all_configuration_writers_share_the_coordinator_device_lock(self):
        from custom_components.catgenie.configuration_lock import configuration_lock
        cfg = dict(dndFrom="", dndTo="", catDelay=600, mode=0, manual=0,
                   volumeLevel=4, autoLock=300, childLock=0, extraDry=False, schedule=[])
        dev = device(config=cfg)
        client = SimpleNamespace(get_devices=AsyncMock(return_value=[dev]), update_configuration=AsyncMock(),
                                 set_child_lock=AsyncMock(), set_extra_dry=AsyncMock(), set_extra_wash=AsyncMock(), set_extra_shake=AsyncMock())
        coord = coordinator(client, [dev])
        entry = SimpleNamespace(id="synthetic", manufacturer="PetNovations", identifiers={("catgenie", MID)})
        async def resolve(did):
            return coord, entry
        operations = [lambda desc=desc: number.CatGenieNumber(coord, MID, desc).async_set_native_value(10 if desc.key != "volume" else 4) for desc in number.NUMBERS]
        operations += [lambda: select.CatGenieSelect(coord, MID, select.SELECTS[0]).async_select_option("manual")]
        operations += [lambda desc=desc: switch.CatGenieSwitch(coord, MID, desc).async_turn_on() for desc in switch.SWITCHES]
        call = SimpleNamespace(hass=None, data=dict(device_id="synthetic", times=[dict(time="07:30:00")], zone="UTC", reference_date="2026-11-01"))
        operations += [lambda: schedule_actions.async_handle_set_schedule(call, resolve)]
        operations += [lambda: dnd_actions.async_apply_dnd(None, dict(device_id="synthetic", enabled=False))]
        await schedule_actions.async_iana_zones(None)
        lock = configuration_lock(coord, MID)
        retained_zone = await schedule_actions._warm_schedule_zone(call.data)
        with patch.object(dnd_actions, "resolve_target", return_value=dnd_actions.ResolvedTarget(coord, MID, dev, "entry")), patch.object(schedule_actions, "_warm_schedule_zone", AsyncMock(return_value=retained_zone)):
            for operation in operations:
                async with lock:
                    started = asyncio.Event()
                    async def invoke():
                        started.set()
                        return await operation()
                    task = asyncio.create_task(invoke())
                    await started.wait()
                    self.assertFalse(task.done())
                    for method in vars(client).values():
                        method.assert_not_awaited()
                await asyncio.wait_for(task, 3)
                self.assertFalse(lock.locked())
                for method in vars(client).values():
                    method.reset_mock()

    async def test_other_device_can_write_while_first_device_read_is_blocked(self):
        read_entered = asyncio.Event()
        release = asyncio.Event()
        dev = device(config=dict(dndFrom="", dndTo="", catDelay=600))
        other = device("SYNTH-OTHER", config=dict(volumeLevel=4))
        async def get():
            read_entered.set()
            await release.wait()
            return [dev, other]
        client = SimpleNamespace(get_devices=get, update_configuration=AsyncMock())
        coord = coordinator(client, [dev, other])
        delay = number.CatGenieNumber(coord, MID, number.NUMBERS[2])
        volume = number.CatGenieNumber(coord, "SYNTH-OTHER", number.NUMBERS[0])
        task = asyncio.create_task(delay.async_set_native_value(15))
        await read_entered.wait()
        try:
            await asyncio.wait_for(volume.async_set_native_value(5), 3)
            client.update_configuration.assert_awaited_once_with("SYNTH-OTHER", volumeLevel=5)
        finally:
            release.set()
            await asyncio.wait_for(task, 3)

    async def test_failure_and_cancellation_release_transaction_at_each_io_stage(self):
        from custom_components.catgenie.configuration_lock import configuration_lock
        for stage in ("get_devices", "update_configuration", "refresh"):
            for cancel in (False, True):
                with self.subTest(stage=stage, cancel=cancel):
                    dev = device(config=dict(dndFrom="", dndTo="", catDelay=600, volumeLevel=4))
                    client = SimpleNamespace(get_devices=AsyncMock(return_value=[dev]), update_configuration=AsyncMock())
                    coord = coordinator(client, [dev])
                    entered = asyncio.Event()
                    async def blocked(*args, **kwargs):
                        entered.set()
                        if not cancel:
                            raise RuntimeError("synthetic failure")
                        await asyncio.Event().wait()
                    if stage == "refresh":
                        coord.async_request_refresh = blocked
                    else:
                        setattr(client, stage, blocked)
                    obj = number.CatGenieNumber(coord, MID, number.NUMBERS[2])
                    task = asyncio.create_task(obj.async_set_native_value(15))
                    await asyncio.wait_for(entered.wait(), 3)
                    if cancel:
                        task.cancel()
                    with self.assertRaises(asyncio.CancelledError if cancel else (HomeAssistantError, RuntimeError)):
                        await task
                    self.assertFalse(configuration_lock(coord, MID).locked())
                    client.get_devices = AsyncMock(return_value=[dev])
                    client.update_configuration = AsyncMock()
                    coord.async_request_refresh = AsyncMock()
                    # Another entity must be able to acquire after failure.
                    await asyncio.wait_for(number.CatGenieNumber(coord, MID, number.NUMBERS[0]).async_set_native_value(5), 3)

    async def test_real_ha_metadata_and_translated_captions(self):
        import json
        import yaml
        from homeassistant.helpers import service as hs, selector
        root = SOURCE / "custom_components/catgenie"
        raw = yaml.safe_load((root / "services.yaml").read_text())
        hs._SERVICES_SCHEMA(raw)
        translations = json.loads((root / "translations/en.json").read_text())["services"]
        self.assertEqual(set(raw), set(translations))
        for name, spec in raw.items():
            self.assertEqual(" ".join(spec["description"].split()), " ".join(translations[name]["description"].split()))
            self.assertEqual(set(spec["fields"]), set(translations[name]["fields"]))
            for field in spec["fields"].values():
                selector.validate_selector(field["selector"])


if __name__ == "__main__":
    unittest.main()
