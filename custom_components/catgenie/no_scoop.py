"""Firmware gate and writer for the app no-scoop body.

The app shows Cleaning Cycle Settings, the path to "Run No Scoop Cycle
Now", only when ``semver.gte`` of letter-stripped ``device.fwVersion``
against ``8.5.81`` is true. ``playSpecial`` itself does not re-check
firmware. This module refuses unless that same comparison would pass,
and also refuses missing or strict-invalid versions instead of sending.
A passing gate is not firmware acceptance of state 129.

The comparison lives in the shared posting boundary. It is a strict
numeric subset of bundled node-semver, not a full semver implementation.
After letters are stripped, a string longer than 256 characters is
refused, matching ``MAX_LENGTH``. Each component above
``9007199254740991`` is refused before conversion, matching
``Number.MAX_SAFE_INTEGER``. Whitespace, prerelease tags, and build
metadata stay refused. Invalid input returns false and does not raise.
"""

from __future__ import annotations

from typing import Any

from .operation_post import (
    OperationNotSent,
    post_literal_state,
    special_cycle_firmware_eligible,
)

_NO_SCOOP_STATE = 129


async def post_no_scoop(client: Any, device_id: str, fw_version: object) -> Any:
    """Invoke state 129 after the gate, with no integration retry.

    The pinned client may resend once after HTTP 401.

    Firmware is forwarded into the shared writer. That writer validates it
    again before I/O. This helper's own check is not the only contract.
    """
    if not special_cycle_firmware_eligible(fw_version):
        raise OperationNotSent(
            "No-scoop firmware is not eligible; command was not sent."
        )
    return await post_literal_state(
        client,
        device_id,
        _NO_SCOOP_STATE,
        "no-scoop",
        fw_version,
    )
