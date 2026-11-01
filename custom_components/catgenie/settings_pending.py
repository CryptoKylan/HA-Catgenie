"""Bounded display hold after an accepted settings PUT.

A PUT acknowledgement is not vendor confirmation and is not written into
the coordinator device. The select or number shows the requested value
until a later poll matches it, the device is missing, or two idle poll
intervals elapse. The window is two idle intervals because the refresh
that follows the PUT can itself be a stale GET; one interval can expire
before the next scheduled poll has a chance to confirm. It is not
unbounded, so an accepted-but-unapplied change cannot stick.

The one-shot expiry uses Home Assistant 2026.10.4
``async_call_later(hass, delay: float | timedelta, action) -> cancel``.
The action receives one datetime. ``Entity.async_on_remove(callback)``
stores that cancel and runs it on removal. This does not add a poll or
a second refresh.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TypeVar

from .const import SCAN_INTERVAL_IDLE

T = TypeVar("T")

# Two configured idle intervals (60s * 2). See module docstring.
PENDING_CONFIRMATION_WINDOW = SCAN_INTERVAL_IDLE * 2


def _monotonic() -> float:
    import time

    return time.monotonic()


class SettingsPending:
    """Per-entity hold. Not coordinator state and not a vendor confirmation."""

    def __init__(
        self,
        window: timedelta | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._window = (window or PENDING_CONFIRMATION_WINDOW).total_seconds()
        if self._window <= 0:
            raise ValueError("pending window must be positive and bounded")
        self._now = now or _monotonic
        self._seq = 0
        self._accepted_seq = 0
        self._active = False
        self._value: T | None = None
        self._baseline: T | None = None
        self._deadline = 0.0

    @property
    def window_seconds(self) -> float:
        return self._window

    @property
    def active(self) -> bool:
        return self._active

    @property
    def generation(self) -> int:
        """Latest accepted attempt. A newer start that has not been acked does not change this."""
        return self._accepted_seq

    def start(self) -> int:
        """Reserve an attempt before the PUT. This is not an acceptance."""
        self._seq += 1
        return self._seq

    def accept(self, token: int, value: T, baseline: T | None) -> bool:
        """Record an ack if no newer attempt has already been accepted."""
        if token < self._accepted_seq:
            return False
        self._accepted_seq = token
        self._value = value
        self._baseline = baseline
        self._deadline = self._now() + self._window
        self._active = True
        return True

    def mark_due(self) -> None:
        if self._active:
            self._deadline = self._now()

    def clear(self) -> None:
        self._active = False
        self._value = None
        self._baseline = None

    def resolve(self, cloud: T | None, *, present: bool) -> tuple[T | None, bool]:
        """Return the display value and whether it is still an unconfirmed hold.

        A missing device drops the hold. A matching poll clears it. Any other
        cloud value, including an intermediate GET from an older write, keeps
        the latest accepted value until the deadline.
        """
        if not self._active:
            return cloud, False
        if not present:
            self.clear()
            return None, False
        if self._now() >= self._deadline:
            self.clear()
            return cloud, False
        if cloud == self._value:
            self.clear()
            return cloud, False
        return self._value, True


def cancel_settings_pending_timer(entity: object) -> None:
    """Cancel the current one-shot expiry. Safe to call more than once."""
    unsub = getattr(entity, "_settings_pending_unsub", None)
    if unsub is None:
        return
    entity._settings_pending_unsub = None
    unsub()


def arm_settings_pending_timer(entity: object, pending: SettingsPending) -> None:
    """Arm one expiry after an accept, if the entity has been added to hass."""
    cancel_settings_pending_timer(entity)
    hass = getattr(entity, "hass", None)
    if hass is None:
        return
    from homeassistant.core import callback
    from homeassistant.helpers.event import async_call_later

    generation = pending.generation

    @callback
    def _expired(_now: datetime) -> None:
        if not pending.active or pending.generation != generation:
            return
        pending.mark_due()
        entity.async_write_ha_state()

    entity._settings_pending_unsub = async_call_later(
        hass, pending.window_seconds, _expired
    )
    if not getattr(entity, "_settings_pending_unload_registered", False):
        entity.async_on_remove(lambda: cancel_settings_pending_timer(entity))
        entity._settings_pending_unload_registered = True


def note_accepted(
    entity: object,
    pending: SettingsPending,
    token: int,
    value: T,
    baseline: T | None,
) -> bool:
    """Hold a value only after the PUT await returns, then publish if added."""
    if not pending.accept(token, value, baseline):
        return False
    arm_settings_pending_timer(entity, pending)
    if getattr(entity, "hass", None) is not None:
        entity.async_write_ha_state()
    return True


def displayed(
    entity: object,
    pending: SettingsPending,
    cloud: T | None,
    *,
    present: bool,
) -> tuple[T | None, bool]:
    """Resolve the hold and drop the expiry timer once it is no longer needed."""
    value, holding = pending.resolve(cloud, present=present)
    if not holding:
        cancel_settings_pending_timer(entity)
    return value, holding


def pending_attributes(holding: bool) -> dict[str, bool] | None:
    """Expose an unconfirmed hold. Absence is not a claim that the vendor confirmed it."""
    if not holding:
        return None
    return {"pending_confirmation": True}
