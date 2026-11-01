"""Register CatGenie settings actions once for all loaded entries.

The schema library is the one Home Assistant already imported in
``homeassistant.helpers.config_validation``: ``probatio`` on current cores,
``vol`` on 2025.1.0. A globally installed copy of either library is not used.
Registration does not probe schemas and does not check framework type names.
"""

from __future__ import annotations

from typing import Any

from .const import DOMAIN
from .dnd_actions import (
    DND_ACTION_ENTRIES,
    SERVICE_SET_DO_NOT_DISTURB,
    DndActionRefused,
    DndIoError,
    async_apply_dnd,
)

_SAFE = {
    "missing": "CatGenie device is unavailable; do not disturb was not changed.",
    "foreign": "CatGenie device was not selected; do not disturb was not changed.",
    "ambiguous": "CatGenie device selection is ambiguous; do not disturb was not changed.",
    "offline": "CatGenie is offline; do not disturb was not changed.",
    "unavailable": "CatGenie device data is unavailable; do not disturb was not changed.",
    "incomplete": "CatGenie configuration is incomplete; do not disturb was not changed.",
    "dnd_unknown": (
        "CatGenie do-not-disturb fields are not a supported pair; "
        "do not disturb was not changed."
    ),
    "not_a_choice": (
        "CatGenie cat activation delay is not a supported choice; "
        "do not disturb was not changed."
    ),
    "invalid_time": "CatGenie do-not-disturb time is not a valid local clock; nothing was changed.",
    "invalid_date": "CatGenie do-not-disturb reference date is not valid; nothing was changed.",
    "invalid_zone": "CatGenie do-not-disturb time zone must be an IANA name; nothing was changed.",
    "invalid_enabled": "CatGenie do-not-disturb enabled must be true or false; nothing was changed.",
    "injected": "CatGenie do-not-disturb request has unsupported fields; nothing was changed.",
    "same_endpoint": "CatGenie do-not-disturb start and end must differ; nothing was changed.",
    "nonexistent_local_time": (
        "CatGenie do-not-disturb clock does not exist on that date; nothing was changed."
    ),
    "ambiguous_local_time": (
        "CatGenie do-not-disturb clock is ambiguous on that date; nothing was changed."
    ),
    "unexpected": "CatGenie device read was not usable; do not disturb was not changed.",
}
_IO = {
    "read": "CatGenie device read failed ({cls}); do not disturb was not changed.",
    "write": "CatGenie request failed ({cls}); the outcome is unconfirmed. It was not retried or rolled back.",
    "readback": "CatGenie readback failed ({cls}); the write was not retried or rolled back.",
}
_DND_FIELDS = (
    ("device_id", True),
    ("enabled", True),
    ("start_time", False),
    ("end_time", False),
    ("timezone", False),
    ("reference_date", False),
)


class ServiceRegistrationContractError(RuntimeError):
    """The framework validation backend cannot build a service schema."""


def safe_dnd_error(err: DndActionRefused | DndIoError) -> str:
    """User text. Vendor messages and request bodies are not included."""
    if isinstance(err, DndIoError):
        template = _IO.get(err.stage)
        class_name = err.class_name
        if template is None or type(class_name) is not str or not class_name.isidentifier():
            return "CatGenie do not disturb was not changed."
        return template.format(cls=class_name)
    return _SAFE.get(err.reason, "Unsupported CatGenie do not disturb request; nothing was changed.")


async def async_handle_set_do_not_disturb(call: Any) -> None:
    """Registered service callback. Validation runs again before any I/O."""
    from homeassistant.exceptions import HomeAssistantError

    from .action_permissions import async_check_device_control

    await async_check_device_control(call, call.data.get("device_id"))
    try:
        await async_apply_dnd(call.hass, call.data)
    except (DndActionRefused, DndIoError) as err:
        raise HomeAssistantError(safe_dnd_error(err)) from None


def framework_validation_backend() -> Any:
    """Return the schema library config_validation already bound.

    Current cores expose ``cv.probatio``. 2025.1.0 exposes ``cv.vol``.
    Importing either name from the process globals is intentionally not done:
    another integration can install the package without Home Assistant using it.
    """
    from homeassistant.helpers import config_validation as cv

    backend = getattr(cv, "probatio", None)
    if backend is None:
        backend = getattr(cv, "vol", None)
    if backend is None or not callable(getattr(backend, "Schema", None)):
        raise ServiceRegistrationContractError(
            "homeassistant.helpers.config_validation exposes neither probatio "
            "nor vol. The service was not registered."
        )
    if not callable(getattr(backend, "Invalid", None)):
        raise ServiceRegistrationContractError(
            "The config_validation schema backend has no Invalid. "
            "The service was not registered."
        )
    if getattr(backend, "PREVENT_EXTRA", None) is None:
        raise ServiceRegistrationContractError(
            "The config_validation schema backend has no PREVENT_EXTRA. "
            "The service was not registered."
        )
    if not callable(getattr(backend, "Required", None)) or not callable(getattr(backend, "Optional", None)):
        raise ServiceRegistrationContractError(
            "The config_validation schema backend has no Required/Optional. "
            "The service was not registered."
        )
    return backend


def _strict_bool(invalid: type[Exception]) -> Any:
    def validator(value: Any) -> bool:
        if type(value) is not bool:
            raise invalid("enabled must be true or false")
        return value

    return validator


def build_registered_schema() -> Any:
    """Build the DND schema ``async_register`` stores. No startup probe."""
    backend = framework_validation_backend()
    spec = {}
    for name, required in _DND_FIELDS:
        marker = backend.Required(name) if required else backend.Optional(name)
        if name == "enabled":
            spec[marker] = _strict_bool(backend.Invalid)
        else:
            def optional_string(value: Any) -> str | None:
                if value is not None and type(value) is not str:
                    raise backend.Invalid("expected str or null")
                return value

            spec[marker] = str if required else optional_string
    return backend.Schema(spec, extra=backend.PREVENT_EXTRA)


def _entries(hass: Any) -> set[str]:
    found = hass.data.get(DND_ACTION_ENTRIES)
    if isinstance(found, set):
        return found
    found = set()
    hass.data[DND_ACTION_ENTRIES] = found
    return found


async def _resolve_schedule_target(hass: Any, device_id: str) -> tuple[Any, Any]:
    """Use the same registry/config-entry resolver, then return the registry entry."""
    from homeassistant.helpers.device_registry import async_get
    from .dnd_actions import resolve_target
    from .schedule_actions import ScheduleActionRefused

    try:
        target = resolve_target(hass, device_id)
    except DndActionRefused as err:
        raise ScheduleActionRefused(err.reason) from None
    device = async_get(hass).async_get(device_id)
    if device is None or getattr(device, "id", None) != device_id:
        raise ScheduleActionRefused("unresolved")
    return target.coordinator, device


def async_setup_actions(hass: Any, entry: Any) -> None:
    """Register both global actions once, after entry platforms load."""
    from homeassistant.core import SupportsResponse
    from .schedule_actions import (
        SERVICE_SET_SCHEDULE,
        prime_iana_zones,
        register_schedule_service,
    )

    entries = _entries(hass)
    entries.add(entry.entry_id)
    prime_iana_zones(hass)
    names = (SERVICE_SET_DO_NOT_DISTURB, SERVICE_SET_SCHEDULE)
    existing = {name for name in names if hass.services.has_service(DOMAIN, name)}
    try:
        if SERVICE_SET_DO_NOT_DISTURB not in existing:
            hass.services.async_register(
                DOMAIN, SERVICE_SET_DO_NOT_DISTURB,
                async_handle_set_do_not_disturb, build_registered_schema(),
                SupportsResponse.NONE,
            )
        if SERVICE_SET_SCHEDULE not in existing:
            async def resolve(device_id: str) -> tuple[Any, Any]:
                return await _resolve_schedule_target(hass, device_id)
            register_schedule_service(hass, resolve)
    except Exception:
        entries.discard(entry.entry_id)
        if not entries:
            hass.data.pop(DND_ACTION_ENTRIES, None)
        for name in names:
            if name not in existing and hass.services.has_service(DOMAIN, name):
                hass.services.async_remove(DOMAIN, name)
        raise


def async_unload_actions(hass: Any, entry: Any) -> None:
    """Remove both global actions only when the last entry unloads."""
    from .schedule_actions import SERVICE_SET_SCHEDULE

    entries = hass.data.get(DND_ACTION_ENTRIES)
    if not isinstance(entries, set) or entry.entry_id not in entries:
        return
    entries.discard(entry.entry_id)
    if entries:
        return
    hass.data.pop(DND_ACTION_ENTRIES, None)
    for name in (SERVICE_SET_DO_NOT_DISTURB, SERVICE_SET_SCHEDULE):
        if hass.services.has_service(DOMAIN, name):
            hass.services.async_remove(DOMAIN, name)
