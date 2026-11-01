"""Post an allowed app operation body through the pinned writer.

The pinned client posts an operation by calling ``_request`` with
``ENDPOINT_DEVICE_OPERATION``. This helper uses that writer once. The
ungated allowlist is pause state 2, resume state 3, and abort state 4.
State 129 is not on that allowlist. This module posts it only when the
caller passes firmware into ``post_literal_state`` and the no-scoop gate
below accepts that value. A prior caller check is not the contract. This
module does not replace client methods, read stored login material, or
choose a state from a reported integer. Firmware acceptance is not proven.
A failed call is not repeated at the integration layer. The pinned client
can refresh authentication and resend once after HTTP 401; this is not an
exactly-once firmware execution guarantee.
"""

from __future__ import annotations

from typing import Any

from catgenie.const import ENDPOINT_DEVICE_OPERATION

_EXPECTED_OPERATION_PATH = "device/management/{device_id}/operation"
_ALLOWED_STATES = (2, 3, 4)
_NO_SCOOP_STATE = 129
# App constant specialCycleThresholdVersion, compared numerically by semver.gte.
_THRESHOLD = (8, 5, 81)
# Bundled SemVer MAX_LENGTH, hasm 576783. Applied to the letter-stripped string.
_MAX_STRIPPED_LENGTH = 256
# Bundled Number.MAX_SAFE_INTEGER fallback, hasm 576782.
_MAX_SAFE_INTEGER_TEXT = "9007199254740991"


class OperationNotSent(RuntimeError):
    """Local refusal. The operation writer was not called."""


def _strip_ascii_letters(value: str) -> str:
    """Match the app ``replace(/[A-Za-z]/g, '')`` transform."""
    return "".join(ch for ch in value if not ("A" <= ch <= "Z" or "a" <= ch <= "z"))


def _component_value(part: str) -> int | None:
    """Return one numeric component, or None before any unsafe conversion."""
    if not part.isascii() or not part.isdigit():
        return None
    if len(part) > 1 and part[0] == "0":
        return None
    if len(part) > len(_MAX_SAFE_INTEGER_TEXT) or (
        len(part) == len(_MAX_SAFE_INTEGER_TEXT) and part > _MAX_SAFE_INTEGER_TEXT
    ):
        return None
    return int(part)


def _strict_numeric_version(value: str) -> tuple[int, int, int] | None:
    """Return MAJOR.MINOR.PATCH or None.

    Overlong stripped text and components above ``9007199254740991`` are
    refused before ``int`` conversion. A leading zero is invalid in strict
    semver. This refuses those inputs instead of sending.
    """
    if len(value) > _MAX_STRIPPED_LENGTH:
        return None
    parts = value.split(".")
    if len(parts) != 3:
        return None
    numbers: list[int] = []
    for part in parts:
        number = _component_value(part)
        if number is None:
            return None
        numbers.append(number)
    return (numbers[0], numbers[1], numbers[2])


def special_cycle_firmware_eligible(fw_version: object) -> bool:
    """True only when the app settings row would be shown.

    Source field is ``fwVersion``. Letters are stripped, then the result
    must be a non-empty string and a strict three-component version greater
    than or equal to 8.5.81, no longer than 256 characters, and with each
    component at most ``9007199254740991``. Missing, non-string, empty,
    oversized, and malformed values are not eligible and do not raise.
    Whitespace, prerelease, and build forms stay refused. This function
    does not send.
    """
    if not isinstance(fw_version, str) or fw_version == "":
        return False
    try:
        stripped = _strip_ascii_letters(fw_version)
        if stripped == "" or len(stripped) > _MAX_STRIPPED_LENGTH:
            return False
        parsed = _strict_numeric_version(stripped)
    except (ValueError, OverflowError):
        return False
    if parsed is None:
        return False
    return parsed >= _THRESHOLD


def _require_writer(client: Any, label: str) -> None:
    request = getattr(client, "_request", None)
    if not callable(request):
        raise OperationNotSent(
            f"Pinned CatGenie client has no _request writer; {label} was not sent."
        )
    if ENDPOINT_DEVICE_OPERATION != _EXPECTED_OPERATION_PATH:
        raise OperationNotSent(
            f"Pinned operation endpoint changed; {label} was not sent."
        )


async def post_literal_state(
    client: Any,
    device_id: str,
    state: int,
    label: str,
    fw_version: object = None,
) -> Any:
    """Invoke the writer once; no integration-level retry (client may resend on 401).

    States 2, 3, and 4 do not need firmware. State 129 is posted only when
    ``fw_version`` is passed into this call and the no-scoop gate accepts it.
    Omitting firmware, or passing a missing, malformed, below-threshold, or
    oversized version, refuses before any writer call. Every other integer,
    including start 1 and stop 0, is refused.
    """
    if not isinstance(device_id, str) or device_id == "":
        raise OperationNotSent(f"{label.capitalize()} needs a device id; nothing was sent.")
    if type(state) is not int:
        raise OperationNotSent(
            f"{label} body is not an allowed app operation state; {label} was not sent."
        )
    if state == _NO_SCOOP_STATE:
        if not special_cycle_firmware_eligible(fw_version):
            raise OperationNotSent(
                "No-scoop firmware is not eligible; command was not sent."
            )
    elif state not in _ALLOWED_STATES:
        raise OperationNotSent(
            f"{label} body is not an allowed app operation state; {label} was not sent."
        )
    _require_writer(client, label)
    path = ENDPOINT_DEVICE_OPERATION.format(device_id=device_id)
    payload = {"state": state}
    return await client._request("POST", path, body=payload)


async def post_allowed_operation(
    client: Any,
    device_id: str,
    body: dict[str, Any],
    label: str,
) -> Any:
    """Invoke once without integration retries; client may resend on 401. Refuse 129."""
    if not isinstance(device_id, str) or device_id == "":
        raise OperationNotSent(f"{label.capitalize()} needs a device id; nothing was sent.")
    state = body.get("state") if type(body) is dict else None
    if (
        type(body) is not dict
        or list(body) != ["state"]
        or type(state) is not int
        or state not in _ALLOWED_STATES
    ):
        raise OperationNotSent(
            f"{label} body is not an allowed app operation state; {label} was not sent."
        )
    return await post_literal_state(client, device_id, state, label)
