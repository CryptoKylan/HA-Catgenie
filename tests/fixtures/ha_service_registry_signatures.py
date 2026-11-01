"""Pinned public service-registry signatures. Not a Home Assistant runtime.

Copied from tagged public sources; tests do not depend on an external checkout.
This module does not import Home Assistant and does not execute a framework.

2026.10.4 ``ServiceRegistry.async_register`` / ``async_remove`` / call path:
https://github.com/home-assistant/core/blob/2026.10.4/homeassistant/core.py
The call path invokes ``handler.schema(service_data)`` and catches only the
``Invalid`` of the library imported by
``homeassistant.helpers.config_validation`` (2026.10.4 imports ``probatio``).
https://github.com/home-assistant/core/blob/2026.10.4/homeassistant/helpers/config_validation.py

2025.1.0 ``ServiceRegistry.async_register`` / call path:
https://github.com/home-assistant/core/blob/2025.1.0/homeassistant/core.py
That module does ``import voluptuous as vol`` and catches ``vol.Invalid``.
``homeassistant.helpers.config_validation`` exposes the same module as ``vol``
(``import voluptuous as vol``). This file does not vendor that module.

Device linkage:
2026.10.4 ``DeviceEntry.config_entry_id`` is one id. ``config_entries`` is a
deprecated shim and logs on non-composite devices.
https://github.com/home-assistant/core/blob/2026.10.4/homeassistant/helpers/device_registry.py
2025.1.0 ``DeviceEntry.config_entries`` is a set. There is no ``config_entry_id``.
https://github.com/home-assistant/core/blob/2025.1.0/homeassistant/helpers/device_registry.py
"""

from __future__ import annotations

# Positional parameters. 2026 adds keyword-only description_placeholders.
ASYNC_REGISTER_2026 = (
    "self",
    "domain",
    "service",
    "service_func",
    "schema",
    "supports_response",
    "job_type",
)
ASYNC_REGISTER_2026_KWONLY = ("description_placeholders",)
ASYNC_REGISTER_2025 = (
    "self",
    "domain",
    "service",
    "service_func",
    "schema",
    "supports_response",
    "job_type",
)
ASYNC_REMOVE = ("self", "domain", "service")
HAS_SERVICE = True
SCHEMA_IS_CALLABLE = True
