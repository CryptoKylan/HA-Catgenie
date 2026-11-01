"""SYNTHETIC capacity regression using real dependency models and HA seams."""
import unittest

from tests.unit_cases.test_unknown_operation_state import (
    CatGenieSensor, TolerantDevice, _Coordinator, _sensor, thing,
)


class CartridgeCapacityTests(unittest.TestCase):
    def device(self, *, mode=0, manual=0, tag=1, reported=None, remaining=160):
        payload = thing('capacity', 0, progress=255)
        payload.update(configuration={'mode': mode, 'manual': manual},
                       tagType=tag, remainingSaniSolution=remaining)
        if reported is not None:
            payload['totalSaniSolution'] = reported
        return TolerantDevice.model_validate(payload)

    def entity(self, device, key='cartridge_capacity'):
        return CatGenieSensor(_Coordinator({device.manufacturer_id: device}),
                             device.manufacturer_id, _sensor(key))

    def test_synthetic_three_modes_and_round_trip(self):
        for mode, manual, remaining, capacity, label in [
            (0, 0, 160, 240, 'cat'), (0, 1, 80, 120, 'manual'),
            (1, 0, 80, 120, 'time'), (0, 0, 160, 240, 'cat'),
        ]:
            with self.subTest(mode=mode, manual=manual):
                device = self.device(mode=mode, manual=manual, remaining=remaining)
                entity = self.entity(device)
                self.assertEqual(entity.native_value, capacity)
                self.assertEqual(entity.extra_state_attributes,
                                 {'capacity_source': 'manufacturer_rating', 'cleaning_mode': label})
                self.assertEqual(self.entity(device, 'cartridge_remaining').native_value, remaining)

    def test_manual_override_wins_over_time_mode_too(self):
        device = self.device(mode=1, manual=1)
        self.assertEqual(self.entity(device).native_value, 120)
        self.assertEqual(self.entity(device).extra_state_attributes['cleaning_mode'], 'manual')

    def test_valid_reported_capacity_takes_precedence(self):
        for reported in (180, 240.0, 480):
            with self.subTest(reported=reported):
                entity = self.entity(self.device(reported=reported))
                self.assertEqual(entity.native_value, reported)
                self.assertEqual(entity.extra_state_attributes['capacity_source'], 'device_reported')

    def test_invalid_reported_capacity_uses_only_valid_rating(self):
        for reported in (0, -1, True, '240', float('nan'), float('inf'), {}, []):
            with self.subTest(reported=reported):
                entity = self.entity(self.device(reported=reported))
                self.assertEqual(entity.native_value, 240)
                self.assertEqual(entity.extra_state_attributes['capacity_source'], 'manufacturer_rating')

    def test_missing_or_nonstandard_cartridge_is_unknown(self):
        for tag in (0, 3, 99, None, '1', True, 1.0):
            with self.subTest(tag=tag):
                entity = self.entity(self.device(tag=tag))
                self.assertIsNone(entity.native_value)
                self.assertEqual(entity.extra_state_attributes['capacity_source'], 'unknown')

    def test_explicit_missing_or_maintenance_cartridge_blocks_stale_maximum(self):
        for tag in (0, 3):
            with self.subTest(tag=tag):
                self.assertIsNone(self.entity(self.device(tag=tag, reported=240)).native_value)

    def test_unsupported_cartridge_may_supply_its_own_capacity(self):
        entity = self.entity(self.device(tag=99, reported=480))
        self.assertEqual(entity.native_value, 480)
        self.assertEqual(entity.extra_state_attributes['capacity_source'], 'device_reported')

    def test_missing_mode_or_manual_flag_does_not_use_pydantic_defaults(self):
        for config in ({}, {'mode': 0}, {'manual': 0}):
            payload = thing('missing-config', 0)
            payload.update(tagType=1, configuration=config)
            entity = self.entity(TolerantDevice.model_validate(payload))
            self.assertIsNone(entity.native_value)
            self.assertEqual(entity.extra_state_attributes['capacity_source'], 'unknown')

    def test_malformed_manual_flag_is_not_a_mode(self):
        for manual in (None, '0', '1', 2, False, 0.0):
            with self.subTest(manual=manual):
                self.assertIsNone(self.entity(self.device(manual=manual)).native_value)

    def test_reported_maximum_does_not_require_mode_or_tag_fallback_inputs(self):
        payload = thing('reported-only', 0)
        payload['totalSaniSolution'] = 200
        entity = self.entity(TolerantDevice.model_validate(payload))
        self.assertEqual(entity.native_value, 200)
        self.assertEqual(entity.extra_state_attributes['capacity_source'], 'device_reported')

    def test_unknown_mode_remains_unknown(self):
        device = self.device()
        device.configuration = device.configuration.model_copy(update={'mode': 99})
        self.assertIsNone(self.entity(device).native_value)

    def test_capacity_contract_preserves_entity_identity_units_and_progress(self):
        device = self.device()
        entity = self.entity(device)
        self.assertEqual(entity._attr_unique_id, 'capacity_cartridge_capacity')
        self.assertEqual(entity.entity_description.native_unit_of_measurement, 'cycles')
        self.assertEqual(self.entity(device, 'operation_progress').native_value, 0)
        self.assertIsNone(device.operation_status.clean_progress_pct)


if __name__ == '__main__':
    unittest.main()
