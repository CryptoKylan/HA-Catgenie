"""Offline harness policy checks; these do not claim real-HA behavior."""
import os
import io
import json
import subprocess
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from tests import process_harness
from tests.process_harness import MARKER, dependency_env, require_dependencies
from tests.fixtures import schema_stub as schema


class HarnessPolicyTests(unittest.TestCase):
    def run_child_row(self, row, required='0'):
        module = 'tests.unit_cases.test_synthetic'
        row = dict(module=module, failures=0, errors=0, **row)
        completed = subprocess.CompletedProcess(['synthetic'], 0,
                                                MARKER + json.dumps(row) + '\n', '')
        output = io.StringIO()
        result = unittest.TestResult()
        with patch.dict(os.environ, {'CATGENIE_REQUIRE_CONTRACTS': required}), \
             patch('tests.process_harness.require_dependencies'), \
             patch('tests.process_harness.subprocess.run', return_value=completed), \
             redirect_stdout(output):
            process_harness.ModuleProcess(module).run(result)
        return result, output.getvalue()

    def test_all_optional_child_skips_surface_with_exact_counts(self):
        result, output = self.run_child_row(dict(tests=3, skips=3))
        self.assertEqual(result.skipped[0][1], 'Child tests ran=3, skips=3')
        self.assertEqual((len(result.failures), len(result.errors)), (0, 0))
        self.assertEqual(json.loads(output.removeprefix(MARKER))['skips'], 3)

    def test_partial_optional_child_skips_fail_visibly(self):
        result, output = self.run_child_row(dict(tests=3, skips=1))
        self.assertEqual((len(result.failures), len(result.skipped), len(result.errors)), (1, 0, 0))
        self.assertIn('Partial child skips: Child tests ran=3, skips=1', result.failures[0][1])
        self.assertEqual(json.loads(output.removeprefix(MARKER))['tests'], 3)

    def test_required_child_skips_fail_even_when_child_exits_zero(self):
        for skips in (1, 3):
            result, output = self.run_child_row(dict(tests=3, skips=skips), required='1')
            self.assertEqual((len(result.failures), len(result.skipped), len(result.errors)), (1, 0, 0))
            self.assertIn(f'Required contracts skipped: Child tests ran=3, skips={skips}', result.failures[0][1])
            self.assertEqual(json.loads(output.removeprefix(MARKER))['skips'], skips)

    def test_zero_child_skips_pass_and_zero_tests_fail(self):
        result, output = self.run_child_row(dict(tests=3, skips=0), required='1')
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(result.skipped, [])
        self.assertEqual(json.loads(output.removeprefix(MARKER))['tests'], 3)
        result, _ = self.run_child_row(dict(tests=0, skips=0))
        self.assertEqual(len(result.failures), 1)

    def test_malformed_or_impossible_child_counts_fail(self):
        for row in (dict(tests=-1, skips=0), dict(tests='3', skips=0),
                    dict(tests=True, skips=0), dict(tests=3, skips=-1),
                    dict(tests=3, skips=4), dict(tests=3, skips=0.0)):
            result, _ = self.run_child_row(row)
            self.assertEqual((len(result.failures), len(result.errors)), (1, 0))

    def test_missing_optional_dependency_skips_not_type_error(self):
        with patch.dict(os.environ, {"CATGENIE_REQUIRE_CONTRACTS": "0"}):
            with self.assertRaises(unittest.SkipTest) as caught:
                require_dependencies(self, "catgenie_deliberately_missing_contract_dependency")
        self.assertIn("Contract dependency unavailable", str(caught.exception))

    def test_missing_required_dependency_fails_not_type_error(self):
        with patch.dict(os.environ, {"CATGENIE_REQUIRE_CONTRACTS": "1"}):
            with self.assertRaises(self.failureException) as caught:
                require_dependencies(self, "catgenie_deliberately_missing_contract_dependency")
        self.assertIn("Contract dependency unavailable", str(caught.exception))

    def test_declared_extracted_dependency_is_separate_path(self):
        from tests.process_harness import ROOT
        with patch.dict(os.environ, {"CATGENIE_TEST_DEPENDENCY": str(ROOT / "synthetic-dependency"),
                                     "PYTHONPATH": str(ROOT / "synthetic-existing")}):
            paths = dependency_env()["PYTHONPATH"].split(os.pathsep)
        self.assertEqual(paths, [str(ROOT), str(ROOT / "synthetic-dependency"),
                                 str(ROOT / "synthetic-existing")])

    def test_stub_extra_policy_does_not_fake_backend_authority(self):
        spec = {schema.Required("device_id"): str}
        payload = {"device_id": "synthetic", "extra": 1}
        self.assertEqual(schema.Schema(spec, extra=schema.ALLOW_EXTRA)(payload), payload)
        with self.assertRaises(schema.Invalid):
            schema.Schema(spec, extra=schema.PREVENT_EXTRA)(payload)
        self.assertIsNot(schema.Invalid, Exception)
