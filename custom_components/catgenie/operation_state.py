"""Adapter-local operation-state compatibility.

Stock catgenie 0.1.6 ``OperationState`` accepts only 0 and 1. Firmware has
reported the integer 2, and ``Device.model_validate`` then rejects the whole
account payload, which makes every entity unavailable.

Unrecognized integers are preserved. Reported state 2 is app SUSPENDED
(function #6945 maps it to STOPPED). It displays as paused only when that
same report has an explicit empty active-error list, blank vendor text, and
an explicit connected status. A missing or malformed error list is not that
report. Active errors, including water-fill code 2, stay faults and take
priority. Other unrecognized integers keep the generic Error label. Specific
fault reasons are not inferred from state codes.
This module does not retry faults, resume a cycle, or send device commands.
Command payloads stay untouched.
"""

from __future__ import annotations

from typing import Annotated, Any

from catgenie.models import Device, OperationState, OperationStatus
from pydantic import BeforeValidator, Field, PrivateAttr, model_validator

from .reported_config import measurement_snapshot

from .operation_status import preserve_raw_progress, reported_normal_pause

# Known idle/running codes retain their labels; the fallback label is Error.
OPERATION_STATE_IDLE = "idle"
OPERATION_STATE_CLEANING = "cleaning"
OPERATION_STATE_PAUSED = "paused"
OPERATION_STATE_ERROR = "error"
OPERATION_STATE_OPTIONS = (
    OPERATION_STATE_IDLE,
    OPERATION_STATE_CLEANING,
    OPERATION_STATE_PAUSED,
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

    @model_validator(mode="wrap")
    @classmethod
    def _keep_raw_progress(cls, data, handler):
        """Retain the original progress value for strict display sensors."""
        return preserve_raw_progress(data, handler)


class TolerantDevice(Device):
    """``Device`` subclass that validates ``operationStatus`` tolerantly.

    The nested field annotation is what ``model_validate`` uses. Passing a
    ``TolerantOperationStatus`` instance into stock ``Device`` can also keep
    an integer (Pydantic does not revalidate that instance by default); the
    integration does not rely on that, and it does not monkeypatch
    ``catgenie.models.Device``.
    """

    _reported_measurements: dict[str, Any] | None = PrivateAttr(default=None)

    @model_validator(mode="wrap")
    @classmethod
    def _keep_reported_measurements(cls, data, handler):
        snapshot = measurement_snapshot(data) if isinstance(data, dict) else None
        device = handler(data)
        if snapshot is not None:
            device._reported_measurements = snapshot
        return device

    operation_status: TolerantOperationStatus = Field(
        alias="operationStatus",
        default_factory=lambda: TolerantOperationStatus.model_validate(
            {"state": 0, "progress": 255}
        ),
    )


def operation_state_label(state: int) -> str:
    """Keep idle/cleaning labels and display the generic error fallback.

    Integer 2 is not paused here. A pause requires the explicit no-error
    report checked by ``operation_state_value``.
    """
    if state == OperationState.IDLE:
        return OPERATION_STATE_IDLE
    if state == OperationState.RUNNING:
        return OPERATION_STATE_CLEANING
    return OPERATION_STATE_ERROR


def operation_state_value(device: Device) -> str | None:
    """Enum label. A disconnected pause is not itself a reported fault."""
    if reported_normal_pause(device):
        return OPERATION_STATE_PAUSED
    if (
        device.operation_status.state == 2
        and not device.is_online
        and not device.active_errors
        and not device.operation_status.error.strip()
    ):
        return None
    return operation_state_label(device.operation_status.state)


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


# Active-error codes are separate from operation-state integers.
# 2/5 were observed on an A.I.; 3/4/6 come from Android app 1.8.253.
# See README.md for the app enum/message path and provenance.
_ACTIVE_ERROR_LABELS = {
    2: "Water fill issue",
    3: "Drainage issue",
    4: "Dryer overheating",
    5: "Cleaning solution cartridge missing",
    6: "Cleaning solution cartridge empty",
}
_MAX_ERROR_STATE_LENGTH = 255  # Home Assistant's maximum state-string length.


def _operation_error_details(device: Device) -> str | None:
    """Describe a reported fault without inventing a clear or fault reason."""
    vendor_error = device.operation_status.error
    if vendor_error.strip():
        return vendor_error

    labels = []
    for code in device.active_errors or []:
        if type(code) is int and code in _ACTIVE_ERROR_LABELS:
            labels.append(_ACTIVE_ERROR_LABELS[code])
        else:
            labels.append(f"Unknown error code: {json_safe(code)}")
    if labels:
        return "; ".join(labels)

    state = device.operation_status.state
    if state == 2 and not device.is_online:
        return None
    if (
        state not in (OperationState.IDLE, OperationState.RUNNING)
        and not reported_normal_pause(device)
    ):
        return f"Error reported (operation state: {state})"

    # Pydantic supplies idle/empty defaults when fields are absent. Those
    # defaults, or a disconnected device, are not a fresh no-fault report.
    if (
        device.is_online
        and {"operation_status", "active_errors"} <= device.model_fields_set
    ):
        return "No active errors"
    return None


def operation_error_label(device: Device) -> str | None:
    """Prefer vendor text, then observed or app-derived error descriptions.

    Observed and app-derived active-error integers select descriptions;
    operation-state integers never select these fault-specific labels.
    Long messages are bounded for HA, with full details kept in attributes.
    """
    details = _operation_error_details(device)
    if details is not None and len(details) > _MAX_ERROR_STATE_LENGTH:
        return details[: _MAX_ERROR_STATE_LENGTH - 3] + "..."
    return details


def operation_error_attributes(device: Device) -> dict[str, Any]:
    """Keep raw active errors and any full message too long for the state."""
    attributes = {"active_errors": json_safe(device.active_errors)}
    details = _operation_error_details(device)
    if details is not None and len(details) > _MAX_ERROR_STATE_LENGTH:
        attributes["error_details"] = details
    return attributes
