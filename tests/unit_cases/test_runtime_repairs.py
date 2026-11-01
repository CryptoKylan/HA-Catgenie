"""Isolate runtime regressions from the legacy global HA import seams."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


class RealHARuntimeTests(unittest.TestCase):
    def test_runtime_with_real_ha(self):
        from tests.process_harness import require_dependencies
        require_dependencies(self, "homeassistant.core", "catgenie")
        result = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve().parents[1].joinpath("runtime_regression_cases.py"))],
            capture_output=True, text=True, env=os.environ.copy(), timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
