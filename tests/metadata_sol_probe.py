"""Real Home Assistant Future and cold-handler probes for the metadata repairs.

Not collected by unittest discovery. The regression test runs this file.
It uses the installed Home Assistant executor, not a coroutine fake, and an
audit hook for loop-thread zoneinfo opens. It does not call a device.
The concurrent section uses actual ZoneInfo and a barrier after construction.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from homeassistant.core import HomeAssistant
from custom_components.catgenie import action_permissions
from custom_components.catgenie import dnd_actions as dnd
from custom_components.catgenie import schedule_actions as schedule
from custom_components.catgenie import services


class StopProbe(Exception):
    """Sentinel raised by the resolver before any vendor read or write."""


def _hass(name: str) -> HomeAssistant:
    return HomeAssistant(str(Path(__file__).parent / f"ha-config-{name}"))


def _reset_loader() -> None:
    schedule._IANA_ZONES = None
    schedule._LOAD_FUTURE = None
    schedule._ZONE_MISSES.clear()
    dnd._ZONE_MISSES.clear()


async def _occupy_executor():
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=1, thread_name_prefix="sol-probe"))
    entered, release = threading.Event(), threading.Event()

    def occupy() -> None:
        entered.set()
        release.wait(10)

    blocker = loop.run_in_executor(None, occupy)
    while not entered.is_set():
        await asyncio.sleep(0)
    return blocker, release


async def cancellation_probe() -> dict:
    blocker, release = await _occupy_executor()
    hass_a = _hass("entry-a")
    hass_b = _hass("entry-b")
    _reset_loader()
    schedule.prime_iana_zones(hass_a)
    shared = schedule._LOAD_FUTURE
    if type(shared).__name__ != "Future" or asyncio.iscoroutine(shared):
        raise SystemExit(f"expected a real Future, got {type(shared).__name__}")
    entry_a = asyncio.create_task(schedule.async_iana_zones(hass_a))
    entry_b = asyncio.create_task(schedule.async_iana_zones(hass_b))
    await asyncio.sleep(0)
    if schedule._LOAD_FUTURE is not shared:
        raise SystemExit("entries did not share the loader Future")
    entry_a.cancel()
    await asyncio.sleep(0)
    still_shared = schedule._LOAD_FUTURE is shared and not shared.cancelled()
    release.set()
    outcomes = await asyncio.gather(entry_a, entry_b, return_exceptions=True)
    await blocker
    await asyncio.sleep(0)
    reloaded = await schedule.async_iana_zones(_hass("entry-reload"))
    concurrent = {
        "executor_return_type": type(shared).__name__,
        "coroutine_fake": asyncio.iscoroutine(shared),
        "waiters": [
            type(item).__name__ if not isinstance(item, frozenset) else "set"
            for item in outcomes
        ],
        "caller_cancelled": type(outcomes[0]).__name__ == "CancelledError",
        "other_entry_loaded": isinstance(outcomes[1], frozenset) and "America/Adak" in outcomes[1],
        "shared_cancelled": shared.cancelled(),
        "reference_preserved_while_running": still_shared,
        "cache_loaded": schedule._IANA_ZONES is not None,
        "reload_loaded": "America/Adak" in reloaded,
    }
    if not (
        concurrent["caller_cancelled"]
        and concurrent["other_entry_loaded"]
        and not concurrent["shared_cancelled"]
        and concurrent["reference_preserved_while_running"]
        and concurrent["cache_loaded"]
        and concurrent["reload_loaded"]
    ):
        raise SystemExit(f"concurrent waiters failed: {concurrent}")

    blocker, release = await _occupy_executor()
    _reset_loader()
    hass_setup = _hass("setup")
    schedule.prime_iana_zones(hass_setup)
    queued = schedule._LOAD_FUTURE
    waiter = asyncio.create_task(schedule.async_iana_zones(hass_setup))
    await asyncio.sleep(0)
    queued_cancel = queued.cancel()
    waiter_outcome = await asyncio.gather(waiter, return_exceptions=True)
    release.set()
    await blocker
    await asyncio.sleep(0)
    hass_other = _hass("other-entry")
    schedule.prime_iana_zones(hass_other)
    recovered = schedule._LOAD_FUTURE
    loaded = await schedule.async_iana_zones(hass_other)
    queued_job = {
        "cancel_returned": queued_cancel,
        "waiter": type(waiter_outcome[0]).__name__,
        "reference_cleared_or_replaced": schedule._LOAD_FUTURE is not queued,
        "recovered_not_cancelled": recovered is not None and not recovered.cancelled(),
        "other_entry_loaded": "America/Adak" in loaded,
        "cache_loaded": schedule._IANA_ZONES is not None,
    }
    if not (
        queued_job["cancel_returned"] is True
        and queued_job["waiter"] == "CancelledError"
        and queued_job["reference_cleared_or_replaced"]
        and queued_job["recovered_not_cancelled"]
        and queued_job["other_entry_loaded"]
        and queued_job["cache_loaded"]
    ):
        raise SystemExit(f"queued job cancellation failed: {queued_job}")

    _reset_loader()
    original = schedule.available_timezones

    def fail() -> frozenset[str]:
        raise OSError("synthetic tzdata failure")

    schedule.available_timezones = fail
    cleared = False
    try:
        await schedule.async_iana_zones(_hass("failure"))
    except OSError:
        cleared = schedule._LOAD_FUTURE is None
    finally:
        schedule.available_timezones = original
    retried = await schedule.async_iana_zones(_hass("failure-retry"))
    failure = {"failed_future_cleared": cleared, "retry_loaded": "America/Adak" in retried}
    if not (cleared and failure["retry_loaded"]):
        raise SystemExit(f"ordinary loader failure retry regressed: {failure}")
    return {"concurrent": concurrent, "queued_job": queued_job, "failure_recovery": failure}


def _audit(loop_thread: int, opens: list[str]):
    active = {"on": False}

    def audit(event: str, args) -> None:
        if (
            active["on"]
            and event == "open"
            and threading.get_ident() == loop_thread
            and args
            and isinstance(args[0], str)
            and "zoneinfo/" in args[0]
        ):
            opens.append(args[0])

    sys.addaudithook(audit)
    return active


async def cold_handler_probe() -> dict:
    schedule._LOAD_FUTURE = None
    schedule._IANA_ZONES = None
    schedule._ZONE_MISSES.clear()
    dnd._ZONE_MISSES.clear()
    schedule._load_iana_zones()
    ZoneInfo.clear_cache()
    loop_thread = threading.get_ident()
    opens: list[str] = []
    active = _audit(loop_thread, opens)

    async def permissions(*_args) -> None:
        return None

    action_permissions.async_check_device_control = permissions
    calls = {"schedule": 0, "dnd": 0, "writes": 0}
    original_schedule_writer = schedule._put_schedule
    original_dnd_writer = dnd._apply_dnd_locked

    async def forbidden_write(*_args, **_kwargs):
        calls['writes'] += 1
        raise AssertionError('cold probe must never reach a writer')

    schedule._put_schedule = forbidden_write
    dnd._apply_dnd_locked = forbidden_write

    async def schedule_resolve(*_args):
        calls["schedule"] += 1
        raise StopProbe()

    def dnd_resolve(*_args):
        calls["dnd"] += 1
        raise StopProbe()

    dnd.resolve_target = dnd_resolve
    results = {}
    for name, zone in (("schedule", "America/Adak"), ("dnd", "Australia/Lord_Howe")):
        ZoneInfo.clear_cache()
        opens.clear()
        active["on"] = True
        try:
            if name == "schedule":
                await schedule.async_handle_set_schedule(
                    SimpleNamespace(
                        data={
                            "device_id": "test",
                            "times": [{"time": "12:00:00"}],
                            "zone": zone,
                            "reference_date": "2026-10-31",
                        },
                        hass=None,
                    ),
                    schedule_resolve,
                )
            else:
                await services.async_handle_set_do_not_disturb(
                    SimpleNamespace(
                        data={
                            "device_id": "test",
                            "enabled": True,
                            "start_time": "12:00:00",
                            "end_time": "18:00:00",
                            "timezone": zone,
                            "reference_date": "2026-10-31",
                        },
                        hass=None,
                    )
                )
            outcome = "returned"
        except Exception as exc:
            outcome = type(exc).__name__
        finally:
            active["on"] = False
        results[name] = {
            "loop_thread_zoneinfo_opens": list(opens),
            "stopped_at": outcome,
            "resolver_calls": calls[name],
            "writer_calls": calls['writes'],
        }
        expected_outcome = 'ScheduleActionError' if name == 'schedule' else 'StopProbe'
        if opens or outcome != expected_outcome or calls[name] != 1 or calls['writes'] != 0:
            raise SystemExit(f"cold handler still does loop zoneinfo I/O or missed the sentinel: {results[name]}")

    # Authorization must fail before even a cold invalid-zone request resolves.
    from homeassistant.exceptions import Unauthorized

    async def unauthorized(*_args):
        raise Unauthorized()

    action_permissions.async_check_device_control = unauthorized
    calls['schedule'] = calls['dnd'] = 0
    ZoneInfo.clear_cache()
    for name in ('schedule', 'dnd'):
        call = SimpleNamespace(data={'device_id': 'test', 'zone': 'America/Not_A_Zone',
                                     'timezone': 'America/Not_A_Zone'}, hass=None)
        try:
            if name == 'schedule':
                await schedule.async_handle_set_schedule(call, schedule_resolve)
            else:
                await services.async_handle_set_do_not_disturb(call)
        except Unauthorized:
            pass
        else:
            raise SystemExit(f'{name} did not refuse unauthorized request')
    if calls != {'schedule': 0, 'dnd': 0, 'writes': 0}:
        raise SystemExit(f'unauthorized request reached resolver/writer: {calls}')
    results['unauthorized'] = dict(calls)
    action_permissions.async_check_device_control = permissions

    opens.clear()
    active["on"] = True
    calls["schedule"] = 0
    calls["dnd"] = 0
    refused = {}
    try:
        try:
            await schedule.async_handle_set_schedule(
                SimpleNamespace(
                    data={
                        "device_id": "test",
                        "times": [{"time": "02:30:00"}, {"time": "12:00:00"}],
                        "zone": "America/New_York",
                        "reference_date": "2026-03-08",
                    },
                    hass=None,
                ),
                schedule_resolve,
            )
        except schedule.ScheduleActionRefused as exc:
            refused["gap"] = exc.code
        try:
            await schedule.async_handle_set_schedule(
                SimpleNamespace(
                    data={
                        "device_id": "test",
                        "times": [{"time": "01:30:00"}, {"time": "12:00:00"}],
                        "zone": "America/New_York",
                        "reference_date": "2026-11-01",
                    },
                    hass=None,
                ),
                schedule_resolve,
            )
        except schedule.ScheduleActionRefused as exc:
            refused["fold"] = exc.code
        try:
            await schedule.async_handle_set_schedule(
                SimpleNamespace(
                    data={
                        "device_id": "test",
                        "times": [{"time": "12:00:00"}, {"time": "18:00:00"}],
                        "zone": "America/Not_A_Zone",
                        "reference_date": "2026-10-31",
                    },
                    hass=None,
                ),
                schedule_resolve,
            )
        except schedule.ScheduleActionRefused as exc:
            refused["membership"] = exc.code
        try:
            await services.async_handle_set_do_not_disturb(
                SimpleNamespace(
                    data={
                        "device_id": "test",
                        "enabled": True,
                        "start_time": "12:00:00",
                        "end_time": "18:00:00",
                        "timezone": "America/Not_A_Zone",
                        "reference_date": "2026-10-31",
                    },
                    hass=None,
                )
            )
        except Exception as exc:
            refused["dnd_invalid"] = type(exc).__name__
            refused["dnd_invalid_iana"] = "IANA" in str(exc)
        try:
            await services.async_handle_set_do_not_disturb(
                SimpleNamespace(
                    data={
                        "device_id": "test",
                        "enabled": True,
                        "start_time": "12:00:00",
                        "end_time": "18:00:00",
                        "timezone": "-05:00",
                        "reference_date": "2026-10-31",
                    },
                    hass=None,
                )
            )
        except Exception as exc:
            refused["dnd_offset"] = "IANA" in str(exc)
    finally:
        active["on"] = False
    refused["loop_thread_zoneinfo_opens"] = list(opens)
    refused["schedule_resolve_calls"] = calls["schedule"]
    refused["dnd_resolve_calls"] = calls["dnd"]
    refused["writer_calls"] = calls['writes']
    if refused != {
        "gap": "nonexistent_local_time",
        "fold": "ambiguous_local_time",
        "membership": "invalid_zone",
        "dnd_invalid": "HomeAssistantError",
        "dnd_invalid_iana": True,
        "dnd_offset": True,
        "loop_thread_zoneinfo_opens": [],
        "schedule_resolve_calls": 0,
        "dnd_resolve_calls": 0,
        "writer_calls": 0,
    }:
        raise SystemExit(f"refusal contract changed: {refused}")
    results["refusals"] = refused
    schedule._put_schedule = original_schedule_writer
    dnd._apply_dnd_locked = original_dnd_writer
    return results


DISTINCT_ZONES = (
    "America/Adak",
    "Australia/Lord_Howe",
    "Europe/London",
    "Asia/Tokyo",
    "Africa/Cairo",
    "Pacific/Auckland",
    "America/Los_Angeles",
    "Europe/Paris",
    "Asia/Kolkata",
    "Africa/Johannesburg",
)


async def concurrent_handler_probe() -> dict:
    """Ten real zones finish construction before either handler validates.

    Cache is cleared only before launch. The barrier is after the actual
    ``_construct_zone`` returns, so this is a permitted completion order,
    not a replacement timezone implementation.
    """
    schedule._ZONE_MISSES.clear()
    dnd._ZONE_MISSES.clear()
    schedule._load_iana_zones()
    loop = asyncio.get_running_loop()
    loop.set_default_executor(
        ThreadPoolExecutor(max_workers=len(DISTINCT_ZONES), thread_name_prefix="sol-zones")
    )
    opens: list[str] = []
    active = _audit(threading.get_ident(), opens)

    async def permissions(*_args: object) -> None:
        return None

    action_permissions.async_check_device_control = permissions

    def dnd_resolve(*_args: object) -> None:
        raise StopProbe()

    dnd.resolve_target = dnd_resolve
    results: dict[str, object] = {
        "zone_count": len(DISTINCT_ZONES),
        "method": (
            "Barrier after actual _construct_zone returns; real ZoneInfo and "
            "actual handlers; cache cleared only before launch"
        ),
    }
    for kind, module in (("schedule", schedule), ("dnd", dnd)):
        barrier = threading.Barrier(len(DISTINCT_ZONES))
        entered = {"n": 0}
        released = threading.Event()
        lock = threading.Lock()
        original_construct = module._construct_zone
        original_prepare = schedule._prepare
        original_validate = dnd.validate_call

        def gated(
            value: str,
            _original=original_construct,
            _barrier=barrier,
            _entered=entered,
            _released=released,
            _lock=lock,
        ):
            result = _original(value)
            with _lock:
                _entered["n"] += 1
            _barrier.wait(timeout=5)
            _released.set()
            return result

        def prepare_after_barrier(
            data, _released=released, _entered=entered, _original=original_prepare
        ):
            if not _released.is_set() or _entered["n"] != len(DISTINCT_ZONES):
                raise RuntimeError("schedule validation resumed before construction barrier")
            return _original(data)

        def validate_after_barrier(
            data, now=None, _released=released, _entered=entered, _original=original_validate
        ):
            if not _released.is_set() or _entered["n"] != len(DISTINCT_ZONES):
                raise RuntimeError("dnd validation resumed before construction barrier")
            return _original(data, now=now)

        module._construct_zone = gated
        if kind == "schedule":
            schedule._prepare = prepare_after_barrier
        else:
            dnd.validate_call = validate_after_barrier
        ZoneInfo.clear_cache()
        opens.clear()
        active["on"] = True
        try:
            outcomes = await asyncio.gather(
                *(
                    _concurrent_call(kind, zone)
                    for zone in DISTINCT_ZONES
                ),
                return_exceptions=True,
            )
        finally:
            active["on"] = False
            module._construct_zone = original_construct
            schedule._prepare = original_prepare
            dnd.validate_call = original_validate
        names = [type(item).__name__ for item in outcomes]
        expected = "ScheduleActionError" if kind == "schedule" else "StopProbe"
        item = {
            "valid_distinct_zones": len(DISTINCT_ZONES),
            "construct_calls": entered["n"],
            "barrier_released_before_validation": (
                released.is_set() and names == [expected] * len(DISTINCT_ZONES)
            ),
            "loop_thread_zoneinfo_opens": list(opens),
            "outcomes": names,
        }
        results[kind] = item
    failed = {
        kind: results[kind]
        for kind in ("schedule", "dnd")
        if results[kind]["loop_thread_zoneinfo_opens"]
        or not results[kind]["barrier_released_before_validation"]
        or results[kind]["construct_calls"] != len(DISTINCT_ZONES)
    }
    if failed:
        raise SystemExit(f"concurrent zone lifetime failed: {failed}")
    return results


async def _concurrent_call(kind: str, zone: str) -> None:
    if kind == "schedule":
        await schedule.async_handle_set_schedule(
            SimpleNamespace(
                data={
                    "device_id": "test",
                    "times": [{"time": "12:00:00"}],
                    "zone": zone,
                    "reference_date": "2026-10-31",
                },
                hass=None,
            ),
            _concurrent_schedule_resolve,
        )
        return
    await services.async_handle_set_do_not_disturb(
        SimpleNamespace(
            data={
                "device_id": "test",
                "enabled": True,
                "start_time": "12:00:00",
                "end_time": "18:00:00",
                "timezone": zone,
                "reference_date": "2026-10-31",
            },
            hass=None,
        )
    )


async def _concurrent_schedule_resolve(*_args: object) -> None:
    raise StopProbe()


def schema_and_sync_probe() -> dict:
    opens: list[str] = []
    current = threading.get_ident()

    def audit(event: str, args) -> None:
        if (
            event == "open"
            and threading.get_ident() == current
            and args
            and isinstance(args[0], str)
            and "zoneinfo/" in args[0]
        ):
            opens.append(args[0])

    sys.addaudithook(audit)
    schedule.SET_SCHEDULE_SCHEMA(
        {
            "device_id": "test",
            "times": [{"time": "12:00:00"}],
            "zone": "America/Adak",
            "reference_date": "2026-10-31",
        }
    )
    schema = {"zoneinfo_opens": list(opens)}
    if opens:
        raise SystemExit(f"framework sync validator did zoneinfo I/O: {opens}")
    schedule._IANA_ZONES = None
    schedule._ZONE_MISSES.clear()
    prepared = schedule._prepare(
        {
            "device_id": "test",
            "times": [{"time": "12:00:00"}],
            "zone": "America/Adak",
            "reference_date": "2026-10-31",
        }
    )
    alias = dnd.require_iana_zone("US/Eastern")
    try:
        dnd.require_iana_zone("America/Not_A_Zone")
        sync_invalid = "accepted"
    except dnd.DndActionRefused as exc:
        sync_invalid = exc.reason
    sync = {
        "utc_clocks": prepared["utc_clocks"],
        "cache_loaded": schedule._IANA_ZONES is not None,
        "alias_key": alias.key,
        "sync_invalid_zone": sync_invalid,
    }
    if sync["utc_clocks"] != ["21:00:00"] or not sync["cache_loaded"] or alias.key != "US/Eastern" or sync_invalid != "invalid_zone":
        raise SystemExit(f"synchronous helper contract changed: {sync}")
    return {"schema": schema, "sync": sync}


def main() -> None:
    results = asyncio.run(cancellation_probe())
    results["cold_handlers"] = asyncio.run(cold_handler_probe())
    results["concurrent_zones"] = asyncio.run(concurrent_handler_probe())
    results.update(schema_and_sync_probe())
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
