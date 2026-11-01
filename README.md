# CatGenie A.I. for Home Assistant
 
An unofficial Home Assistant integration and dashboard card for the
[CatGenie A.I.](https://www.catgenie.com/) self-washing litter box by PetNovations.
It signs in the way the official app does (phone number plus SMS code), so no
token has to be captured by hand, and it exposes the unit's status, controls
and an animated dashboard card.
 
## Credits
 
This project builds on the work of others and through vibe coding with Claude. Thank you to:
 
* [Rukongai/CatDjinni](https://github.com/Rukongai/CatDjinni): reverse engineering research: signing algorithm, Frida scripts
* [appkins/hass-catgenie](https://github.com/appkins/hass-catgenie): earlier HA integration (requires manual refresh token)
* [PrimeAutomation/petnovations](https://github.com/PrimeAutomation/petnovations): earlier HA integration (same limitation)
Also used directly:
 
* [kclif9/catgenie-api](https://github.com/kclif9/catgenie-api) (MIT), published on PyPI as
  [`catgenie`](https://pypi.org/project/catgenie/). This is the async Python client that
  does the authentication, request signing and API calls. The integration depends on it.
The integration was written from scratch. The sensor list follows the earlier
PrimeAutomation integration, but no code was copied from it.
 
## Operation states and error reporting

The integration preserves integer operation states, including values the
pinned client does not recognize. `0` is idle and `1` is cleaning. Reported
`2` is the app `SUSPENDED` value. Function #6945,
`convertDeviceCleaningStatusToAppCleannigStatus`, maps idle `0` to NONE,
play `1` to CLEANING, and suspended `2` to STOPPED. It displays as
**paused** only when that same report is explicitly connected, the
active-error list was supplied and is empty, and vendor error text is
blank. The operation-status text is then **Paused**, and the error sensor
says **No active errors**. A missing, malformed, or non-empty error list
is not that report. A disconnected state 2 without an actual fault stays
unknown, not an invented error. Other unsupported integers keep the generic error
label, with the original `raw_state` retained. An unrecognized operation
state does not supply a fault-specific diagnosis. The cleaning binary
sensor stays unknown for these states, including a normal pause, not
falsely off.

The `operation_error` sensor prefers nonblank vendor error text. Otherwise,
it describes the separate `activeErrors` list using these mappings:

Observed on a CatGenie A.I. running firmware 8.7.205R:

- **2 — Water fill issue.** Observed with operation state 2 and the same
  description in the official app.
- **5 — Cleaning solution cartridge missing.** Observed after removing the
  SaniSolution cartridge while operation state remained 0 (idle).

Derived from the CatGenie Android app 1.8.253, not reproduced on that unit:

- **3 — Drainage issue** (`DRAINAGE_PROBLEM`).
- **4 — Dryer overheating** (`BI_METAL`).
- **6 — Cleaning solution cartridge empty** (`EMPTY_CARTRIDGE`).

The app uses these definitions to interpret `activeErrors`, not just push
notifications. See [app-derived code evidence](docs/error-code-provenance.md)
for the enum/message path, archive version and reproducibility details.

This is not a complete manufacturer error catalogue. Other active-error values
stay explicitly unknown, and the raw list remains in `active_errors`. String,
float and boolean lookalikes do not select the integer mappings.

An online device explicitly reporting idle, cleaning, or this paused
state, together with an empty active-error list, displays **No active
errors**. Missing fields and offline devices do not become confirmed
clear reports. Another abnormal operation state without a message or
active codes instead displays a generic error with its state number.
Active-error code 2 is water fill. It is not reported operation state 2.
A long error message is shortened to fit Home Assistant's
255-character state limit, with its full text retained in `error_details`.
Cards and automations should treat `No active errors` as normal, rather than
interpreting every populated error-sensor value as a fault.

`operation_status` is a separate text sensor. It shows **Idle** only when
`reportedStatus` was explicitly `connected` and the operation state was
explicitly `0`, including when progress is missing or a stale `100`. While
explicitly cleaning, a finite progress from 0 through 100 is shown as text
such as `42%`. Missing, `255`, out-of-range, boolean, nonnumeric and
nonfinite progress stay unknown. Numeric `operation_progress` also rejects
malformed/coerced percentages and preserves valid reported 0–100 values,
including valid idle percentages. Only missing progress or numeric sentinel
`255` in an explicit connected idle report with an explicit empty active-error
list and absent or blank-string vendor error text displays `0%`. A supplied
null, malformed, or nonblank error prevents this idle-only fallback. This is
an idle display convention, not measured telemetry; raw model values are
unchanged. Faults, offline/unknown reports, and running missing progress do
not receive the fallback. The pinned model still rejects wire payloads that
omit required progress; display handling does not relax that validation.
An explicit non-connected `reportedStatus` makes this sensor unavailable.
A missing status or a Pydantic default is not Idle and is not treated as a
confirmed offline report. An explicit normal pause, reported state `2`
with an explicit empty active-error list and blank vendor text, is
**Paused**. It is not a percentage, even when numeric progress is present.
Valid reported numeric percentages are preserved. Any other operation state `2`,
and other unsupported states, are not Idle and not Paused. An idle cycle
with an active fault still says Idle; the fault stays on `operation_error`.
See [readable operation status](docs/readable-operation-status.md).

While offline, a valid numeric percentage is the last reported progress, not
evidence that the unit is healthy or still cleaning. Malformed device records
are quarantined individually; other valid devices remain available. An all-invalid
nonempty list or malformed list envelope fails the poll. A true empty list is valid.
If a device is quarantined at setup while a valid peer allows the entry to load,
no entities are created for it; reload the entry after good data returns to create
them. For a device whose entities already exist, quarantine makes them unavailable,
not partially updated, until a later successful poll recovers the device.

Absent measurements show unknown, not client-library defaults. In particular,
missing lifetime activation count does not publish zero or imply a meter reset.
Actual integer zero counts and auto-lock off are retained. Numeric strings and
booleans do not become valid measurements through Pydantic coercion. Activation
mode requires both a known integer mode and an integer manual flag (0 or 1).

This reporting does not change device commands, polling or recovery behavior.
See [tests/README.md](tests/README.md) for the offline regression suite.

## Repository layout
 
```
catgenie-ha/
├── hacs.json
├── README.md
└── custom_components/catgenie/
    ├── __init__.py        setup and teardown
    ├── manifest.json      domain, version, requirements
    ├── const.py           constants and polling intervals
    ├── config_flow.py     phone + SMS login, re-authentication
    ├── coordinator.py     polling and error handling
    ├── history.py         activity/diary parsing, no network
    ├── history_coordinator.py  slower isolated history refresh
    ├── activity.py        read-only visit and abort sensors
    ├── client.py          client subclass for payload compatibility
    ├── operation_state.py integer-state compatibility and error descriptions
    ├── operation_status.py readable Idle or percentage text
    ├── entity.py          base entity, device info, command helper
    ├── cartridge.py       labelled cartridge capacity
    ├── configuration.py   partial mode and volume payloads
    ├── settings_pending.py  bounded unconfirmed hold for select and number
    ├── reported_config.py  explicit reported diagnostics and measurement provenance
    ├── local_errors.py     safe local refusal types
    ├── configuration_lock.py  shared per-device settings write lock
    ├── read_information.py  notification and firmware-note parsing
    ├── read_information_coordinator.py  isolated account reader
    ├── read_sensors.py      read-only notification and notes sensors
    ├── schedule.py         pure schedule/DND preparation contracts
    ├── sensor.py
    ├── binary_sensor.py
    ├── button.py
    ├── operation_post.py  shared writer for ungated states 2, 3, and 4; state 129 only when that call receives eligible firmware
    ├── pause.py           literal state-2 pause helper; no new client fork
    ├── resume.py          literal state-3 resume helper; no new client fork
    ├── abort.py           literal state-4 abort helper; does not replace Stop
    ├── no_scoop.py        state 129 only after the traced fwVersion gate
    ├── action_permissions.py  caller permission before settings actions
    ├── dnd_actions.py     set_do_not_disturb; explicit IANA zone and reference date
    ├── schedule_actions.py  set_schedule; explicit IANA zone and reference date
    ├── services.py        shared action registration and unload
    ├── services.yaml      native action forms, not device-page time entities
    ├── switch.py
    ├── select.py          Cat / Manual / Time activation
    ├── number.py          volume, auto-lock timeout, cat activation delay
    └── translations/en.json
```
 
Delivered separately as front-end files:
 
* `catgenie-card.js`: the animated custom Lovelace card (copy to `/config/www/`).
* `catgenie-card.yaml`: an earlier, simpler card made only from built-in cards. The custom card replaces it.
* `catgenie-card-preview.html`: a standalone preview of the card using simulated data.
## The integration
 
| Item | Detail |
|---|---|
| Domain | `catgenie` |
| Version | v1.0.1 |
| Dependency | `catgenie==0.1.6` requires Python >=3.13. Supported minimum: Home Assistant 2025.7.0 (Python >=3.13.2); also tested on HA 2026.10.4 (Python >=3.14.2). The native typed schedule-row selector requires the object-selector fields/multiple support added for HA 2025.7; HA 2025.2 rejects that metadata. Both declared test targets execute real-HA setup, lifecycle, services and data contracts as well as the isolated unit suite. |
| IoT class | `cloud_polling` |
| Polling | Device state every 60 seconds, or every 15 seconds while state 1 is running. Paused state 2 and unknown states retain the 60-second cadence; faster paused polling is not implemented. Activity history is a separate 15-minute read. Notification and firmware notes are a separate 30-minute local bound, not a recovered vendor limit. Neither read changes the device poll. |
| Transport | The library uses `curl_cffi` to present a mobile TLS fingerprint, which PetNovations requires |
 
### How it works
 
* **Login (`config_flow.py`).** Two steps: the user enters a country code and
  phone number, an SMS code is requested, then the code is exchanged for credentials.
  Only the long-lived refresh token and account IDs are stored. The access token
  is refreshed automatically by the library. A re-authentication flow handles a
  rejected login, and a mismatched account aborts instead of overwriting the entry.
  Login-code requests must return an integer HTTP 2xx status to advance; this
  does not prove SMS delivery. To request a replacement code, close and restart
  setup or reauthentication. Reauth uses the same phone/code steps and preserves
  the configured account identity; it has no separate confirmation/back step.
* **Setup (`__init__.py`).** Creates one `curl_cffi` session, rebuilds the
  credentials from the config entry, and makes sure the auth object and client
  share the same credentials instance so a refresh is seen by both. The
  integration-owned auth subclass serializes overlapping token refreshes;
  cancellation or a failed refresh releases the lock for later requests.
* **Coordinator (`coordinator.py`).** Polls all devices on the account.
  Authentication failures start re-authentication. Network, API and
  validation errors surface as update failures. Polling speeds up while a
  cycle is running. Activity history uses a second coordinator and does not
  replace this one. Notification and firmware notes use a third coordinator
  with the same isolation rule. See [activity history](docs/activity-history.md)
  and [read-only feed](docs/read-information.md).
* **Client fix (`client.py`).** Real devices report schedule entries as time
  strings such as `06:00:00`, but the library's model only accepts
  dictionaries. The subclass converts them before validation and keeps the
  original string.
* **Entities (`entity.py`).** Every entity belongs to one device per unit, with
  MAC address, serial number and firmware shown on the device page instead of as
  separate sensors. Device-page firmware refreshes on integration reload, not
  each coordinator update; release-note attribution follows the current device
  coordinator and can change sooner. Commands share a helper that reports failures cleanly and
  refreshes state afterwards.
### Entities (per device)
 
| Platform | Entities |
|---|---|
| Sensor | Last clean (timestamp), total cycles, cartridge remaining, cartridge capacity, operation state, operation progress, operation status, operation error, Reported activation mode, scheduled cycles (reported times in attributes), Reported cat activation delay, Reported auto-lock timeout, cat sensitivity, Reported volume, network type, cartridge type, reported timezone, and reported DND. Activity history, when the history coordinator is attached: visits today, last visit, last visit duration, aborted cycles. Aborted cycles are cloud flush outcomes, not completed-cleaning or recovery counters. Read-only diagnostics, when the account reader is attached: latest notification, announced firmware, and firmware release notes. Device-page software version refreshes on reload. |
| Binary sensor | Online, cleaning; low heater and fan shutter (raw diagnostics, disabled by default because their meaning is undocumented) |
| Button | Start cleaning, stop cleaning, Pause cleaning, Resume cleaning, Abort cleaning, and No-scoop wash. The four cycle controls are enabled by default for a new registration and are not start or stop commands. Home Assistant keeps an existing registry enabled or disabled choice; this integration does not rewrite it. A previously disabled entry needs an explicit Home Assistant enable. See [pause and resume](docs/pause-resume-control.md) and [abort and no-scoop](docs/cycle-controls.md). |
| Switch | Panel lock, extra dry, and extra wash and extra shake where the unit reports them |
| Select | Activation mode: Cat, Manual, or Time. Writes the raw `mode`/`manual` pair, not the app presentation enum |
| Number | Volume, integers 1–7; auto-lock timeout, 0 (off) or 5/10/15/20/25/30 minutes; cat activation delay, 5/10/15/20/25/30 minutes. Delay/timeout wire values and reported duration sensors use seconds. |

Activation and volume writes send only those fields, then refresh once. They do not create a schedule or rewrite nested settings. Auto-lock writes only `autoLock`; cat delay echoes a supported fresh DND pair with `catDelay` under the shared per-device write lock. See [cat activation delay](docs/cat-activation-delay.md). The offline tests do not prove the vendor merges a partial PUT. After the cloud accepts the PUT, the select or number keeps the requested value until a later poll reports that same value, or for two idle poll intervals (120 seconds), whichever comes first. While that hold is active, `pending_confirmation` is true. That attribute means the write was accepted, not that the unit applied it. Read-only reported sensors keep showing the last poll, or unknown when a field is absent or unsupported. A refused or failed write does not create a hold, and a device that disappears from the account drops it. The integration does not retry the write or poll faster.

Diagnostic entity category means read-only diagnostic entities in the UI. It
does not imply Home Assistant's Download diagnostics feature: this integration
does not implement a `diagnostics.py` download hook. `reported_config.py` is a
reader helper, not that hook. Full firmware notes and history diaries remain
visible in current attributes but are excluded from recorder attribute history.
 
### Cartridge capacity

The capacity sensor prefers a valid API-reported maximum. When absent, a regular
A.I. cartridge uses the mode-dependent manufacturer rating: 240 cleanings in Cat
Activation or 120 in Manual/Time Activation. The `capacity_source` attribute
identifies whether the value is device-reported or manufacturer-rated. Unknown
inputs and missing/maintenance cartridges are not assigned a guessed rating.
The reported remaining count is unchanged: the API already adjusts it by mode.
See [capacity behavior and evidence](docs/cartridge-capacity.md).

### Known limitations
 
* The library still validates other response fields strictly. An unexpected
  cleaning mode or malformed non-integer operation state quarantines that
  device report. If no valid reports remain, the poll fails. Logs contain only
  rejection counts and exception classes, not field paths, values, context,
  or vendor response text. Unrecognized integer operation states are preserved.
* Cleaning mode requires explicit known mode and manual fields, otherwise unknown.
  Supported mode/manual pairs identify manual, cat or time
  activation. Prior read-only inspection around a mode round trip confirmed these pairs
  on A.I. V1 firmware 8.7.205R; see the capacity evidence above.
* `catgenie.set_schedule` is a native action, not a device-page time list. It requires an explicit IANA zone and reference date, uses that same date for every clock, and refuses gap and fold times. It does not disable the schedule with an empty list and does not activate Time mode. The old `schedule.py` fragment stays nonsendable. Schedule storage is not a verified device timezone. The device-page editor is deferred. See [schedule actions](docs/schedule-actions.md).
* `catgenie.set_do_not_disturb` is a settings action, not a device-page time entity. It uses the selected IANA zone and reference date, refuses gap and fold times, writes strict UTC clock strings, and is not a DST-safe recurring guarantee. Off writes two empty clocks. The device-page editor is deferred. See [schedule and DND contract](docs/schedule-dnd.md).
* Pause cleaning and Resume cleaning are enabled by default for a new entity registration. An existing registry enabled or disabled choice is not changed. Pause posts literal state 2. Resume posts literal state 3. Both use the existing operation writer only after an explicit online report. Normal-cycle firmware acceptance was owner-verified; fault resume and cartridge allowance effects are not proven. They do not recover a water-fill fault, restore cartridge allowance, or send start, stop, abort, or a special cycle. A reported integer is not a send guard. See [pause and resume](docs/pause-resume-control.md).
* Abort cleaning posts literal state 4 and does not replace Stop. No-scoop wash posts literal state 129 only after the traced `fwVersion` gate (`8.5.81`). Both are enabled by default for a new registration. Normal-cycle Abort and No-scoop were owner-verified; fault resume, cartridge allowance, and finishing-cycle equivalence are not proven. See [abort and no-scoop](docs/cycle-controls.md).
* Entities are created from the device list at setup. Adding a device needs an
  integration reload; removing one leaves its entities unavailable. Automatic
  device addition/removal and a separate reauth confirmation screen are not
  implemented. Account-wide actions remain entry-ref-counted.
* This is an unofficial integration that talks to PetNovations' cloud. The API
  can change without notice and the vendor does not support it.
  
## The dashboard card
 
A custom element, `catgenie-card`, drawn as an SVG that follows the unit's state.
 
| State | What it shows |
|---|---|
| Idle | Green status light, rake stowed in its bay, a grey cat that walks up to the unit |
| Cleaning | Blue pulsing light, the inner bowl spinning, clumps carried around to the rake, which dips in, lifts them and retracts into the housing, falling water drops, and a progress bar |
| Error | Red blinking light with the error text in the header |
| Offline | Greyed-out unit that doesn't respond to taps |
 
Tapping the unit asks for confirmation inside the card, then presses the start
or stop button. The cartridge window on the housing drains as the cartridge
runs down and turns red below 15%. Tapping the cartridge stat opens the sensor's
history. The stats row shows cartridge remaining, last clean (or progress while
cleaning) and mode.
 
### Installation
 
1. Copy `catgenie-card.js` to `/config/www/`.
2. Add `/local/catgenie-card.js` as a JavaScript module under Settings, Dashboards, Resources.
3. Hard-refresh the browser, or add `?v=N` to the resource URL after an update.
### Configuration
 
```yaml
type: custom:catgenie-card
prefix: catgenie      # matches entity names such as sensor.catgenie_cartridge_remaining
name: CatGenie A.I.
max_cartridge: 120    # defaults to the cartridge capacity sensor
confirm: true         # ask before starting or stopping
width: 420px          # optional maximum width, centered
height: 260px         # optional maximum illustration height
font_scale: 1         # optional text scale
compact: false        # hide the stats row
```
 
An `entities:` block can map individual entities by key (`state`, `progress`,
`error`, `cartridge`, `capacity`, `last`, `mode`, `online`, `start`, `stop`).
 
**Sizing.** With no `width` or `height`, the card fills its panel or grid cell
and the illustration scales to fit. With either set, the card shrinks to fit its
content. In sections dashboards the card registers a default grid size of 6 by 6
(minimum 3 by 3) so it can be resized in edit mode.
 
### Card limitations
 
* The illustration is stylized, based on photos of the real unit, and not a photographic match.
* The rake and bowl animation is a timed loop, not tied to the unit's real scoop, wash and dry phases.
* The cat is decorative and does not react to a real cat.
* The animation and gradients are heavier than a flat card and have not been tried on low-power tablets.
 
