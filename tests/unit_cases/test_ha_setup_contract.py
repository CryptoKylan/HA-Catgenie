"""Installed-HA API/real-backend checks in a fresh, unstubbed interpreter."""
import ast
import asyncio

import inspect
from pathlib import Path

import unittest
from unittest.mock import AsyncMock

from tests.process_harness import require_dependencies

ROOT = Path(__file__).resolve().parents[2]


class HomeAssistantSetupContractTests(unittest.TestCase):
    def setUp(self):
        require_dependencies(self, "homeassistant.core", "catgenie")

    def test_config_entry_task_calls_bind_actual_installed_methods(self):
        from homeassistant.config_entries import ConfigEntry
        tree = ast.parse((ROOT / "custom_components/catgenie/__init__.py").read_text())
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute)
                 and isinstance(node.func.value, ast.Name) and node.func.value.id == "entry"
                 and node.func.attr in ("async_create_task", "async_create_background_task")]
        self.assertTrue(calls)
        for call in calls:
            with self.subTest(method=call.func.attr, line=call.lineno):
                signature = inspect.signature(getattr(ConfigEntry, call.func.attr))
                signature.bind(object(), *[object() for _ in call.args],
                               **{kw.arg: object() for kw in call.keywords})
                self.assertIsInstance(call.args[0], ast.Name)
                self.assertEqual(call.args[0].id, "hass")

    def test_service_registry_fixture_matches_actual_installed_api(self):
        from homeassistant.core import ServiceRegistry
        from tests.fixtures.ha_service_registry_signatures import (
            ASYNC_REGISTER_2026, ASYNC_REGISTER_2026_KWONLY)
        signature = inspect.signature(ServiceRegistry.async_register)
        positional = tuple(n for n, p in signature.parameters.items()
                           if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD))
        kwonly = tuple(n for n, p in signature.parameters.items() if p.kind == p.KEYWORD_ONLY)
        self.assertEqual(positional, ASYNC_REGISTER_2026)
        # Both real APIs are supported; reject any third, unverified shape.
        self.assertIn(kwonly, ((), ASYNC_REGISTER_2026_KWONLY))
        # The synthetic registry intentionally models the newer superset API,
        # while the schema test below executes the actual installed registry.
        tree = ast.parse((ROOT / "tests/unit_cases/test_schedule_actions.py").read_text())
        fixture = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "async_register")
        self.assertEqual(tuple(n.arg for n in fixture.args.args), positional)
        self.assertEqual(tuple(n.arg for n in fixture.args.kwonlyargs), ASYNC_REGISTER_2026_KWONLY)

    def test_actual_schema_backend_refuses_extra_before_handler_or_http(self):
        from homeassistant.core import HomeAssistant
        from homeassistant.helpers import config_validation as cv
        from homeassistant.exceptions import ServiceValidationError
        from custom_components.catgenie.schedule_actions import register_schedule_service
        backend = getattr(cv, "probatio", None) or getattr(cv, "vol", None)
        self.assertIsNotNone(backend)

        async def check():
            import os
            import tempfile
            from curl_cffi.requests import AsyncSession
            from unittest.mock import patch
            with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as config:
                hass = HomeAssistant(config)
                resolver = AsyncMock(side_effect=AssertionError("schema must refuse before resolver"))
                register_schedule_service(hass, resolver)
                schema = hass.services._services["catgenie"]["set_schedule"].schema
                valid = {"device_id": "ha-device", "zone": "UTC", "times": [{"time": "08:00:00"}]}
                self.assertEqual(schema(valid), valid)
                with patch.object(AsyncSession, "request", new_callable=AsyncMock) as http:
                    for key in ("mode", "manual", "extra"):
                        with self.subTest(key=key):
                            with self.assertRaises(backend.Invalid):
                                schema({**valid, key: 1})
                            # Real ServiceRegistry also validates before dispatch.
                            with self.assertRaises((backend.Invalid, ServiceValidationError)):
                                await hass.services.async_call("catgenie", "set_schedule", {**valid, key: 1}, blocking=True)
                    resolver.assert_not_awaited()
                    http.assert_not_awaited()
                await hass.async_stop()
        asyncio.run(check())
