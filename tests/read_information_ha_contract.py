"""Real Home Assistant 2026.10.4 startup contract for the read-only lane.

Not collected by unittest. The regression test runs this file. It starts a
local Home Assistant, loads this candidate, and refreshes through the real
coordinator. The client is patched. AsyncSession.request refuses the network.
Fixtures are SYNTHETIC. This is not firmware acceptance and not a live display.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
from pathlib import Path
from types import MappingProxyType
from unittest.mock import AsyncMock, patch

ROOT = Path(os.environ.get("CATGENIE_READ_INFORMATION_ROOT", Path(__file__).resolve().parents[1]))
DEPENDENCY = os.environ.get("CATGENIE_TEST_DEPENDENCY")
if DEPENDENCY:
    sys.path.insert(0, DEPENDENCY)
sys.path.insert(0, str(ROOT))

from curl_cffi.requests import AsyncSession  # noqa: E402
from homeassistant.config_entries import ConfigEntry, ConfigEntryState  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.exceptions import ConfigEntryAuthFailed  # noqa: E402
from homeassistant.helpers import device_registry as dr  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402
from homeassistant.helpers.update_coordinator import UpdateFailed  # noqa: E402

FIXTURE = "SYNTHETIC"
MANUFACTURER_ID = "SYN-UNIT"
INSTALLED_FW = "8.7.205R"
NOTES = "SYNTHETIC release notes"
THING = {
    "_fixture": FIXTURE,
    "manufacturerId": MANUFACTURER_ID,
    "name": f"{FIXTURE}-{MANUFACTURER_ID}",
    "macAddress": "aa:bb:cc:dd:ee:ff",
    "hwRevision": "1",
    "fwVersion": INSTALLED_FW,
    "reportedStatus": "connected",
    "operationStatus": {"state": 0, "progress": 255, "error": ""},
    "activeErrors": [],
}


def _refuse_network(*_args, **_kwargs):
    raise RuntimeError("startup contract refused a network request")


AsyncSession.request = _refuse_network


async def _refresh(self):
    self.credentials.access_token = "synthetic-access"
    self.credentials.token_expiration = time.time() + 3600


CALLS: list[dict] = []


async def _request(self, method, path, body=None, params=None):
    CALLS.append(
        {
            "method": method,
            "path": path,
            "params": None if params is None else dict(params),
            "has_body": body is not None,
        }
    )
    if str(method).upper() != "GET":
        raise RuntimeError(f"refused {method} {path}")
    if path == "device/device/v2":
        return {"thingList": [THING]}
    if path == "notification/v1/push/user":
        if params:
            raise RuntimeError("feed query refused")
        return {"userId": "synthetic-user", "notifications": []}
    if path == "device/update/versions/comments":
        if params != {"name": INSTALLED_FW}:
            raise RuntimeError(f"bad notes query {params}")
        return {"comments": NOTES}
    if path == "device/history/account/pet/statistics":
        raise RuntimeError("history read is not this contract")
    raise RuntimeError(f"refused {method} {path}")


def _patch_client() -> None:
    from catgenie.auth import CatGenieAuth
    from catgenie.client import CatGenieClient

    CatGenieAuth.refresh = _refresh
    CatGenieClient._request = _request


async def _startup(config_dir: Path) -> None:
    # Observe actual HA lifecycle ownership, not a fake ConfigEntry cleanup.
    closed_sessions = []
    cancelled_trackers = []
    from homeassistant.helpers import event as ha_event

    original_close = AsyncSession.close
    original_track = ha_event.async_track_time_interval

    async def _record_close(session):
        closed_sessions.append(session)
        await original_close(session)

    def _record_track(*args, **kwargs):
        cancel = original_track(*args, **kwargs)
        def _cancel():
            cancelled_trackers.append(cancel)
            cancel()
        return _cancel

    AsyncSession.close = _record_close
    ha_event.async_track_time_interval = _record_track
    component = ROOT / "custom_components" / "catgenie"
    custom = config_dir / "custom_components"
    custom.mkdir(parents=True)
    (custom / "catgenie").symlink_to(component)
    hass = HomeAssistant(str(config_dir))
    from homeassistant import loader
    from homeassistant.config_entries import ConfigEntries
    from homeassistant.helpers import area_registry as ar

    from homeassistant.helpers import frame as ha_frame

    loader.async_setup(hass)
    hass.config_entries = ConfigEntries(hass, {})
    await hass.config_entries.async_initialize()
    ha_frame.async_setup(hass)
    # Older HA initializes the registry in async_load; newer HA has setup too.
    if hasattr(dr, "async_setup"):
        dr.async_setup(hass)
    await ar.async_load(hass)
    await dr.async_load(hass)
    await er.async_load(hass)
    hass.config.skip_pip = True
    _patch_client()
    entry = ConfigEntry(
        data={
            "refresh_token": "synthetic-refresh",
            "account_id": "synthetic-account",
            "user_id": "synthetic-user",
            "tenant_id": "synthetic-tenant",
        },
        discovery_keys=MappingProxyType({}),
        domain="catgenie",
        minor_version=1,
        options={},
        source="user",
        subentries_data=None,
        title="SYNTHETIC CatGenie",
        unique_id="synthetic-read-information",
        version=1,
    )
    await hass.config_entries.async_add(entry)
    await hass.async_block_till_done(wait_background_tasks=True)
    if entry.state is not ConfigEntryState.LOADED:
        raise SystemExit(f"entry state {entry.state} reason={entry.reason}")
    from custom_components.catgenie.coordinator import CatGenieCoordinator
    from custom_components.catgenie.read_information_coordinator import (
        CatGenieReadCoordinator,
    )
    from custom_components.catgenie import PLATFORMS
    from homeassistant.const import Platform

    if not isinstance(entry.runtime_data, CatGenieCoordinator):
        raise SystemExit(f"runtime_data is {type(entry.runtime_data).__name__}")
    reader = getattr(entry.runtime_data, "read_information", None)
    if not isinstance(reader, CatGenieReadCoordinator):
        raise SystemExit("read coordinator was not bound")
    if reader.update_interval is not None:
        raise SystemExit(f"reader schedules itself: {reader.update_interval}")
    if entry.runtime_data.update_interval.total_seconds() < 60:
        raise SystemExit("device poll was shortened")
    if Platform.UPDATE in PLATFORMS:
        raise SystemExit("update platform was registered")
    if (component / "update.py").exists():
        raise SystemExit("update.py must not exist")

    registry = er.async_get(hass)
    wanted = {
        f"{MANUFACTURER_ID}_latest_notification",
        f"{MANUFACTURER_ID}_announced_firmware",
        f"{MANUFACTURER_ID}_firmware_release_notes",
        f"{MANUFACTURER_ID}_operation_state",
    }
    found = {
        item.unique_id: item
        for item in registry.entities.values()
        if item.unique_id in wanted
    }
    missing = wanted - set(found)
    if missing:
        raise SystemExit(f"missing entities {sorted(missing)}")
    states = {}
    for unique_id, item in found.items():
        state = hass.states.get(item.entity_id)
        if state is None:
            raise SystemExit(f"no state for {unique_id}")
        states[unique_id] = state
        dumped = str(state.as_dict())
        if "synthetic-user" in dumped or "userId" in dumped:
            raise SystemExit(f"account id leaked onto {unique_id}")
    latest = states[f"{MANUFACTURER_ID}_latest_notification"]
    announced = states[f"{MANUFACTURER_ID}_announced_firmware"]
    notes = states[f"{MANUFACTURER_ID}_firmware_release_notes"]
    if latest.state != "unknown":
        raise SystemExit(f"empty feed state {latest.state}")
    if announced.state != "unknown":
        raise SystemExit(f"no type-24 item displayed {announced.state}")
    if announced.state == INSTALLED_FW:
        raise SystemExit("installed firmware was displayed as announced")
    if notes.state != "available":
        raise SystemExit(f"notes state {notes.state} attrs={notes.attributes}")
    if notes.attributes.get("installed_notes") != NOTES:
        raise SystemExit("installed notes were not the fetched comments string")
    if notes.attributes.get("query_key") != "name":
        raise SystemExit("notes query key was not name")
    if latest.attributes.get("response_count") != 0:
        raise SystemExit(f"response count {latest.attributes.get('response_count')}")
    if latest.attributes.get("complete_history") is not False:
        raise SystemExit("empty feed was treated as a complete history")
    registry = dr.async_get(hass)
    if hasattr(registry, "async_get_devices"):
        devices = registry.async_get_devices(identifiers={("catgenie", MANUFACTURER_ID)})
    else:
        device = registry.async_get_device(identifiers={("catgenie", MANUFACTURER_ID)})
        devices = [] if device is None else [device]
    if len(devices) != 1 or devices[0].sw_version != INSTALLED_FW:
        raise SystemExit(
            f"device sw_version {[getattr(item, 'sw_version', None) for item in devices]}"
        )
    feed_calls = [row for row in CALLS if row["path"] == "notification/v1/push/user"]
    note_calls = [row for row in CALLS if row["path"] == "device/update/versions/comments"]
    if len(feed_calls) != 1 or feed_calls[0]["params"] is not None:
        raise SystemExit(f"feed calls {feed_calls}")
    if note_calls != [{"method": "GET", "path": "device/update/versions/comments", "params": {"name": INSTALLED_FW}, "has_body": False}]:
        raise SystemExit(f"notes calls {note_calls}")
    forbidden = [
        row["path"]
        for row in CALLS
        if row["path"].startswith("device/update/")
        and row["path"] != "device/update/versions/comments"
        or "push/settings" in row["path"]
        or row["method"] != "GET"
    ]
    if forbidden:
        raise SystemExit(f"forbidden calls {forbidden}")
    print("STARTUP_LOADED")
    print("ENTITIES_REGISTERED")

    started: list[str] = []
    reauth_hooks = [name for name in ("async_start_reauth_if_available", "async_start_reauth")
                    if hasattr(entry, name)]
    if not reauth_hooks:
        raise SystemExit("No known actual HA reauthentication hook")
    for hook_name in reauth_hooks:
        original = getattr(entry, hook_name)

        def _record(*args, _original=original, **kwargs):
            started.append("reauth")
            return _original(*args, **kwargs)

        setattr(entry, hook_name, _record)
    device_interval = entry.runtime_data.update_interval

    class AuthFail:
        async def _request(self, method, path, body=None, params=None):
            raise ConfigEntryAuthFailed("synthetic auth failure")

    isolated = CatGenieReadCoordinator(hass, entry, AuthFail(), entry.runtime_data)
    await isolated.async_refresh()
    if started:
        raise SystemExit("feed auth failure started reauth")
    if not isinstance(isolated.last_exception, UpdateFailed):
        raise SystemExit(f"isolation exception {type(isolated.last_exception).__name__}")
    if isinstance(isolated.last_exception, ConfigEntryAuthFailed):
        raise SystemExit("auth failure escaped as ConfigEntryAuthFailed")
    if entry.runtime_data.update_interval != device_interval:
        raise SystemExit("device poll interval changed after feed failure")
    if hass.states.get(found[f"{MANUFACTURER_ID}_operation_state"].entity_id).state in {
        "unavailable",
        "unknown",
    }:
        raise SystemExit("device sensor became unavailable after feed failure")

    from custom_components.catgenie.read_information import (
        KnownDevice,
        load_read_information,
    )

    class NotesFail:
        async def _request(self, method, path, body=None, params=None):
            if path == "notification/v1/push/user":
                return {"notifications": []}
            raise RuntimeError("synthetic notes failure")

    partial = await load_read_information(
        NotesFail(), (KnownDevice(MANUFACTURER_ID, INSTALLED_FW),)
    )
    if partial.feed.response_count != 0 or partial.notes[0].error != "RuntimeError":
        raise SystemExit("notes failure erased the feed or was not recorded")
    if partial.notes[0].comments is not None:
        raise SystemExit("failed notes query produced comments")
    from custom_components.catgenie.read_sensors import notes_available

    if notes_available(partial, MANUFACTURER_ID, INSTALLED_FW):
        raise SystemExit("notes entity stayed available after every notes query failed")
    print("COORDINATOR_ISOLATED")

    from custom_components.catgenie.read_information import (
        NotesResult,
        ReadSnapshot,
        parse_feed,
    )
    from custom_components.catgenie.read_sensors import (
        announced_attributes,
        announced_state,
        latest_attributes,
        latest_state,
        notes_attributes,
    )

    def _notice(type_code, version=None):
        payload = {"type": type_code, "parentDeviceId": MANUFACTURER_ID}
        if version is not None:
            payload["version"] = version
        return {
            "creationTime": "2026-10-31T12:00:00Z",
            "data": json.dumps(payload),
        }

    visited = _notice(20)
    message = _notice(21)
    for order in ([visited, message], [message, visited]):
        feed = parse_feed({"notifications": order}, [MANUFACTURER_ID])
        snapshot = ReadSnapshot(feed, (), ())
        attrs = latest_attributes(snapshot, MANUFACTURER_ID)
        if latest_state(snapshot, MANUFACTURER_ID) != "unknown":
            raise SystemExit("equal-time notifications published an order-chosen type")
        if attrs.get("latest_selection") != "ambiguous" or "type_name" in attrs or "type" in attrs:
            raise SystemExit(f"latest notification hid the tie {attrs}")
    firmware_a = _notice(24, "SYN-A")
    firmware_b = _notice(24, "SYN-B")
    tied = parse_feed({"notifications": [firmware_a, firmware_b]}, [MANUFACTURER_ID])
    tied_snapshot = ReadSnapshot(
        tied,
        (
            NotesResult("SYN-A", "notes-a", None),
            NotesResult("SYN-B", "notes-b", None),
            NotesResult(INSTALLED_FW, NOTES, None),
        ),
        (INSTALLED_FW, "SYN-A", "SYN-B"),
    )
    if announced_state(tied_snapshot, MANUFACTURER_ID) != "unknown":
        raise SystemExit("ambiguous firmware was published as a version")
    announced = announced_attributes(tied_snapshot, MANUFACTURER_ID)
    if (
        announced.get("latest_selection") != "ambiguous"
        or announced.get("announcement") != "ambiguous"
        or announced.get("unknown_means_no_announcement") is not False
        or "announced_version" in announced
    ):
        raise SystemExit(f"announced attributes hid the tie {announced}")
    tied_notes = notes_attributes(tied_snapshot, MANUFACTURER_ID, INSTALLED_FW)
    if (
        tied_notes.get("installed_notes") != NOTES
        or "announced_version" in tied_notes
        or "announced_notes" in tied_notes
    ):
        raise SystemExit(f"ambiguous announcement labeled notes {tied_notes}")
    print("AMBIGUOUS_SELECTION_NOT_AUTHORITATIVE")

    calls_before_device_update = len(CALLS)
    device_interval = entry.runtime_data.update_interval
    device = entry.runtime_data.data[MANUFACTURER_ID]
    old_fw = device.fw_version
    note_entity_id = notes.entity_id

    entry.runtime_data.async_set_updated_data(dict(entry.runtime_data.data))
    await hass.async_block_till_done()
    unchanged = hass.states.get(note_entity_id)
    if len(CALLS) != calls_before_device_update:
        raise SystemExit(f"unchanged firmware issued a read {CALLS[calls_before_device_update:]}")
    if unchanged.state != "available" or unchanged.attributes.get("installed_notes") != NOTES:
        raise SystemExit(
            f"unchanged firmware disturbed notes {unchanged.state} {unchanged.attributes}"
        )
    if unchanged.attributes.get("installed_version") != INSTALLED_FW:
        raise SystemExit("unchanged firmware rewrote the installed version")

    device.fw_version = "SYN-NEW-INSTALLED"
    entry.runtime_data.async_set_updated_data(dict(entry.runtime_data.data))
    await hass.async_block_till_done()
    changed = hass.states.get(note_entity_id)
    from custom_components.catgenie.read_sensors import notes_attributes as pure_notes_attributes
    from custom_components.catgenie.read_sensors import notes_state as pure_notes_state

    pure_state = pure_notes_state(reader.data, MANUFACTURER_ID, device.fw_version)
    pure_attrs = pure_notes_attributes(reader.data, MANUFACTURER_ID, device.fw_version)
    if pure_state != "unknown" or "installed_notes" in pure_attrs:
        raise SystemExit(f"pure rendering no longer matches the defect model {pure_state} {pure_attrs}")
    if changed.state != pure_state or ("installed_notes" in changed.attributes) != (
        "installed_notes" in pure_attrs
    ):
        raise SystemExit(
            "firmware change left installed notes labeled until the next reader poll: "
            f"state={changed.state} installed_version={changed.attributes.get('installed_version')} "
            f"installed_notes_present={'installed_notes' in changed.attributes} pure={pure_state}"
        )
    if changed.attributes.get("installed_version") != "SYN-NEW-INSTALLED":
        raise SystemExit(
            f"installed version was not recomputed {changed.attributes.get('installed_version')}"
        )
    if "installed_notes" in changed.attributes or changed.state != "unknown":
        raise SystemExit("old installed notes remained authoritative after firmware change")
    if len(CALLS) != calls_before_device_update:
        raise SystemExit(f"firmware change issued a read {CALLS[calls_before_device_update:]}")
    if entry.runtime_data.update_interval != device_interval or reader.update_interval is not None:
        raise SystemExit("firmware notification changed device poll or reader scheduling")
    operation = hass.states.get(found[f"{MANUFACTURER_ID}_operation_state"].entity_id)
    if operation.state in {"unavailable", "unknown"}:
        raise SystemExit("device sensor changed after the notes recomputation")

    device.fw_version = old_fw
    entry.runtime_data.async_set_updated_data(dict(entry.runtime_data.data))
    await hass.async_block_till_done()
    restored = hass.states.get(note_entity_id)
    if restored.state != "available" or restored.attributes.get("installed_notes") != NOTES:
        raise SystemExit("already fetched notes were not restored from current firmware without a read")
    if len(CALLS) != calls_before_device_update:
        raise SystemExit("restoring firmware issued a read")

    from homeassistant.helpers.entity_platform import async_get_platforms

    read_entities = [
        entity
        for platform in async_get_platforms(hass, "catgenie")
        for entity in platform.entities.values()
        if type(entity).__name__ == "CatGenieReadSensor"
    ]
    notes_entity = next(
        entity
        for entity in read_entities
        if entity.unique_id == f"{MANUFACTURER_ID}_firmware_release_notes"
    )
    listeners = [callback for callback, _context in entry.runtime_data._listeners.values()]
    handler = getattr(notes_entity, "_handle_device_coordinator_update", None)
    if handler is None or handler not in listeners:
        raise SystemExit("notes sensor is not subscribed to the device coordinator")
    await notes_entity.async_remove()
    await hass.async_block_till_done()
    listeners = [callback for callback, _context in entry.runtime_data._listeners.values()]
    if handler in listeners:
        raise SystemExit("device coordinator listener survived notes entity removal")
    entry.runtime_data.async_set_updated_data(dict(entry.runtime_data.data))
    await hass.async_block_till_done()
    if len(CALLS) != calls_before_device_update:
        raise SystemExit("removed notes listener issued a read")
    print("FIRMWARE_CHANGE_DROPPED_OLD_NOTES")
    print("DEVICE_LISTENER_REMOVED")

    session = entry.runtime_data.client._session
    from custom_components.catgenie.client import HomeAssistantCatGenieAuth
    if not isinstance(entry.runtime_data.client._auth, HomeAssistantCatGenieAuth):
        raise SystemExit("setup did not use single-flight auth")
    if entry.runtime_data.client._auth.credentials is not entry.runtime_data.client._credentials:
        raise SystemExit("setup did not share credentials")

    started_background = asyncio.Event()
    async def _blocked_background():
        started_background.set()
        await asyncio.Event().wait()
    task = entry.async_create_background_task(hass, _blocked_background(), "synthetic-lifecycle")
    await started_background.wait()
    trackers_before = len(cancelled_trackers)
    if not await hass.config_entries.async_unload(entry.entry_id):
        raise SystemExit("entry unload failed")
    if entry.state is not ConfigEntryState.NOT_LOADED or closed_sessions.count(session) != 1:
        raise SystemExit("unload did not close its session exactly once")
    if not task.cancelled() or len(cancelled_trackers) - trackers_before < 2:
        raise SystemExit("unload retained background work or interval trackers")
    if hass.services.has_service("catgenie", "set_schedule"):
        raise SystemExit("last-entry unload retained actions")
    print("UNLOAD_CLOSED_SESSION_CANCELLED_TASK_AND_TRACKERS")

    from catgenie import CatGenieAPIError
    from custom_components.catgenie.client import HomeAssistantCatGenieClient
    from custom_components.catgenie import services

    # Reuse the actual registered entry; HA executes failure cleanup itself.
    closes_before = len(closed_sessions)
    with patch.object(HomeAssistantCatGenieClient, "get_devices", AsyncMock(side_effect=CatGenieAPIError("synthetic setup failure"))):
        await hass.config_entries.async_setup(entry.entry_id)
    if entry.state is not ConfigEntryState.SETUP_RETRY or len(closed_sessions) != closes_before + 1:
        raise SystemExit("first-refresh setup failure did not close the session")
    await hass.config_entries.async_unload(entry.entry_id)
    print("FIRST_REFRESH_FAILURE_CLOSED_SESSION")

    closes_before = len(closed_sessions)
    with patch.object(services, "async_setup_actions", side_effect=RuntimeError("synthetic action setup failure")):
        await hass.config_entries.async_setup(entry.entry_id)
    if entry.state is not ConfigEntryState.SETUP_ERROR or len(closed_sessions) != closes_before + 1:
        raise SystemExit("action setup failure did not close the session")
    from homeassistant.helpers.entity_platform import async_get_platforms
    if any(platform.entities for platform in async_get_platforms(hass, "catgenie")):
        raise SystemExit("action setup failure retained platform entities")
    print("ACTION_SETUP_FAILURE_UNLOADED_PLATFORMS_CLOSED_SESSION")
    await hass.async_stop()


def main() -> int:
    import tempfile
    temporary = tempfile.TemporaryDirectory(prefix="catgenie-read-information-", dir=os.environ.get("TMPDIR"))
    config_dir = Path(temporary.name)
    try:
        asyncio.run(_startup(config_dir))
    except Exception:
        traceback.print_exc()
        return 1
    finally:
        temporary.cleanup()
    print("HA_CONTRACT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
