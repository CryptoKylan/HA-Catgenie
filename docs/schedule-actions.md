# Schedule list action

Registered by `services.py` after entry platforms load, alongside DND, with
shared setup/unload handling and a common device resolver. Live sibling
preservation remains unverified.

## What the first version is

A native Home Assistant service action, `catgenie.set_schedule`. It is the
Developer Tools / automation action form, not a calendar on the device page
and not a time-list entity. Home Assistant 2026.10.4 `TimeSelector` has no
`multiple` setting. The list is an `ObjectSelector` with `multiple: true`
and one required `time` field per row. That is a typed clock row, not a JSON
text box pretending to be a time entity.

## Call

Required: `device_id`, `times`, `zone`. Optional: `reference_date`.

`times` is a list of objects, `[{"time": "HH:mm:ss"}]`. Bare strings are
refused. One to eight clocks. Duplicates are refused. Both directions of the
app's `minutesDifferenceBetweenTimes` must be at least 120 minutes, including
across midnight. An empty list is UI-saveable in the app and is refused here
because disable is not verified.

`zone` is an explicit IANA name. It is not `configuration.timezone`, not a
fixed offset, and not the Home Assistant or device zone. `reference_date`
is a calendar date. When omitted, the date is today in `zone`. Every clock
uses that same date. The action does not guess an overnight firmware window.

Ambiguous and nonexistent civil times are refused. There is no automatic
DST job and no resave. App-parity UTC storage does not prove the unit will
run at the same wall time after a transition.

## Write

One injected `resolve_target(device_id)` returns the coordinator and the
Device Registry entry. The combined registration path uses the same resolver
as do-not-disturb, including legacy `config_entries`. Cache availability is
checked before any vendor read. The registered schema is the framework schema
from `homeassistant.helpers.config_validation` and raises that library's
`Invalid`, not `HomeAssistantError`. The handler still refuses gaps, folds,
and spacing before I/O. Listed zones in the tests are explicit fixtures, not
a claim that every IANA zone or device DST behavior was verified.
One `client.get_devices()` must return a list of `Device` with exactly one
row for that manufacturer id. The fresh row must be online, with an explicit
configuration and an explicit current `schedule` list whose entries came
from `HH:mm:ss` strings. A library `day/hour/minute/enabled` list is refused
before PUT.

The PUT is `update_configuration(manufacturer_id, schedule=[UTC clocks])`.
Library `set_schedule` is not called. `mode`, `manual`, DND, cat delay,
volume, and auto-lock are not sent. Coordinator data is not mutated. Refresh
runs once after the PUT returns. A failed write is not retried and not rolled
back. Exception text keeps a reason code or an exception class name, not a
serial and not the vendor body.

`schedule.py` still reports `sendable=False` and `registered_ha_service=False`.
This module does not flip that hold. Sibling preservation on a live device
still needs an approved owner edit and readback before claiming acceptance.
