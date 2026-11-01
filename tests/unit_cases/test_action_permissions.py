"""Registered settings actions honor HA control permissions for their target."""
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import tests.unit_cases.test_dnd_action as h


class _Denied(Exception):
    def __init__(self, **kwargs):
        self.details = kwargs
        super().__init__('unauthorized')


class _Unknown(_Denied):
    pass


class ActionPermissionTests(unittest.TestCase):
    def setUp(self):
        h._activate_stubs()
        permissions = types.ModuleType('homeassistant.auth.permissions.const')
        permissions.POLICY_CONTROL = 'control'
        self.registry_module = types.ModuleType('homeassistant.helpers.entity_registry')
        self.registry_module.async_get = lambda hass: hass.entity_registry
        self.stack = __import__('contextlib').ExitStack()
        self.stack.enter_context(patch.dict(sys.modules, {
            'homeassistant.auth.permissions.const': permissions,
            'homeassistant.helpers.entity_registry': self.registry_module,
        }))
        self.stack.enter_context(patch.object(sys.modules['homeassistant.helpers'], 'entity_registry', self.registry_module, create=True))
        errors = sys.modules['homeassistant.exceptions']
        self.stack.enter_context(patch.object(errors, 'Unauthorized', _Denied, create=True))
        self.stack.enter_context(patch.object(errors, 'UnknownUser', _Unknown, create=True))

    def tearDown(self):
        self.stack.close()
        h._restore_stubs()

    def _call(self, service, kind, legacy=False, offline=False):
        device = h._device(configuration={'schedule': [{'time': '08:00:00', 'hour': 8, 'minute': 0}]}, **({'reportedStatus': 'disconnected'} if offline else {}))
        hass, coordinator, entry = h._bound(device, fresh=[device])
        if service == 'set_schedule':
            from custom_components.catgenie import schedule_actions
            payload = h.harness.device_payload()
            if offline:
                payload['reportedStatus'] = 'disconnected'
            device = schedule_actions.Device.model_validate(payload)
            coordinator.data = {device.manufacturer_id: device}
            coordinator.client.fresh_devices = [device]
        if legacy:
            del entry.config_entry_id
            entry.config_entries = {'entry-1'}
        lookups = []
        async def lookup(user_id):
            lookups.append(user_id)
            if kind == 'missing':
                return None
            return SimpleNamespace(is_admin=kind == 'admin', permissions=SimpleNamespace(
                check_entity=lambda entity_id, permission: kind == 'allowed' and entity_id == 'number.target_delay' and permission == 'control'))
        hass.auth = SimpleNamespace(async_get_user=lookup)
        hass.entity_registry = SimpleNamespace(entities={
            'target': SimpleNamespace(platform='catgenie', device_id=entry.id, entity_id='number.target_delay'),
            'other': SimpleNamespace(platform='catgenie', device_id='other-device', entity_id='number.other_delay'),
        })
        if kind == 'other_device_only':
            async def other_lookup(user_id):
                lookups.append(user_id)
                return SimpleNamespace(is_admin=False, permissions=SimpleNamespace(check_entity=lambda entity_id, permission: entity_id == 'number.other_delay'))
            hass.auth.async_get_user = other_lookup
        h.service_mod.async_setup_actions(hass, SimpleNamespace(entry_id='entry-1'))
        data = {'device_id': entry.id, 'enabled': False} if service == 'set_do_not_disturb' else {
            'device_id': entry.id, 'times': [{'time': '08:00:00'}], 'zone': 'UTC', 'reference_date': '2026-10-31'}
        call = SimpleNamespace(hass=hass, data=data, context=SimpleNamespace(user_id=None if kind == 'automation' else 'caller'))
        callback = hass.services.registered['catgenie'][service]['func']
        return callback, call, coordinator, lookups

    def test_registered_actions_reject_denied_unknown_and_other_device_users_before_io(self):
        for service in ('set_do_not_disturb', 'set_schedule'):
            for legacy in (False, True):
                for kind in ('denied', 'missing', 'other_device_only'):
                    with self.subTest(service=service, legacy=legacy, kind=kind):
                        callback, call, coordinator, lookups = self._call(service, kind, legacy)
                        with self.assertRaises(_Unknown if kind == 'missing' else _Denied):
                            h._run(callback(call))
                        self.assertEqual(lookups, ['caller'])
                        self.assertEqual(coordinator.client.methods, [])
                        self.assertEqual(coordinator.refreshes, 0)

    def test_registered_actions_allow_target_control_admin_and_internal_automation(self):
        for service in ('set_do_not_disturb', 'set_schedule'):
            for legacy in (False, True):
                for kind in ('allowed', 'admin', 'automation'):
                    with self.subTest(service=service, legacy=legacy, kind=kind):
                        callback, call, coordinator, lookups = self._call(service, kind, legacy)
                        h._run(callback(call))
                        self.assertEqual(coordinator.client.methods, ['get_devices', 'update_configuration'])
                        self.assertEqual(coordinator.refreshes, 1)
                        self.assertEqual(lookups, [] if kind == 'automation' else ['caller'])

    def test_cached_offline_schedule_refuses_without_io(self):
        callback, call, coordinator, _ = self._call('set_schedule', 'allowed', offline=True)
        from custom_components.catgenie.schedule_actions import ScheduleActionRefused
        with self.assertRaises(ScheduleActionRefused) as caught:
            h._run(callback(call))
        self.assertEqual(caught.exception.code, 'offline')
        self.assertEqual(coordinator.client.methods, [])
        self.assertEqual(coordinator.refreshes, 0)
