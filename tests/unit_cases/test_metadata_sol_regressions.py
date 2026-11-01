"""SOL regressions: shared loader cancellation and cold handler ZoneInfo I/O.

The probe uses installed Home Assistant 2026.10.4 Future semantics and an
audit hook. It does not call a live device. A coroutine-only executor fake
cannot represent the cancellation bug, so this test does not use one.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROBE = Path(__file__).resolve().parents[1].joinpath("metadata_sol_probe.py")


class MetadataSolRegressionTests(unittest.TestCase):
    def test_loader_cancellation_and_zone_lifetime(self) -> None:
        from tests.process_harness import require_dependencies
        require_dependencies(self, "homeassistant.core", "catgenie")
        pythonpath = str(ROOT)
        dependency = os.environ.get("CATGENIE_TEST_DEPENDENCY")
        if dependency:
            pythonpath = dependency + os.pathsep + pythonpath
        completed = subprocess.run(
            [sys.executable, "-B", str(PROBE)],
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": pythonpath, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        concurrent = payload["concurrent"]
        self.assertEqual(concurrent["executor_return_type"], "Future")
        self.assertFalse(concurrent["coroutine_fake"])
        self.assertTrue(concurrent["caller_cancelled"])
        self.assertTrue(concurrent["other_entry_loaded"])
        self.assertFalse(concurrent["shared_cancelled"])
        self.assertTrue(concurrent["reference_preserved_while_running"])
        self.assertTrue(concurrent["reload_loaded"])
        queued = payload["queued_job"]
        self.assertTrue(queued["cancel_returned"])
        self.assertEqual(queued["waiter"], "CancelledError")
        self.assertTrue(queued["other_entry_loaded"])
        self.assertTrue(payload["failure_recovery"]["failed_future_cleared"])
        self.assertTrue(payload["failure_recovery"]["retry_loaded"])
        self.assertEqual(payload["cold_handlers"]["schedule"]["loop_thread_zoneinfo_opens"], [])
        self.assertEqual(payload["cold_handlers"]["dnd"]["loop_thread_zoneinfo_opens"], [])
        self.assertEqual(payload["cold_handlers"]["schedule"]["stopped_at"], "ScheduleActionError")
        self.assertEqual(payload["cold_handlers"]["dnd"]["stopped_at"], "StopProbe")
        self.assertEqual(payload["cold_handlers"]["refusals"]["gap"], "nonexistent_local_time")
        self.assertEqual(payload["cold_handlers"]["refusals"]["fold"], "ambiguous_local_time")
        self.assertEqual(payload["cold_handlers"]["refusals"]["membership"], "invalid_zone")
        self.assertEqual(payload["cold_handlers"]["refusals"]["loop_thread_zoneinfo_opens"], [])
        self.assertEqual(payload["schema"]["zoneinfo_opens"], [])
        self.assertEqual(payload["sync"]["utc_clocks"], ["21:00:00"])
        self.assertEqual(payload["sync"]["alias_key"], "US/Eastern")
        self.assertEqual(payload["sync"]["sync_invalid_zone"], "invalid_zone")
        concurrent_zones = payload["concurrent_zones"]
        self.assertGreater(concurrent_zones["zone_count"], 8)
        self.assertEqual(concurrent_zones["zone_count"], 10)
        for name, expected in (("schedule", "ScheduleActionError"), ("dnd", "StopProbe")):
            item = concurrent_zones[name]
            self.assertEqual(item["valid_distinct_zones"], 10)
            self.assertEqual(item["construct_calls"], 10)
            self.assertTrue(item["barrier_released_before_validation"])
            self.assertEqual(item["loop_thread_zoneinfo_opens"], [])
            self.assertEqual(item["outcomes"], [expected] * 10)


if __name__ == "__main__":
    unittest.main()
