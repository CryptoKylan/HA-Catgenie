"""Serialize configuration transactions within one account coordinator.

HA executes these lookups on its event loop, with no await between lookup and
insertion. Locks belong to the coordinator (not an entity or the client) and
are keyed by manufacturer id, so separate devices remain independent. This
is not vendor compare-and-swap and cannot coordinate another app/client.
"""
from __future__ import annotations

import asyncio
from typing import Any


def configuration_lock(coordinator: Any, manufacturer_id: str) -> asyncio.Lock:
    """Return the device lock. Use async with so failure/cancellation releases it."""
    locks = getattr(coordinator, "_configuration_locks", None)
    if locks is None:
        locks = coordinator._configuration_locks = {}
    if manufacturer_id not in locks:
        locks[manufacturer_id] = asyncio.Lock()
    return locks[manufacturer_id]
