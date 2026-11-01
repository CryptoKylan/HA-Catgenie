"""Run each legacy unit world in a fresh interpreter, never in discovery's parent.

The child owns its fake frameworks until exit. This is process isolation, NOT
an assertion that legacy import seams restore every global in their own child.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MARKER = "CATGENIE_TEST_RESULT "


def dependency_env():
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (
        str(ROOT), env.get("CATGENIE_TEST_DEPENDENCY"), env.get("PYTHONPATH"))))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def require_dependencies(case, *modules):
    """Check with the SAME path/interpreter as the contract, not parent stubs."""
    result = subprocess.run(
        [sys.executable, "-B", "-c",
         "import importlib; " + "; ".join(f"importlib.import_module({m!r})" for m in modules)],
        env=dependency_env(), cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    if result.returncode:
        message = "Contract dependency unavailable: " + ", ".join(modules) + "\n" + result.stderr
        if os.environ.get("CATGENIE_REQUIRE_CONTRACTS") == "1":
            case.fail(message)
        case.skipTest(message)


class ModuleProcess(unittest.TestCase):
    def __init__(self, module):
        super().__init__("runTest")
        self.module = module

    def id(self):
        return self.module + ".fresh_process"

    def shortDescription(self):
        return self.id()

    def runTest(self):
        require_dependencies(self, "catgenie")
        result = subprocess.run(
            [sys.executable, "-B", "-m", "tests.process_harness", self.module],
            cwd=ROOT, env=dependency_env(), text=True, capture_output=True, timeout=180,
        )
        output = result.stdout + result.stderr
        rows = [json.loads(line[len(MARKER):]) for line in result.stdout.splitlines()
                if line.startswith(MARKER)]
        self.assertEqual(result.returncode, 0, output)
        self.assertEqual(len(rows), 1, output)
        row = rows[0]
        for key in ("tests", "failures", "errors", "skips"):
            self.assertIs(type(row.get(key)), int, f"Invalid child count {key}: {output}")
            self.assertGreaterEqual(row[key], 0, output)
        self.assertGreater(row["tests"], 0, output)
        self.assertLessEqual(row["failures"] + row["errors"] + row["skips"], row["tests"], output)
        print(MARKER + json.dumps(row, sort_keys=True), flush=True)
        self.assertEqual(row["failures"], 0, output)
        self.assertEqual(row["errors"], 0, output)
        if row["skips"]:
            reason = f"Child tests ran={row['tests']}, skips={row['skips']}"
            if os.environ.get("CATGENIE_REQUIRE_CONTRACTS") == "1":
                self.fail(f"Required contracts skipped: {reason}")
            if row["skips"] == row["tests"]:
                self.skipTest(reason)
            self.fail(f"Partial child skips: {reason}")


def module_suite(module):
    return unittest.TestSuite([ModuleProcess(module)])


def main():
    module = sys.argv[1]
    if not module.startswith("tests.unit_cases.test_"):
        raise SystemExit("Expected canonical tests.unit_cases.test_* module")
    suite = unittest.defaultTestLoader.loadTestsFromName(module)
    # No second bare/old canonical harness may exist in this child's world.
    settings = [n for n in sys.modules if n.split(".")[-1] == "test_settings_controls"]
    if settings and settings != ["tests.unit_cases.test_settings_controls"]:
        raise SystemExit(f"Duplicate harness names: {settings}")
    identities = []
    if settings:
        canonical = sys.modules[settings[0]]
        consumer = sys.modules[module]
        for name in ("CatGenieSelect", "CatGenieNumber", "HomeAssistantError",
                     "CatGenieException", "make_device"):
            if hasattr(consumer, name) and hasattr(canonical, name):
                if getattr(consumer, name) is not getattr(canonical, name):
                    raise SystemExit(f"Split settings harness identity: {module}.{name}")
                identities.append(name)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    row = dict(module=module, tests=result.testsRun, failures=len(result.failures),
               errors=len(result.errors), skips=len(result.skipped), settings_modules=settings,
               settings_identities=identities)
    print(MARKER + json.dumps(row, sort_keys=True), flush=True)
    return not result.wasSuccessful()


if __name__ == "__main__":
    raise SystemExit(main())
