"""Minimal schema stub shared by legacy and current validation backends.

Not voluptuous, not probatio, and not a Home Assistant runtime. Tests attach
this module as ``homeassistant.helpers.config_validation.probatio`` or ``.vol``.
``Invalid`` is a plain Exception, not ``HomeAssistantError``.
"""

from __future__ import annotations


class Invalid(Exception):
    """Stand-in for the framework schema error the service call path catches."""


class _Marker:
    def __init__(self, key: str) -> None:
        self.key = key


class Required(_Marker):
    pass


class Optional(_Marker):
    pass


PREVENT_EXTRA = "prevent"
ALLOW_EXTRA = "allow"


def _apply(validator: object, value: object) -> object:
    if isinstance(validator, type):
        if not isinstance(value, validator):
            raise Invalid("type")
        return value
    if callable(validator):
        return validator(value)
    raise Invalid("validator")


class Schema:
    def __init__(self, spec: dict, extra: object = None) -> None:
        if extra is None:
            raise TypeError("extra is required")
        self.spec = spec
        self.extra = extra

    def __call__(self, data: dict) -> dict:
        if type(data) is not dict:
            raise Invalid("not-dict")
        allowed: dict[str, object] = {}
        required: set[str] = set()
        for key, validator in self.spec.items():
            name = key.key if isinstance(key, _Marker) else str(key)
            allowed[name] = validator
            if isinstance(key, Required):
                required.add(name)
        unknown = set(data) - set(allowed)
        if unknown and self.extra != ALLOW_EXTRA:
            raise Invalid("unknown_field")
        missing = required - set(data)
        if missing:
            raise Invalid("missing")
        return {name: _apply(allowed[name], value) if name in allowed else value
                for name, value in data.items()}
