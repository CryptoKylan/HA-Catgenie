"""CatGenie client with tolerance for real-world payload quirks."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import logging
from typing import Any

from pydantic import ValidationError
from catgenie import CatGenieAPIError, CatGenieAuth, CatGenieClient, Credentials, Device
from catgenie.const import ENDPOINT_DEVICES

from .operation_state import TolerantDevice


def _schedule_entry(entry: Any) -> dict[str, Any]:
    """Turn a schedule entry into the dict shape the library's model expects.

    Real devices report schedule entries as plain time strings such as
    "06:00:00", while the library's ScheduleEntry model only accepts dicts.
    The original string is kept under "time".
    """
    if isinstance(entry, dict):
        return entry
    if isinstance(entry, str):
        result: dict[str, Any] = {"time": entry}
        parts = entry.split(":")
        try:
            result["hour"] = int(parts[0])
            result["minute"] = int(parts[1])
        except (ValueError, IndexError):
            pass
        return result
    return {"value": entry}


def _normalize_thing(thing: dict[str, Any]) -> dict[str, Any]:
    """Fix known payload quirks in one device before validation."""
    configuration = thing.get("configuration")
    if isinstance(configuration, dict):
        schedule = configuration.get("schedule")
        if isinstance(schedule, list):
            configuration["schedule"] = [_schedule_entry(e) for e in schedule]
    return thing


class HomeAssistantCatGenieAuth(CatGenieAuth):
    """Serialize refresh on the shared auth/session without changing the library.

    A waiter reuses a successful overlapping refresh only while its token is
    still valid. A non-overlapping explicit refresh (including a 401 retry)
    still refreshes. Exceptions and cancellation release the lock normally.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._refresh_lock = asyncio.Lock()
        self._refresh_generation = 0

    async def refresh(self) -> Credentials:
        generation = self._refresh_generation
        async with self._refresh_lock:
            if generation != self._refresh_generation and not self.credentials.is_token_expired:
                return self.credentials
            credentials = await super().refresh()
            self._refresh_generation += 1
            return credentials


class HomeAssistantCatGenieClient(CatGenieClient):
    """CatGenieClient that normalises device payloads before validating them."""

    async def get_devices(self) -> list[Device]:
        """Get all devices on the account."""
        data = await self._request(
            "GET",
            ENDPOINT_DEVICES,
            params={"useFleetIndexAndGetRealConnectivity": "true"},
        )
        # A missing/malformed envelope is a failed poll, not a healthy empty
        # account. Validate records independently without retaining stale data.
        if not isinstance(data, dict) or not isinstance(data.get("thingList"), list):
            raise CatGenieAPIError("Invalid device-list response") from None
        things = data["thingList"]
        devices: list[Device] = []
        rejected: dict[str, int] = {}
        for thing in things:
            try:
                if not isinstance(thing, dict):
                    raise ValueError("Invalid device record")
                # Never infer a device identity for an unparseable record.
                identity = thing.get("manufacturerId")
                if type(identity) is not str or not identity.strip():
                    raise ValueError("Missing device identity")
                devices.append(TolerantDevice.model_validate(_normalize_thing(deepcopy(thing))))
            except (ValidationError, ValueError) as err:
                name = type(err).__name__
                rejected[name] = rejected.get(name, 0) + 1
        # Counts and exception class names only: no input, paths or error text.
        for name, count in rejected.items():
            logging.getLogger(__name__).warning("Quarantined %d device report(s): %s", count, name)
        if things and not devices:
            raise CatGenieAPIError("No valid device reports") from None
        return devices
