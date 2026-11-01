"""Reported cartridge capacity with a labelled standard A.I. rated fallback."""
from __future__ import annotations

import math
from typing import Any

from catgenie import Device

from .entity import extra
from .reported_config import reported_activation_mode


def _rating_mode(device: Device) -> str | None:
    """Share the sensor's strict, pre-coercion activation interpretation."""
    return reported_activation_mode(device)


def _capacity(device: Device) -> tuple[int | float | None, str, str | None]:
    """Keep reported values first, and restrict ratings to a regular cartridge.

    TAG_TYPE 0 means missing and 3 maintenance in the Android app; neither
    should inherit a cached regular-cartridge maximum. Unknown cartridge
    types may supply their own maximum, but never receive the A.I. rating.
    """
    tag = extra(device, 'tagType')
    mode = _rating_mode(device)
    if type(tag) is int and tag in (0, 3):
        return None, 'unknown', mode
    reported = extra(device, 'totalSaniSolution')
    if type(reported) in (int, float) and reported > 0:
        if type(reported) is int or math.isfinite(reported):
            return reported, 'device_reported', mode
    if type(tag) is int and tag == 1 and mode is not None:
        return (240 if mode == 'cat' else 120), 'manufacturer_rating', mode
    return None, 'unknown', mode


def cartridge_capacity(device: Device) -> int | float | None:
    """Return capacity in the current mode's cleanings, not a liquid volume."""
    return _capacity(device)[0]


def cartridge_capacity_attributes(device: Device) -> dict[str, Any]:
    """Distinguish reported capacity from a manufacturer-rated reference."""
    _, source, mode = _capacity(device)
    attributes: dict[str, Any] = {'capacity_source': source}
    if mode is not None:
        attributes['cleaning_mode'] = mode
    return attributes
