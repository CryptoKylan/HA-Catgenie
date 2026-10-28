"""CatGenie client with tolerance for real-world payload quirks."""

from __future__ import annotations

from typing import Any

from catgenie import CatGenieClient, Device
from catgenie.const import ENDPOINT_DEVICES


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


class HomeAssistantCatGenieClient(CatGenieClient):
    """CatGenieClient that normalises device payloads before validating them."""

    async def get_devices(self) -> list[Device]:
        """Get all devices on the account."""
        data = await self._request(
            "GET",
            ENDPOINT_DEVICES,
            params={"useFleetIndexAndGetRealConnectivity": "true"},
        )
        return [
            Device.model_validate(_normalize_thing(thing))
            for thing in data.get("thingList", [])
        ]
