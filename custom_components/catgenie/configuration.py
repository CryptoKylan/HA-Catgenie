"""Partial configuration writes for proven CatGenie settings.

Wire mode is not the app presentation enum (cat 0, schedule 1, manual 2) and
not the library ``CleaningMode.MANUAL`` label. Observed pairs are mode 0 /
manual 0 for cat, mode 1 / manual 0 for time, and manual 1 with the existing
mode preserved. The app copies the current mode when the caller omits it.

These helpers send only the intended flat keys. Omitting schedule and nested
objects avoids creating a schedule or replacing sibling
binaryElements. A PUT acknowledgement is not vendor validation; callers must
refresh and read the next coordinator snapshot.
"""

from __future__ import annotations

import math
import re
from typing import Any

from catgenie import CleaningMode, Device

from .local_errors import SettingsWriteRefused
from .reported_config import reported_measurement, reported_activation_mode

ACTIVATION_CAT = "cat"
ACTIVATION_MANUAL = "manual"
ACTIVATION_TIME = "time"
ACTIVATION_OPTIONS = (ACTIVATION_CAT, ACTIVATION_MANUAL, ACTIVATION_TIME)

VOLUME_MIN = 1
VOLUME_MAX = 7

_KNOWN_MODES = (CleaningMode.AUTOMATIC, CleaningMode.MANUAL)


def refusal_message(setting: str, reason: str) -> str:
    """User-facing refusal. It does not claim the vendor accepted a change."""
    if reason == "missing":
        return f"CatGenie device is unavailable; {setting} was not changed."
    if reason == "offline":
        return f"CatGenie is offline; {setting} was not changed."
    if reason == "incomplete":
        return f"CatGenie configuration is incomplete; {setting} was not changed."
    if reason == "unknown":
        return f"CatGenie {setting} is unknown; it was not changed."
    if reason == "out_of_range":
        return (
            f"CatGenie volume must be an integer from {VOLUME_MIN} to {VOLUME_MAX}."
        )
    if reason == "not_a_choice":
        if setting == "cat activation delay":
            return (
                "CatGenie cat activation delay must be "
                "5, 10, 15, 20, 25, or 30 minutes."
            )
        return (
            "CatGenie auto-lock timeout must be 0 (off) or "
            "5, 10, 15, 20, 25, or 30 minutes."
        )
    if reason == "dnd_unknown":
        return (
            "CatGenie do-not-disturb fields are not a supported unchanged pair; "
            "cat activation delay was not changed."
        )
    return f"Unsupported CatGenie {setting}."


def _configuration(device: Device | None) -> Any | None:
    if device is None or "configuration" not in device.model_fields_set:
        return None
    return device.configuration


def _explicit_mode(device: Device) -> int | None:
    configuration = _configuration(device)
    if (configuration is None or "mode" not in configuration.model_fields_set
            or configuration.mode not in _KNOWN_MODES):
        return None
    mode = reported_measurement(device, "mode")
    if type(mode) not in (int, CleaningMode) or mode not in _KNOWN_MODES:
        return None
    return int(mode)


def _explicit_manual(device: Device) -> int | None:
    manual = reported_measurement(device, "manual")
    if type(manual) is not int or manual not in (0, 1):
        return None
    return manual


def _require_online(device: Device | None) -> Any:
    if device is None:
        raise SettingsWriteRefused("missing")
    if not device.is_online:
        raise SettingsWriteRefused("offline")
    configuration = _configuration(device)
    if configuration is None:
        raise SettingsWriteRefused("incomplete")
    return configuration


def activation_label(device: Device | None) -> str | None:
    """Return cat, manual, or time only from explicit raw fields."""
    configuration = _configuration(device)
    if configuration is None:
        return None
    return reported_activation_mode(device)


def activation_payload(device: Device | None, option: str) -> dict[str, int]:
    """Return only ``mode`` and ``manual``.

    Manual keeps the current wire mode, matching the app's undefined-mode
    branch. Cat and time set both fields explicitly. Schedule is not included
    and is not created.
    """
    if option not in ACTIVATION_OPTIONS:
        raise SettingsWriteRefused("unsupported")
    _require_online(device)
    mode = _explicit_mode(device)
    manual = _explicit_manual(device)
    if mode is None or manual is None:
        raise SettingsWriteRefused("unknown")
    if option == ACTIVATION_MANUAL:
        # Preserve the current wire mode. Do not force 0, and do not write
        # the app presentation enum (manual = 2).
        payload = {"mode": mode, "manual": 1}
    elif option == ACTIVATION_TIME:
        # Observed time activation is wire mode 1 with manual 0. This is not
        # the library CleaningMode.MANUAL label used as a single-field write.
        payload = {"mode": 1, "manual": 0}
    else:
        payload = {"mode": 0, "manual": 0}
    return _flat(payload, frozenset({"mode", "manual"}))


def stored_volume(device: Device | None) -> int | None:
    """Return an explicit integer volumeLevel, even if it is outside 1–7."""
    configuration = _configuration(device)
    if configuration is None or "volume_level" not in configuration.model_fields_set:
        return None
    level = reported_measurement(device, "volume_level")
    if type(level) is not int:
        return None
    return level


def display_volume(device: Device | None) -> int | None:
    """Return a volume the app and library both bound to 1–7."""
    level = stored_volume(device)
    if level is None or level < VOLUME_MIN or level > VOLUME_MAX:
        return None
    return level


def _coerce_volume(level: object) -> int:
    if type(level) is int:
        return level
    if type(level) is float and math.isfinite(level) and level.is_integer():
        return int(level)
    raise SettingsWriteRefused("out_of_range")


def volume_payload(device: Device | None, level: object) -> dict[str, int]:
    """Return only ``volumeLevel`` for an integer from 1 to 7."""
    _require_online(device)
    if stored_volume(device) is None:
        raise SettingsWriteRefused("incomplete")
    coerced = _coerce_volume(level)
    if coerced < VOLUME_MIN or coerced > VOLUME_MAX:
        raise SettingsWriteRefused("out_of_range")
    return _flat({"volumeLevel": coerced}, frozenset({"volumeLevel"}))


# App panel-lock module, com.petnovations 1.8.253 function #18273.
# Getter slots: MULTIPLIER=5, MIN_AUTO_LOCK_ELEMENTARY=1, MAX_AUTO_LOCK_ELEMENTARY=6.
# elementary minutes are elementary * 5. Wire seconds are minutes * 60.
# Switch-off passes 0 through the same minutes-to-seconds path, so 0 disables.
# The PUT object is autoLock only. addDelay is a saga refresh wait, not a key.
AUTO_LOCK_MINUTES = (0, 5, 10, 15, 20, 25, 30)
AUTO_LOCK_SECONDS = tuple(minutes * 60 for minutes in AUTO_LOCK_MINUTES)


def stored_auto_lock_seconds(device: Device | None) -> int | None:
    """Return an explicit autoLock integer, including values outside the choices."""
    configuration = _configuration(device)
    if configuration is None or "auto_lock" not in configuration.model_fields_set:
        return None
    seconds = reported_measurement(device, "auto_lock")
    if type(seconds) is not int:
        return None
    return seconds


def display_auto_lock_minutes(device: Device | None) -> int | None:
    """Return minutes only for an exact app choice. Do not snap an unknown value."""
    seconds = stored_auto_lock_seconds(device)
    if seconds not in AUTO_LOCK_SECONDS:
        return None
    return seconds // 60


def _coerce_auto_lock_minutes(minutes: object) -> int:
    if type(minutes) is int:
        return minutes
    if type(minutes) is float and math.isfinite(minutes) and minutes.is_integer():
        return int(minutes)
    raise SettingsWriteRefused("not_a_choice")


def auto_lock_payload(device: Device | None, minutes: object) -> dict[str, int]:
    """Return only ``autoLock`` seconds for 0 or a 5-minute step through 30.

    0 is the app switch-off encoding. Other values are elementary 1–6 times
    300 seconds. This does not send addDelay, DND, catDelay, or schedule.
    """
    _require_online(device)
    if stored_auto_lock_seconds(device) is None:
        raise SettingsWriteRefused("incomplete")
    coerced = _coerce_auto_lock_minutes(minutes)
    if coerced not in AUTO_LOCK_MINUTES:
        raise SettingsWriteRefused("not_a_choice")
    return _flat({"autoLock": coerced * 60}, frozenset({"autoLock"}))


# App cat-activation module, com.petnovations 1.8.253.
# MIN/DEFAULT/MAX are 300/600/1800 (function #18350 slots 0/1/2).
# Snap is Math.round(value / 300) * 300, clamped to that range (#18308).
# The label is state.catDelay / 60, then '{catDelayValue} Min' (#18319).
# Save object is exactly {dndFrom, dndTo, catDelay} (#18377). When isDndOn
# is strictly false both clocks are ''. Otherwise a null selection copies
# configuration.dndFrom/dndTo with no conversion. fixConfigurationSchedules
# returns that object unchanged when schedule is absent (#15556).
CAT_DELAY_SECONDS = (300, 600, 900, 1200, 1500, 1800)
CAT_DELAY_MINUTES = tuple(seconds // 60 for seconds in CAT_DELAY_SECONDS)
# ASCII digits only. Unicode digits such as Arabic-Indic U+0661 are not a wire clock.
_WIRE_CLOCK = re.compile(
    r"^([01][0-9]|2[0-3]):([0-5][0-9]):([0-5][0-9])$",
    re.ASCII,
)


def stored_cat_delay_seconds(device: Device | None) -> int | None:
    """Return an explicit catDelay integer. The library default is not a reading."""
    configuration = _configuration(device)
    if configuration is None or "cat_delay" not in configuration.model_fields_set:
        return None
    seconds = reported_measurement(device, "cat_delay")
    if type(seconds) is not int:
        return None
    return seconds


def display_cat_delay_minutes(device: Device | None) -> int | None:
    """Return minutes only for an exact snapped choice. Do not snap unknowns."""
    seconds = stored_cat_delay_seconds(device)
    if seconds not in CAT_DELAY_SECONDS:
        return None
    return seconds // 60


def _coerce_cat_delay_minutes(minutes: object) -> int:
    if type(minutes) is int:
        return minutes
    if type(minutes) is float and math.isfinite(minutes) and minutes.is_integer():
        return int(minutes)
    raise SettingsWriteRefused("not_a_choice")


def _supported_unchanged_dnd(dnd_from: str, dnd_to: str) -> bool:
    """Pairs the app save would emit again without rewriting DND.

    Both empty matches isDndOn === false. Both HH:MM:SS matches a null
    selection copied from configuration, including equal clocks. A mixed
    pair is not echoed: the app would blank both, which is a DND change.
    """
    if dnd_from == "" and dnd_to == "":
        return True
    return (
        _WIRE_CLOCK.fullmatch(dnd_from) is not None
        and _WIRE_CLOCK.fullmatch(dnd_to) is not None
    )


def _unchanged_dnd(configuration: Any) -> tuple[str, str]:
    extra_map = getattr(configuration, "model_extra", None) or {}
    if not isinstance(extra_map, dict):
        raise SettingsWriteRefused("dnd_unknown")
    if "dndFrom" not in extra_map or "dndTo" not in extra_map:
        raise SettingsWriteRefused("dnd_unknown")
    dnd_from = extra_map["dndFrom"]
    dnd_to = extra_map["dndTo"]
    if type(dnd_from) is not str or type(dnd_to) is not str:
        raise SettingsWriteRefused("dnd_unknown")
    if not _supported_unchanged_dnd(dnd_from, dnd_to):
        raise SettingsWriteRefused("dnd_unknown")
    return dnd_from, dnd_to


def guard_cat_delay_before_read(device: Device | None, minutes: object) -> None:
    """Refuse a bad choice or a missing/offline cache before any read.

    DND shape is not judged here. The number entity reads devices next and
    passes that snapshot to ``cat_delay_payload``. This function does no I/O.
    """
    coerced = _coerce_cat_delay_minutes(minutes)
    if coerced not in CAT_DELAY_MINUTES:
        raise SettingsWriteRefused("not_a_choice")
    if device is None:
        raise SettingsWriteRefused("missing")
    if not device.is_online:
        raise SettingsWriteRefused("offline")


def cat_delay_payload(device: Device | None, minutes: object) -> dict[str, int | str]:
    """Return ``dndFrom``, ``dndTo``, and ``catDelay`` seconds.

    DND strings are the values on ``device``, copied without conversion.
    The number entity must pass the device just returned by
    ``get_devices()``; this helper does not fetch. Schedule, mode, volume,
    and nested siblings are omitted, matching the app save object. This
    does not call the library setter.
    """
    configuration = _require_online(device)
    if stored_cat_delay_seconds(device) is None:
        raise SettingsWriteRefused("incomplete")
    dnd_from, dnd_to = _unchanged_dnd(configuration)
    coerced = _coerce_cat_delay_minutes(minutes)
    if coerced not in CAT_DELAY_MINUTES:
        raise SettingsWriteRefused("not_a_choice")
    payload: dict[str, int | str] = {
        "dndFrom": dnd_from,
        "dndTo": dnd_to,
        "catDelay": coerced * 60,
    }
    if list(payload) != ["dndFrom", "dndTo", "catDelay"]:
        raise SettingsWriteRefused("unsupported")
    if payload["dndFrom"] is not dnd_from or payload["dndTo"] is not dnd_to:
        raise SettingsWriteRefused("unsupported")
    if type(payload["catDelay"]) is not int:
        raise SettingsWriteRefused("unsupported")
    return payload


def _flat(payload: dict[str, int], allowed: frozenset[str]) -> dict[str, int]:
    if set(payload) != allowed or any(type(value) is not int for value in payload.values()):
        raise SettingsWriteRefused("unsupported")
    return dict(payload)
