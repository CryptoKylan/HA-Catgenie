"""Run controls regressions in a clean interpreter with actual HA dependencies."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


class RealHAControlsTests(unittest.TestCase):
    def test_controls_with_real_ha(self):
        from tests.process_harness import require_dependencies
        require_dependencies(self, "homeassistant.core", "catgenie")
        result = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve().parents[1].joinpath("controls_regression_cases.py"))],
            capture_output=True, text=True, env=os.environ.copy(), timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
