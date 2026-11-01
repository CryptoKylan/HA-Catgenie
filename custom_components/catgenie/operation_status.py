"""Readable operation status and strict numeric progress display.

Idle is shown only for an explicit connected report and an explicit idle
operation state. A cleaning percentage is shown only for an explicit cleaning
state and a finite progress value from 0 through 100. Reported state 2 is
paused text only for that same explicit connected report plus an explicit
empty active-error list and blank vendor text. Fault text stays on
operation_error. This module does not send commands or clear faults.
"""

from __future__ import annotations

import math
from typing import Any

from catgenie.models import Device, OperationState

_IDLE = "Idle"
_PAUSED_TEXT = "Paused"
# App #6945 maps CLEANING_STATE_VALUES.SUSPENDED (2) to CLEANING_STATUS.STOPPED.
# That integer is not active-error code 2 (water fill).
_REPORTED_SUSPENDED = 2


def preserve_raw_progress(data: Any, handler):
    """Keep the pre-coercion progress value on a validated status.

    The pinned model turns ``True`` into ``1`` and ``\"42\"`` into ``42``.
    Both display sensors must reject those coerced inputs as percentages;
    the pinned model's stored reading itself is left untouched.
    """
    present = isinstance(data, dict) and "progress" in data
    raw = data.get("progress") if present else None
    model = handler(data)
    if present:
        object.__setattr__(model, "_raw_progress", raw)
    return model


def explicit_online(device: Device) -> bool:
    """True only when reportedStatus was supplied and is connected.

    ``is_online`` is false for the empty Pydantic default, but that default
    is not an explicit offline report. Integer ``status`` is a different
    field and is not a connectivity substitute.
    """
    if "reported_status" not in device.model_fields_set:
        return False
    status = device.reported_status
    if not isinstance(status, str):
        return False
    return status.lower() == "connected"


def operation_status_available(device: Device) -> bool:
    """Use HA unavailable only for an explicit non-connected report.

    A missing reportedStatus stays available so the state can be unknown
    rather than a fabricated offline or Idle reading.
    """
    if "reported_status" not in device.model_fields_set:
        return True
    status = device.reported_status
    if not isinstance(status, str):
        return False
    return status.lower() == "connected"


def _explicit_state(device: Device) -> int | None:
    if "operation_status" not in device.model_fields_set:
        return None
    state = device.operation_status.state
    if isinstance(state, bool) or not isinstance(state, int):
        return None
    return int(state)


def _supplied_progress(status: Any) -> tuple[bool, Any]:
    if hasattr(status, "_raw_progress"):
        return True, getattr(status, "_raw_progress")
    fields = getattr(status, "model_fields_set", ())
    if "progress" in fields:
        return True, status.progress
    return False, None


def _finite_percent(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value < 0 or value > 100:
        return None
    return value


def _percentage_text(value: int | float) -> str:
    if isinstance(value, float) and not value.is_integer():
        return f"{value:g}%"
    return f"{int(value)}%"


def explicit_empty_active_errors(device: Device) -> bool:
    """True only when the payload supplied an empty list.

    A missing field uses Pydantic's empty default and is not an explicit
    clear. A non-list is malformed, not a clear.
    """
    if "active_errors" not in device.model_fields_set:
        return False
    errors = device.active_errors
    return isinstance(errors, list) and len(errors) == 0


def explicit_blank_vendor_error(device: Device) -> bool:
    """True when the reported operation status has no vendor error text."""
    if "operation_status" not in device.model_fields_set:
        return False
    error = device.operation_status.error
    return isinstance(error, str) and not error.strip()


def reported_normal_pause(device: Device | None) -> bool:
    """Reported SUSPENDED (2) plus an explicit no-error connected report.

    App ``convertDeviceCleaningStatusToAppCleannigStatus`` (#6945) maps
    IDLE 0 to NONE, PLAY 1 to CLEANING, and SUSPENDED 2 to STOPPED. Other
    reported integers are not paused. Missing, malformed, or non-empty
    active errors are not a pause. Offline is not a pause. Active-error
    code 2 is water fill and is not this state.
    """
    if device is None or not explicit_online(device):
        return False
    if "operation_status" not in device.model_fields_set:
        return False
    state = device.operation_status.state
    if isinstance(state, bool) or not isinstance(state, int):
        return False
    if state != _REPORTED_SUSPENDED:
        return False
    if not explicit_empty_active_errors(device):
        return False
    return explicit_blank_vendor_error(device)


def _idle_vendor_error_clear(device: Device) -> bool:
    """Idle-only: vendor error is optional, but a supplied value must be blank.

    Idle wire reports may omit error. Do not extend this allowance to
    pause/fault classification or treat an explicit null/malformed error as clear.
    """
    status = device.operation_status
    return "error" not in status.model_fields_set or explicit_blank_vendor_error(device)


def operation_progress_value(device: Device | None) -> int | float | None:
    """Strict numeric display; idle zero is a convention, not telemetry.

    Preserve valid reported idle percentages (even 100), rather than guessing
    that they are stale. Only missing progress or numeric sentinel 255 permits
    the idle-zero fallback, and only with an explicit no-fault online report.
    Vendor error text may be absent; if supplied it must be a blank string.
    """
    if device is None:
        return None
    status = device.operation_status
    supplied, raw = _supplied_progress(status)
    percent = _finite_percent(raw)
    # Preserve valid reported percentages regardless of cycle/connectivity;
    # these are not synthetic idle zeros. Only the fallback needs idle proof.
    if percent is not None:
        return percent
    if not (
        explicit_online(device)
        and "operation_status" in device.model_fields_set
        and "state" in status.model_fields_set
        and _explicit_state(device) == int(OperationState.IDLE)
        and explicit_empty_active_errors(device)
        and _idle_vendor_error_clear(device)
    ):
        return None
    # Do not accept string/bool lookalikes or other malformed progress as idle.
    if not supplied or (
        isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw == 255
    ):
        return 0
    return None


def operation_status_text(device: Device | None) -> str | None:
    """Return Idle, Paused, a percentage, or None. Never the string 'unknown'."""
    if device is None or not explicit_online(device):
        return None
    state = _explicit_state(device)
    if state == int(OperationState.IDLE):
        return _IDLE
    if reported_normal_pause(device):
        return _PAUSED_TEXT
    if state != int(OperationState.RUNNING):
        return None
    supplied, raw = _supplied_progress(device.operation_status)
    if not supplied:
        return None
    percent = _finite_percent(raw)
    if percent is None:
        return None
    return _percentage_text(percent)
