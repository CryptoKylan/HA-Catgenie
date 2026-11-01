"""Post the app resume body through the pinned operation writer.

Resume sends the literal body ``{"state": 3}``. It does not replace
client methods, read stored login material, or send any other state.
Firmware acceptance is not proven. A failed call is not repeated here.
"""

from __future__ import annotations

from typing import Any

from .operation_post import post_allowed_operation


async def post_resume(client: Any, device_id: str) -> Any:
    """Invoke once; no integration retry. Pinned client may resend on HTTP 401."""
    return await post_allowed_operation(client, device_id, {"state": 3}, "resume")
