"""Synthetic data, real HA/Pydantic, fake HTTP only; no device actuation."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import io
import logging
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if dependency := os.environ.get("CATGENIE_TEST_DEPENDENCY"):
    sys.path.insert(0, dependency)

from curl_cffi.requests import AsyncSession
from homeassistant.components.sensor import SensorEntity
from custom_components.catgenie.client import HomeAssistantCatGenieClient
from custom_components.catgenie.operation_state import TolerantDevice, operation_state_value, operation_error_label
from custom_components.catgenie.operation_status import operation_progress_value
from custom_components.catgenie import history as h
from custom_components.catgenie.activity import ACTIVITY_SENSORS, CatGenieActivitySensor, activity_filter
from custom_components.catgenie.read_sensors import READ_SENSORS, CatGenieReadSensor
from custom_components.catgenie.read_information import ReadSnapshot, FeedParse, NotesResult
from catgenie import CatGenieAPIError
from PIL import Image

MARK = "SYNTHETIC-PRIVATE-INPUT"


def wire(identity="synthetic-unit"):
    return {"manufacturerId": identity, "name": "Synthetic", "macAddress": "00:11:22:AA:BB:CC",
            "hwRevision": "1", "fwVersion": "1", "reportedStatus": "connected",
            "operationStatus": {"state": 0, "progress": 255}, "activeErrors": []}


class DataCases(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        network = patch.object(AsyncSession, "request", side_effect=AssertionError("network forbidden"))
        network.start()
        self.addCleanup(network.stop)

    async def poll(self, payload):
        # Exercise the real adapter get_devices, with only HTTP replaced.
        client = HomeAssistantCatGenieClient.__new__(HomeAssistantCatGenieClient)
        client._request = AsyncMock(return_value=deepcopy(payload))
        result = await client.get_devices()
        client._request.assert_awaited_once()
        self.assertEqual(client._request.call_args.args[0], "GET")
        return result

    async def test_one_invalid_device_does_not_remove_other_valid_device(self):
        variants = []
        for key, value in (("progress", None), ("progress", 42.5), ("error", None)):
            invalid = wire(MARK)
            invalid["operationStatus"][key] = value
            variants.append(invalid)
        invalid = wire(MARK)
        del invalid["operationStatus"]["progress"]
        variants.append(invalid)
        invalid = wire(MARK)
        invalid["reportedStatus"] = None
        variants.append(invalid)
        invalid = wire(MARK)
        del invalid["manufacturerId"]
        variants.append(invalid)
        for invalid in variants:
            for online in ("connected", "disconnected"):
                good = wire()
                good["reportedStatus"] = online
                with self.subTest(invalid=variants.index(invalid), online=online):
                    with self.assertLogs("custom_components.catgenie.client", level="WARNING") as captured:
                        devices = await self.poll({"thingList": [good, invalid]})
                    self.assertEqual([d.manufacturer_id for d in devices], ["synthetic-unit"])
                    self.assertEqual(devices[0].is_online, online == "connected")
                    self.assertEqual(operation_progress_value(devices[0]), 0 if online == "connected" else None)
                    self.assertNotIn(MARK, "\n".join(captured.output))
                    self.assertNotIn("progress", "\n".join(captured.output))

    async def test_invalid_envelope_all_invalid_and_true_empty(self):
        self.assertEqual(await self.poll({"thingList": []}), [])
        for payload in (None, [], {}, {"thingList": None}, {"thingList": {}},
                        {"thingList": [None]}, {"thingList": [wire() | {"reportedStatus": None}]}):
            with self.subTest(payload=type(payload).__name__):
                with self.assertRaises(CatGenieAPIError) as caught:
                    await self.poll(payload)
                self.assertNotIn(MARK, str(caught.exception))

    async def test_paused_disconnection_is_not_a_new_fault(self):
        report = wire()
        report.update(reportedStatus="disconnected", operationStatus={"state": 2, "progress": 40})
        device = TolerantDevice.model_validate(report)
        self.assertIsNone(operation_state_value(device))
        self.assertIsNone(operation_error_label(device))
        self.assertEqual(operation_progress_value(device), 40)  # as-reported, not online health
        report["activeErrors"] = [2]
        device = TolerantDevice.model_validate(report)
        self.assertEqual(operation_state_value(device), "error")
        self.assertEqual(operation_error_label(device), "Water fill issue")
        report["activeErrors"] = []
        report["reportedStatus"] = "connected"
        self.assertEqual(operation_state_value(TolerantDevice.model_validate(report)), "paused")

    def activity(self, records, **extra):
        tz = ZoneInfo("America/New_York")
        now = datetime(2026, 11, 1, 12, tzinfo=tz)
        self.assertEqual(now.utcoffset(), timedelta(hours=-5))
        start, end = h.window_bounds(now, tz)
        account = h.parse_account_history({"visitResponses": records, "flushResponses": [], **extra},
                                         window_start=start, window_end=end, tz=tz)
        return account.for_device(activity_filter(TolerantDevice.model_validate(wire())))

    def visit(self, stamp, mac="00:11:22:AA:BB:CC", serial=None):
        return {"fields": {"rtcStart": stamp, "deviceId": mac, "serialNumber": serial, "durationSeconds": 30}}

    async def test_old_future_only_unknown_and_dst_replay(self):
        for stamp in ("2026-10-01T10:00:00-04:00", "2026-11-01T12:05:00-05:00", "2026-11-02T14:00:00-05:00"):
            with self.subTest(stamp=stamp):
                result = self.activity([self.visit(stamp)])
                self.assertIsNone(result.visits_today)
                self.assertEqual(result.today_basis, "uncovered")
                self.assertEqual(result.coverage, "partial")
                self.assertEqual(result.outside_window, 1)
        # Original H3 was before noon EST; no window parser change is warranted.
        result = self.activity([self.visit("2026-11-01T12:05:00-04:00")])
        self.assertEqual(result.visits_today, 1)
        self.assertEqual(result.outside_window, 0)
        self.assertEqual(self.activity([]).visits_today, 0)
        self.assertIsNone(self.activity([self.visit("2026-11-01T10:00:00-05:00", None)]).visits_today)

    async def test_canonical_macs_full_count_and_conflicts(self):
        spellings = ("00:11:22:AA:BB:CC", "00:11:22:aa:bb:cc", "00-11-22-AA-BB-CC", "001122aabbcc", "0011.22aa.bbcc")
        result = self.activity([self.visit(f"2026-11-01T{index+6:02d}:00:00-05:00", mac)
                                for index, mac in enumerate(spellings)])
        self.assertEqual(result.visits_today, len(spellings))
        self.assertEqual(result.today_basis, "counted")
        conflict = self.activity([self.visit("2026-11-01T10:00:00-05:00", spellings[1], "different-serial")])
        self.assertIsNone(conflict.visits_today)
        self.assertEqual(conflict.conflict_attribution, 1)
        # Manufacturer IDs stay exact, even if they look like MACs.
        filt = h.DeviceFilter(frozenset(), frozenset({spellings[0]}))
        self.assertEqual(h._classify(None, spellings[1], filt), "other_device")
        self.assertEqual(h._classify("not-A-MAC", None, h.DeviceFilter(frozenset({"not-a-mac"}), frozenset())), "other_device")

    async def test_real_ha_recorder_contract_keeps_full_notes_in_ui(self):
        from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
        # Real Entity.capability_attributes is what publishes recorder exclusions.
        device = TolerantDevice.model_validate(wire())
        snapshot = ReadSnapshot(FeedParse(0, "list", 0, 0, 0, 0, 0, ()),
                                (NotesResult("1", "x" * 20000, None),), ("1",))
        reader = SimpleNamespace(data=snapshot, last_update_success=True)
        devices = SimpleNamespace(data={device.manufacturer_id: device})
        entity = CatGenieReadSensor(reader, devices, device.manufacturer_id,
                                  next(d for d in READ_SENSORS if d.key == "firmware_release_notes"))
        self.assertIsInstance(entity, SensorEntity)
        self.assertEqual(len(entity.extra_state_attributes["installed_notes"]), 20000)
        excluded = entity._Entity__combined_unrecorded_attributes
        self.assertTrue({"installed_notes", "announced_notes"} <= excluded)
        entity = CatGenieActivitySensor(SimpleNamespace(data=None), devices, device.manufacturer_id, ACTIVITY_SENSORS[0])
        self.assertTrue({"visit_diary", "flush_diary"} <= entity._Entity__combined_unrecorded_attributes)

    async def test_missing_measurements_and_lifetime_counter(self):
        from custom_components.catgenie.sensor import SENSORS
        sensors = {s.key: s for s in SENSORS}
        keys = ('total_cycles', 'cartridge_remaining', 'cat_activation_delay',
                'panel_lock_delay', 'cat_sensitivity', 'volume_level',
                'cleaning_mode', 'scheduled_cycles')
        for config in (None, {}, {'activation': None}):
            report = wire()
            if config is not None:
                report['configuration'] = config
            device = (await self.poll({'thingList': [report]}))[0]
            for key in keys:
                with self.subTest(config=config, key=key):
                    self.assertIsNone(sensors[key].value_fn(device))
        values = []
        activation = {'count': 812, 'date': '2026-01-01T00:00:00Z', 'state': 0}
        for config in ({'activation': activation}, {}, {'activation': activation}):
            device = TolerantDevice.model_validate(wire() | {'configuration': config})
            values.append(sensors['total_cycles'].value_fn(device))
        self.assertEqual(values, [812, None, 812])

    async def test_wire_numeric_provenance_and_supported_values(self):
        from custom_components.catgenie.sensor import SENSORS
        sensors = {s.key: s for s in SENSORS}
        fields = {'catDelay': ('cat_activation_delay', 600),
                  'autoLock': ('panel_lock_delay', 0),
                  'catSense': ('cat_sensitivity', 0),
                  'volumeLevel': ('volume_level', 7)}
        for field, (key, valid) in fields.items():
            for raw in (False, str(valid), valid):
                report = wire() | {'configuration': {field: raw}}
                device = (await self.poll({'thingList': [report]}))[0]
                with self.subTest(field=field, raw=raw):
                    self.assertEqual(sensors[key].value_fn(device), valid if type(raw) is int else None)
        for field, key, location in (('count', 'total_cycles', 'activation'),
                                     ('remainingSaniSolution', 'cartridge_remaining', 'device')):
            for raw in (False, '0', 0, 812):
                report = wire()
                if location == 'device':
                    report[field] = raw
                else:
                    report['configuration'] = {'activation': {field: raw, 'date': '2026-01-01T00:00:00Z', 'state': 0}}
                device = (await self.poll({'thingList': [report]}))[0]
                self.assertEqual(sensors[key].value_fn(device), raw if type(raw) is int else None)
        for field, key, raw in (('catDelay', 'cat_activation_delay', 0),
                                ('autoLock', 'panel_lock_delay', 301),
                                ('volumeLevel', 'volume_level', 0)):
            device = TolerantDevice.model_validate(wire() | {'configuration': {field: raw}})
            self.assertIsNone(sensors[key].value_fn(device))
        for raw, expected in (([], 0), ([{'enabled': False}], 0),
                              ([{'enabled': True}], 1), ([{'enabled': 'false'}], None),
                              ([{}], None)):
            device = (await self.poll({'thingList': [wire() | {'configuration': {'schedule': raw}}]}))[0]
            self.assertEqual(sensors['scheduled_cycles'].value_fn(device), expected)
        # None remains a vendor validation failure for non-nullable fields;
        # quarantine is intentional, not permission to broaden installed models.
        for field in fields:
            good = wire('good')
            bad = wire('bad') | {'configuration': {field: None}}
            self.assertEqual([d.manufacturer_id for d in await self.poll({'thingList': [good, bad]})], ['good'])

    async def test_shared_strict_activation_and_capacity_wire_contract(self):
        from custom_components.catgenie.sensor import SENSORS
        from custom_components.catgenie.cartridge import cartridge_capacity, cartridge_capacity_attributes
        cleaning = next(s for s in SENSORS if s.key == 'cleaning_mode')
        for mode in (0, 1, False, '1', None):
            for manual in (0, 1, False, '1', 2, None):
                report = wire() | {'tagType': 1, 'configuration': {'mode': mode, 'manual': manual}}
                if mode is None:
                    del report['configuration']['mode']
                device = (await self.poll({'thingList': [report]}))[0]
                expected = None
                if type(mode) is int and type(manual) is int and manual in (0, 1):
                    expected = 'manual' if manual else ('cat' if mode == 0 else 'time')
                with self.subTest(mode=mode, manual=manual):
                    self.assertEqual(cleaning.value_fn(device), expected)
                    self.assertEqual(cartridge_capacity_attributes(device).get('cleaning_mode'), expected)
                    self.assertEqual(cartridge_capacity(device), None if expected is None else (240 if expected == 'cat' else 120))
        device = TolerantDevice.model_validate(wire() | {'configuration': {'mode': 0}})
        self.assertIsNone(cleaning.value_fn(device))
        for tag in (0, 3):
            device = TolerantDevice.model_validate(wire() | {'tagType': tag, 'totalSaniSolution': 240,
                'configuration': {'mode': 0, 'manual': 0}})
            self.assertIsNone(cartridge_capacity(device))

    async def test_polled_numeric_controls_share_sensor_provenance_and_refuse_writes(self):
        from custom_components.catgenie.sensor import SENSORS
        from custom_components.catgenie.number import NUMBERS, CatGenieNumber
        from custom_components.catgenie.select import SELECTS, CatGenieSelect
        from custom_components.catgenie.configuration import activation_payload, SettingsWriteRefused
        from homeassistant.exceptions import HomeAssistantError
        sensors = {s.key: s for s in SENSORS}
        for field, key, number, requested in (
            ('volumeLevel', 'volume_level', 'volume', 7),
            ('autoLock', 'panel_lock_delay', 'auto_lock_timeout', 5),
            ('catDelay', 'cat_activation_delay', 'cat_activation_delay', 10),
        ):
            for raw in (True, False, '7', '600', '1', None):
                config = {'dndFrom': '', 'dndTo': ''}
                if raw is not None:  # Missing is distinct from invalid nullable models.
                    config[field] = raw
                device = (await self.poll({'thingList': [wire() | {'configuration': config}]}))[0]
                client = SimpleNamespace(update_configuration=AsyncMock(), get_devices=AsyncMock(return_value=[device]))
                coordinator = SimpleNamespace(data={device.manufacturer_id: device}, client=client,
                                              last_update_success=True, async_request_refresh=AsyncMock())
                entity = CatGenieNumber(coordinator, device.manufacturer_id,
                                       next(d for d in NUMBERS if d.key == number))
                with self.subTest(field=field, raw=raw):
                    self.assertIsNone(sensors[key].value_fn(device))
                    self.assertIsNone(entity.native_value)
                    with self.assertRaises(HomeAssistantError):
                        await entity.async_set_native_value(requested)
                    client.update_configuration.assert_not_awaited()
                    coordinator.async_request_refresh.assert_not_awaited()
        for mode in (False, True, '1', None, 0, 1):
            for manual in (0, 1):
                config = {'manual': manual}
                if mode is not None:
                    config['mode'] = mode
                device = (await self.poll({'thingList': [wire() | {'configuration': config}]}))[0]
                client = SimpleNamespace(update_configuration=AsyncMock())
                coordinator = SimpleNamespace(data={device.manufacturer_id: device}, client=client,
                                              last_update_success=True, async_request_refresh=AsyncMock())
                entity = CatGenieSelect(coordinator, device.manufacturer_id, SELECTS[0])
                with self.subTest(mode=mode, manual=manual):
                    if type(mode) is not int:
                        self.assertIsNone(entity.current_option)
                        self.assertIsNone(sensors['cleaning_mode'].value_fn(device))
                        with self.assertRaises(SettingsWriteRefused):
                            activation_payload(device, 'manual')
                        with self.assertRaises(HomeAssistantError):
                            await entity.async_select_option('manual')
                        client.update_configuration.assert_not_awaited()
                    else:
                        expected = 'manual' if manual else ('cat' if mode == 0 else 'time')
                        self.assertEqual(entity.current_option, expected)
                        self.assertEqual(sensors['cleaning_mode'].value_fn(device), expected)
                        self.assertEqual(activation_payload(device, 'manual'), {'mode': mode, 'manual': 1})
                        await entity.async_select_option('manual')
                        client.update_configuration.assert_awaited_once_with(device.manufacturer_id, mode=mode, manual=1)

    async def test_polled_valid_numeric_controls_keep_zero_and_positive_values(self):
        from custom_components.catgenie.configuration import (
            stored_volume, display_volume, display_auto_lock_minutes, display_cat_delay_minutes,
            volume_payload, auto_lock_payload, cat_delay_payload,
        )
        from custom_components.catgenie.sensor import SENSORS
        sensors = {s.key: s for s in SENSORS}
        for volume, lock, delay in ((7, 0, 600), (1, 300, 300), (0, 1800, 1800)):
            config = {'volumeLevel': volume, 'autoLock': lock, 'catDelay': delay,
                      'dndFrom': '', 'dndTo': '', 'extraDry': False}
            device = (await self.poll({'thingList': [wire() | {'configuration': config}]}))[0]
            self.assertEqual(stored_volume(device), volume)
            self.assertEqual(display_volume(device), volume or None)
            self.assertEqual(sensors['volume_level'].value_fn(device), volume or None)
            self.assertEqual(display_auto_lock_minutes(device), lock // 60)
            self.assertEqual(display_cat_delay_minutes(device), delay // 60)
            self.assertEqual(sensors['panel_lock_delay'].value_fn(device), lock)
            self.assertEqual(sensors['cat_activation_delay'].value_fn(device), delay)
            self.assertEqual(volume_payload(device, 7), {'volumeLevel': 7})
            self.assertEqual(auto_lock_payload(device, 0), {'autoLock': 0})
            self.assertEqual(cat_delay_payload(device, 10), {'dndFrom': '', 'dndTo': '', 'catDelay': 600})
            from custom_components.catgenie.switch import CatGenieSwitch, SWITCHES
            coordinator = SimpleNamespace(data={device.manufacturer_id: device})
            switch = CatGenieSwitch(coordinator, device.manufacturer_id, next(d for d in SWITCHES if d.key == 'extra_dry'))
            self.assertIs(switch.is_on, False)

    async def test_private_measurement_provenance_is_bounded_and_not_serialized(self):
        report = wire() | {'remainingSaniSolution': 0, 'tagType': 1,
            'configuration': {'mode': 0, 'manual': 0, 'volumeLevel': '7',
                              'privateUnrelated': MARK, 'schedule': ['06:00:00']}}
        device = (await self.poll({'thingList': [report]}))[0]
        self.assertIn('configuration', device.model_fields_set)
        self.assertIn('volume_level', device.configuration.model_fields_set)
        self.assertNotIn('auto_lock', device.configuration.model_fields_set)
        raw = device._reported_measurements
        self.assertEqual(raw['volume_level'], '7')
        self.assertNotIn(MARK, repr(raw))
        self.assertNotIn('_reported_measurements', device.model_dump())
        self.assertNotIn('_reported_measurements', device.model_dump_json())
        report['configuration']['volumeLevel'] = 1
        self.assertEqual(raw['volume_level'], '7')
        from custom_components.catgenie.reported_config import reported_schedule_count
        self.assertEqual(reported_schedule_count(device), 1)

    async def test_logo_really_is_png(self):
        with Image.open(ROOT / "custom_components/catgenie/brand/logo.png") as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (256, 256))


if __name__ == "__main__":
    unittest.main(verbosity=2)
