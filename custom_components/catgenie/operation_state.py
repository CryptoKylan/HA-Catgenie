"""Adapter-local operation-state compatibility.

Stock catgenie 0.1.6 ``OperationState`` accepts only 0 and 1. Firmware has
reported the integer 2, and ``Device.model_validate`` then rejects the whole
account payload, which makes every entity unavailable.

Unrecognized integers, including 2, are preserved and displayed with the
generic Error label. Specific fault reasons are not inferred from state codes.
This module does not retry faults, resume a cycle, or send device commands.
Command payloads stay untouched.
"""

from __future__ import annotations

from typing import Annotated, Any

from catgenie.models import Device, OperationState, OperationStatus
from pydantic import BeforeValidator, Field

# Known idle/running codes retain their labels; the fallback label is Error.
OPERATION_STATE_IDLE = "idle"
OPERATION_STATE_CLEANING = "cleaning"
OPERATION_STATE_ERROR = "error"
OPERATION_STATE_OPTIONS = (
    OPERATION_STATE_IDLE,
    OPERATION_STATE_CLEANING,
    OPERATION_STATE_ERROR,
)


def require_integer_operation_state(value: Any) -> int:
    """Keep a real integer code. Refuse coerced or non-integer values.

    Bool is an ``int`` subclass and must not become 0/1. Strings such as
    ``"2"`` and floats such as ``2.0`` are malformed, not unknown states.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("operation state must be an integer")
    return int(value)


IntegerOperationState = Annotated[
    int, BeforeValidator(require_integer_operation_state)
]


class TolerantOperationStatus(OperationStatus):
    """``OperationStatus`` that stores unrecognized integer states as ints."""

    state: IntegerOperationState = Field(alias="state")


class TolerantDevice(Device):
    """``Device`` subclass that validates ``operationStatus`` tolerantly.

    The nested field annotation is what ``model_validate`` uses. Passing a
    ``TolerantOperationStatus`` instance into stock ``Device`` can also keep
    an integer (Pydantic does not revalidate that instance by default); the
    integration does not rely on that, and it does not monkeypatch
    ``catgenie.models.Device``.
    """

    operation_status: TolerantOperationStatus = Field(
        alias="operationStatus",
        default_factory=lambda: TolerantOperationStatus.model_validate(
            {"state": 0, "progress": 255}
        ),
    )


def operation_state_label(state: int) -> str:
    """Keep idle/cleaning labels and display the generic error fallback."""
    if state == OperationState.IDLE:
        return OPERATION_STATE_IDLE
    if state == OperationState.RUNNING:
        return OPERATION_STATE_CLEANING
    return OPERATION_STATE_ERROR


def cleaning_known(state: int) -> bool | None:
    """Binary cleaning for known codes only.

    Unsupported integers return ``None`` (unknown), not ``False``. Stock
    ``is_cleaning`` is False for those integers and must not be used here.
    """
    if state == OperationState.RUNNING:
        return True
    if state == OperationState.IDLE:
        return False
    return None


def json_safe(value: Any) -> Any:
    """Copy a value into JSON-safe primitives without interpreting it."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return str(value)
        return value
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return str(value)


def operation_state_attributes(device: Device) -> dict[str, Any]:
    """Dashboard attributes for the operation_state sensor.

    ``raw_state`` is the integer code, including unrecognized values.
    ``active_errors`` is the raw list, not a fault classification.
    """
    return {
        "raw_state": int(device.operation_status.state),
        "active_errors": json_safe(device.active_errors),
    }


def operation_error_label(device: Device) -> str | None:
    """Prefer vendor text, otherwise describe active error codes.

    activeErrors is a separate namespace from operationStatus.state.
    Code 5 was observed on an A.I. running 8.7.205R when its cleaning
    solution cartridge was removed. Other codes remain explicitly unknown.
    """
    if device.operation_status.error:
        return device.operation_status.error
    labels = []
    for code in device.active_errors or []:
        if type(code) is int and code == 5:
            labels.append("Cleaning solution cartridge missing")
        else:
            labels.append(f"Unknown error code: {json_safe(code)}")
    return "; ".join(labels) or None


def operation_error_attributes(device: Device) -> dict[str, Any]:
    """Diagnostic copy of the raw activeErrors list."""
    return {"active_errors": json_safe(device.active_errors)}
