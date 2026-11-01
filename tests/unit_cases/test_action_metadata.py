"""Service-description and event-loop regressions for the settings actions.

The YAML check uses Home Assistant 2026.10.4's own services schema when that
package is installed. The loop check fails if importing the action module on a
running loop walks or opens zoneinfo. Neither test calls a live device.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "custom_components" / "catgenie"
ACTIONS = COMPONENT / "schedule_actions.py"
SERVICES = COMPONENT / "services.yaml"


def _object_time_field(text: str) -> str:
    marker = "fields:\n            time:\n"
    start = text.index(marker) + len(marker)
    return text[start : text.index("selector:", start)]


class ActionMetadataContractTests(unittest.TestCase):
    def test_object_selector_field_uses_label_not_name(self) -> None:
        for path in (SERVICES, ACTIONS):
            field = _object_time_field(path.read_text(encoding="utf-8"))
            with self.subTest(path=path.name):
                self.assertIn("label: Local time", field)
                self.assertNotIn("name:", field)

    def test_iana_zones_are_not_loaded_at_import(self) -> None:
        tree = ast.parse(ACTIONS.read_text(encoding="utf-8"))
        visitor = _ModuleCallVisitor()
        visitor.visit(tree)
        names = {ast.unparse(node.func) for node in visitor.calls}
        self.assertNotIn("available_timezones", names)
        handler = _function(tree, "async_handle_set_schedule")
        awaited = [
            ast.unparse(node.value)
            for node in handler.body
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Await)
        ]
        self.assertTrue(any("async_iana_zones" in item for item in awaited))
        prepare = next(
            index
            for index, node in enumerate(handler.body)
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and ast.unparse(node.value.func) == "_prepare"
        )
        zone_await = next(
            index
            for index, node in enumerate(handler.body)
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Await)
            and "async_iana_zones" in ast.unparse(node.value)
        )
        self.assertLess(zone_await, prepare)

    def test_import_on_the_event_loop_does_not_touch_zoneinfo(self) -> None:
        from tests.process_harness import dependency_env, require_dependencies
        require_dependencies(self, "catgenie", "homeassistant.core")
        completed = subprocess.run(
            [sys.executable, "-c", _LOOP_PROBE], cwd=ROOT,
            env=dependency_env(), capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("ZONEINFO_IO 0", completed.stdout)
        self.assertIn("AUDIT_CALIBRATION_OK", completed.stdout)

    def test_installed_ha_accepts_services_yaml(self) -> None:
        from tests.process_harness import dependency_env, require_dependencies
        require_dependencies(self, "homeassistant.helpers.service", "catgenie")
        completed = subprocess.run(
            [sys.executable, "-c", _HA_PROBE], cwd=ROOT,
            env=dependency_env(), capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("PARSE_OK", completed.stdout)
        self.assertIn("LOOP_CLEAN", completed.stdout)


def _function(tree: ast.AST, name: str) -> ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(name)


class _ModuleCallVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.calls: list[ast.Call] = []
        self._depth = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._depth += 1
        self.generic_visit(node)
        self._depth -= 1

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]
    visit_ClassDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_Call(self, node: ast.Call) -> None:
        if self._depth == 0:
            self.calls.append(node)
        self.generic_visit(node)


_LOOP_PROBE = textwrap.dedent(
    """
    import asyncio
    import os
    import sys
    import threading

    sys.path[:0] = os.environ["PYTHONPATH"].split(os.pathsep)
    import custom_components.catgenie.const
    import custom_components.catgenie.schedule
    from zoneinfo import ZoneInfo
    from tests.metadata_sol_probe import _audit
    sys.modules.pop("custom_components.catgenie.schedule_actions", None)

    opens = []
    active = _audit(threading.get_ident(), opens)

    async def load():
        # Positive control: the C ZoneInfo constructor bypasses builtins.open.
        ZoneInfo.clear_cache()
        active["on"] = True
        ZoneInfo("America/Adak")
        active["on"] = False
        assert opens, "audit hook missed a cold on-loop ZoneInfo open"
        print("AUDIT_CALIBRATION_OK", len(opens))
        opens.clear()
        ZoneInfo.clear_cache()
        active["on"] = True
        try:
            from custom_components.catgenie.schedule_actions import SERVICE_SET_SCHEDULE
            assert SERVICE_SET_SCHEDULE == "set_schedule"
        finally:
            active["on"] = False

    asyncio.run(load())
    print("ZONEINFO_IO", len(opens))
    if opens:
        raise SystemExit(2)
    """
)


_HA_PROBE = textwrap.dedent(
    """
    import asyncio
    import builtins
    import importlib
    import logging
    import os
    import sys
    import threading
    from pathlib import Path
    from types import SimpleNamespace

    paths = os.environ["PYTHONPATH"].split(os.pathsep)
    sys.path[:0] = paths
    root = Path(paths[0])
    from homeassistant.helpers.service import _load_services_file
    from homeassistant.util.loop import protect_loop

    component = root / "custom_components" / "catgenie"
    logger = logging.getLogger("homeassistant.helpers.service")
    warnings = []

    class Capture(logging.Handler):
        def emit(self, record):
            warnings.append(record.getMessage())

    handler = Capture()
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    import inspect
    integration = SimpleNamespace(domain="catgenie", file_path=component)
    parameters = tuple(inspect.signature(_load_services_file).parameters)
    if parameters == ("hass", "integration"):
        # HA 2025.7 accepts an unused hass argument in this pure YAML loader.
        loaded = _load_services_file(None, integration)
    elif parameters == ("integration",):
        loaded = _load_services_file(integration)
    else:
        raise AssertionError(f"Unverified service-loader signature: {parameters}")
    logger.removeHandler(handler)
    if warnings:
        print("\\n".join(warnings))
        raise SystemExit(3)
    for name in ("set_do_not_disturb", "set_schedule"):
        fields = loaded[name]["fields"]
        if not fields:
            print("EMPTY", name)
            raise SystemExit(4)
        print("FIELDS", name, ",".join(fields))
    time_field = loaded["set_schedule"]["fields"]["times"]["selector"]["object"]["fields"]["time"]
    if "name" in time_field or time_field.get("label") != "Local time":
        print("BAD_FIELD", time_field)
        raise SystemExit(5)
    if "time" not in time_field["selector"]:
        print("BAD_SELECTOR", time_field)
        raise SystemExit(6)

    import custom_components.catgenie.const
    import custom_components.catgenie.schedule
    import zoneinfo
    sys.modules.pop("custom_components.catgenie.schedule_actions", None)
    loop_id = threading.get_ident()
    originals = (os.walk, builtins.open, importlib.import_module)
    os.walk = protect_loop(originals[0], loop_id, strict=False, strict_core=False)
    builtins.open = protect_loop(
        originals[1], loop_id, strict=False, strict_core=False,
        check_allowed=lambda mapped: str(mapped["args"][0]).startswith("/proc"),
    )
    importlib.import_module = protect_loop(
        originals[2], loop_id, strict=False, strict_core=False,
        check_allowed=lambda mapped: bool(mapped.get("args") and mapped["args"][0] in sys.modules),
    )
    loop_logger = logging.getLogger("homeassistant.util.loop")
    loop_warnings = []

    class LoopCapture(logging.Handler):
        def emit(self, record):
            loop_warnings.append(record.getMessage())

    loop_handler = LoopCapture()
    loop_logger.addHandler(loop_handler)
    loop_logger.setLevel(logging.WARNING)

    async def load():
        importlib.import_module("custom_components.catgenie.schedule_actions")

    try:
        asyncio.run(load())
    finally:
        os.walk = originals[0]
        builtins.open = originals[1]
        importlib.import_module = originals[2]
        loop_logger.removeHandler(loop_handler)
    relevant = [
        message for message in loop_warnings
        if "schedule_actions.py" in message
        and (
            "Detected blocking call to walk" in message
            or "Detected blocking call to open" in message
            or "import_module with args ('tzdata'," in message
        )
    ]
    if relevant:
        print("\\n".join(item.splitlines()[0] for item in relevant))
        raise SystemExit(7)
    print("PARSE_OK")
    print("LOOP_CLEAN")
    """
)


if __name__ == "__main__":
    unittest.main()
