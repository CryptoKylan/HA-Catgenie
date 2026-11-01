"""Display-only distinction between reported settings and editable controls."""
import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / 'custom_components/catgenie'


class SettingsLabelTests(unittest.TestCase):
    def test_reported_sensor_labels_do_not_look_like_controls(self):
        entities = json.loads((ROOT / 'translations/en.json').read_text())['entity']
        for key in ('cleaning_mode', 'cat_activation_delay', 'panel_lock_delay',
                    'cat_sensitivity', 'volume_level', 'reported_dnd'):
            with self.subTest(key=key):
                self.assertTrue(entities['sensor'][key]['name'].startswith('Reported '))
        self.assertEqual(entities['number']['volume']['name'], 'Volume')
        self.assertEqual(entities['number']['auto_lock_timeout']['name'], 'Auto-lock timeout')
        self.assertEqual(entities['select']['activation_mode']['name'], 'Activation mode')

    def test_read_only_mode_sensor_is_diagnostic(self):
        tree = ast.parse((ROOT / 'sensor.py').read_text())
        matches = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                   and any(k.arg == 'key' and isinstance(k.value, ast.Constant)
                           and k.value.value == 'cleaning_mode' for k in n.keywords)]
        self.assertEqual(len(matches), 1)
        categories = [k.value for k in matches[0].keywords if k.arg == 'entity_category']
        self.assertEqual(len(categories), 1)
        self.assertEqual(ast.unparse(categories[0]), 'EntityCategory.DIAGNOSTIC')
