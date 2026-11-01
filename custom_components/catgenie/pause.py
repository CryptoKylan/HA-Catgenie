"""Post the app pause body through the pinned operation writer.

Pause sends the literal body ``{"state": 2}``. That integer is the app
outbound SUSPENDED command. It is not a reported operation integer and
not an error code. This module does not replace client methods, read
stored login material, or send any other state. Firmware acceptance is
not proven. A failed call is not repeated here.
"""

from __future__ import annotations

from typing import Any

from .operation_post import post_allowed_operation


async def post_pause(client: Any, device_id: str) -> Any:
    """Invoke once; no integration retry. Pinned client may resend on HTTP 401."""
    return await post_allowed_operation(client, device_id, {"state": 2}, "pause")
