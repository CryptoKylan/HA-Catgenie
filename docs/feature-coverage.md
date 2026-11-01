# Feature coverage

This inventory covers 47 deduplicated topics, not 47 entities. The JSON and table
below describe code capabilities, not deployment state. `implemented` means code
exists, not full firmware acceptance. `read-only` and `local-action` distinguish
reader capabilities from registered settings actions. `catalogue` is research,
not an entity. `limitation` is an unimplemented lifecycle behavior.

## Validation scope

Pause, Resume, Abort, and No-scoop buttons are enabled by default for new
registrations; existing registry choices and ids remain unchanged. Normal-cycle
use was owner-verified. Reported state 2 displays as paused only for an explicit
connected report, an explicit empty active-error list, and blank vendor text.
Natural-pause owner render remains pending. Fault resume, cartridge allowance,
and finishing-cycle equivalence are not proven. CG-34 and CG-36 stay `HOLD` for
those open questions, not because their implemented buttons are absent.

The notification/firmware readers are implemented. No authoritative live type-24
item has established announced-version acceptance. No item means unknown, not
up to date. Firmware install, approve, delete, and push settings stay out.
Device-page firmware refreshes on reload; release-note attribution follows the
current device coordinator and can change sooner.

## Settings actions

- `catgenie.set_do_not_disturb`: native action form, explicit IANA zone and
  reference date, atomic app-shaped DND/delay payload, selected-device control
  authorization, and fresh preservation read. Off writes empty clocks.
- `catgenie.set_schedule`: typed clock-row action with explicit IANA zone and
  reference date. Writes only schedule clock strings, without activating Time
  mode. Empty-list disable is not exposed.
- Both register through shared setup/unload. They are not device-page time
  entities; the device-page editor is deferred. Legacy nonsendable `schedule.py`
  preparation fragments remain separate. No maintainer-question draft is included.
- User calls require admin or selected-device entity control; trusted context-free
  automation remains supported. Denied/missing users and offline cached devices
  refuse before vendor I/O.
- Gap and fold times are refused. Both window endpoints use the same reference
  date. There is no automatic DST rewrite or year-round wall-time guarantee.
  Schedule sibling preservation and recurring device DST execution remain
  acceptance gates; app-save encoding evidence is not integration PUT acceptance.
- Extra wash/shake still use the pinned library's partial `binaryElements` body.
  Vendor nested sibling merge versus replacement remains UNVERIFIED. A local
  per-device lock is not remote compare-and-swap or proof of merge semantics.
- Mode, volume, auto-lock, cat-delay and reported diagnostic entities are retained.
  Missing measurements are unknown, not fabricated defaults or counter resets.

## Inventory dispositions

| ID | Disposition | Topic |
| --- | --- | --- |
| CG-01 | implemented | Mode-aware cartridge capacity |
| CG-02 | implemented | Configuration write safety |
| CG-03 | implemented | Idle progress display |
| CG-04 | implemented | Cat / Manual / Time mode selector |
| CG-05 | read-only | Activity Data / Diary read pipeline |
| CG-06 | implemented | Panel auto-lock timeout control |
| CG-07 | implemented | Cat activation delay control |
| CG-08 | read-only | Cleaning history and abort outcomes |
| CG-09 | local-action | Do Not Disturb window |
| CG-10 | read-only | Explicit history window |
| CG-11 | local-action | Schedule display and editor |
| CG-12 | read-only | Visits: daily count, last visit, duration and diary |
| CG-13 | implemented | Volume control |
| CG-14 | read-only | Cartridge type diagnostic |
| CG-15 | read-only | Reported timezone diagnostic |
| CG-16 | read-only | History coverage and retention |
| CG-17 | read-only | Notification events |
| CG-18 | HOLD | Account notification preference |
| CG-19 | catalogue | Pet profile/identity information |
| CG-20 | implemented | Version/documentation consistency |
| CG-21 | HOLD | Account metadata |
| CG-22 | HOLD | Cat sensitivity control |
| CG-23 | read-only | DST fields diagnostics |
| CG-24 | HOLD | Dome/accessory diagnostic |
| CG-25 | limitation | Devices added after setup |
| CG-26 | HOLD | Estimated cycle finish/time remaining |
| CG-27 | read-only | Other device/configuration diagnostics |
| CG-28 | read-only | Firmware availability / release notes / install |
| CG-29 | HOLD | Device language |
| CG-30 | HOLD | Cycle phase / start countdown |
| CG-31 | implemented | Status endpoint compatibility |
| CG-32 | HOLD | Cat present / occupancy |
| CG-33 | HOLD | Pump/heater/water hardware settings |
| CG-34 | HOLD | Pause / resume / stage commands |
| CG-35 | HOLD | Liquid level / used solution volume |
| CG-36 | HOLD | Special / no-scoop cycle |
| CG-37 | catalogue | Other endpoint catalogue entries |
| CG-38 | HOLD | Vacuum/valve domain model |
| CG-39 | implemented | Extra dry, wash, and shake |
| CG-40 | implemented | Extra dry |
| CG-41 | implemented | Extra shake |
| CG-42 | implemented | Extra wash |
| CG-43 | implemented | Serial, MAC, BLE, and connectivity sensors |
| CG-44 | implemented | Panel lock |
| CG-45 | implemented | Status sensors already in current |
| CG-46 | implemented | Start cleaning |
| CG-47 | implemented | Stop cleaning |

Counts: HOLD 13, catalogue 2, implemented 18, limitation 1, local-action 2,
read-only 11. Total: 47. These counts are checked against the JSON entries.
A topic can retain a HOLD while its implemented subset is explicitly identified;
this is not a blanket assertion of missing code or complete acceptance.
