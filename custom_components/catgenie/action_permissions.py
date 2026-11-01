"""Apply HA's control permission to the selected CatGenie device.

Like HA's verify_domain_control, but restricted to entities belonging to the
selected device rather than any entity in the integration. Context-free
calls retain the normal trusted automation/internal-service behavior.
"""
from __future__ import annotations

from typing import Any


async def async_check_device_control(call: Any, device_id: str) -> None:
    """Reject unknown/unauthorized callers before device resolution or I/O."""
    context = getattr(call, "context", None)
    user_id = getattr(context, "user_id", None)
    if user_id is None:
        return

    from homeassistant.auth.permissions.const import POLICY_CONTROL
    from homeassistant.exceptions import Unauthorized, UnknownUser
    from homeassistant.helpers import entity_registry as er

    hass = call.hass
    user = await hass.auth.async_get_user(user_id)
    if user is None:
        raise UnknownUser(context=context, permission=POLICY_CONTROL, user_id=user_id)
    if user.is_admin:
        return
    registry = er.async_get(hass)
    if any(
        entity.platform == "catgenie"
        and entity.device_id == device_id
        and user.permissions.check_entity(entity.entity_id, POLICY_CONTROL)
        for entity in registry.entities.values()
    ):
        return
    raise Unauthorized(context=context, permission=POLICY_CONTROL, user_id=user_id)
