# Schedule and Do Not Disturb contract

The integration registers two native settings actions:
`catgenie.set_schedule` and `catgenie.set_do_not_disturb`. The schedule action
uses typed time rows in an ObjectSelector; see [Schedule action](schedule-actions.md).
These are action forms, not device-page time entities. Deployment state is not
tracked in this contract. The preparation helpers in `schedule.py`
remain separate and do not expose sendable fragments.

## Implemented

- Strict `HH:MM:SS` parsing. Unpadded times, `HH:MM`, and library
  `day`/`hour`/`minute`/`enabled` objects are rejected.
- `local_time_to_utc_time` and `utc_time_to_local_time`, matching app
  functions #12931 and #12930 for an explicit IANA zone and an explicit
  reference date.
- DST gaps and overlaps are rejected. They are not folded to a neighboring
  hour.
- Read-only schedule and DND display dicts. The wire list is copied and is
  not sorted. Display sort is a separate field.
- A prepared schedule fragment contains only `schedule`, with the same length
  and caller order as the existing list.
- A prepared DND fragment contains only `dndFrom`, `dndTo`, and the existing
  `catDelay` integer. It is one window, not two time entities.

Prepared schedule and DND fragments in `schedule.py` still have
`sendable=False`. The action does not flip that flag.

## Do Not Disturb action

`catgenie.set_do_not_disturb` is registered once while any config entry is
loaded, and removed when the last entry unloads. The device field is a single
Home Assistant device selector. It is resolved through the device registry
identifier `(catgenie, manufacturer_id)` and exactly one CatGenie config entry.
Current cores use that entry's `config_entry_id`. 2025.1.0 devices use
`config_entries`; a foreign entry on that shared device is ignored, and two
CatGenie entries are refused before any vendor read. Composite devices are
refused. There is no device map in `hass.data[catgenie]`, and a raw vendor id
is not accepted. The registered schema comes from
`homeassistant.helpers.config_validation` (`probatio` or `vol`), not from a
package that merely happens to be installed. Schema failures are that
library's `Invalid`. The handler still checks IANA names, gaps, and folds
before I/O. This does not verify every IANA zone or how the device applies DST.

Enabled writes convert both local clocks with the explicit IANA zone and the
reference date. If the date is omitted, the date is today in that selected
zone, not the Home Assistant host zone and not `configuration.timezone`.
Both ends use that same date, including an overnight window. The PUT body is
exactly `{dndFrom, dndTo, catDelay}`. `catDelay` is the fresh integer when it
is one of 300, 600, 900, 1200, 1500, or 1800 seconds. Disable writes both
clocks as `''` and does not invent times. Prior official-app save/readback
inspection confirmed UTC clock encoding and Off plus Save clearing both
strings. Personal settings, dates, and phone-zone observations are omitted.

That observation was an official-app save/readback, not validation that this
integration's disable PUT is accepted by firmware. Integration write acceptance
remains unverified. All local configuration writers share a per-device
coordinator lock across fresh GET, PUT, and refresh; separate devices remain
independent. This does not coordinate the app/other clients or provide remote
compare-and-swap.

This is current-date app-parity UTC encoding. It is not a DST-safe recurring
wall-clock guarantee. Firmware interpretation of retained clocks, `timezone`,
`dstFrom`, and `dstTo` is unverified. There is no automatic DST resave.
Gap and fold local clocks are refused rather than folded. A successful PUT is
followed by one coordinator refresh. A failed GET or PUT does not continue,
and an ambiguous PUT is not rolled back.

## Not the conversion input

The app does not read `configuration.timezone` in `localTimeToUtcTime`.
Synthetic example: a reported `-05:00` offset need not match a date whose
selected IANA zone uses `-04:00`. Helpers refuse a raw offset and a fixed
`datetime.timezone`. Callers must pass an explicit IANA zone,
plus the calendar date used for conversion. The same wall time is
`16:00:00` UTC on 2026-10-31 in `America/New_York` and `17:00:00` UTC on
2026-11-02. Applying `-05:00` to both dates would be an arbitrary rewrite.

Wire UTC encoding is supported by the app display/write path and the observed
DND app-save/readback described above. An integration schedule edit/readback has not
been performed, and neither native action has live PUT acceptance yet. The
conservative preparation-helper display flag remains
`device_storage_verified=False`; it is not a statement that the DND observation
never occurred.

## Remaining acceptance gates and helper limitations

- The registered schedule action provides a native ObjectSelector time-row
  editor. There is no device-page time entity or raw JSON text-box editor.
  The older preparation helpers are not that registered action.
- Live PUT preservation of unrelated schedule fields is not verified, and no
  schedule write was performed. The DND action sends only `dndFrom`, `dndTo`,
  and `catDelay`.
- An edit save (function #18484) would PUT only `{schedule: [HH:MM:SS]}` to
  `device/management/{manufacturerId}/configuration`. The first-time
  mode-picker save (function #17991) also merges `{manual: 0, mode: 1}`.
  That activates time cleaning. List edits must omit `mode` and `manual`.
  A populated list is not activation: for example, a synthetic configuration
  can have mode 0 and multiple stored schedule strings.
- Add, edit, and delete replace the whole string list. Delete matches the
  clock value, not an index. Redux `scheduleTimes` actions are not the HTTP
  write. Length changes are not prepared here.
- Empty `schedule: []` is UI-saveable because an empty array is truthy in
  `fixConfigurationSchedules`. `prepare_schedule_disable` raises. That is
  not a proven device disable.
- `prepare_dnd_disable` still raises. The action path, not that helper, writes
  empty strings. Prior app Off plus Save cleared both reported clocks. That is
  app-save evidence, not a firmware DST contract. The cat-activation delay
  number still only echoes a stored pair.
- A span above ten hours is rejected by the unsendable helper because the app
  UI rejects it and the server limit is unknown. The action does not apply
  that UI cap and does not treat it as a server limit.
- `catDelay` choices belong to the settings controls. The action only copies an
  existing integer and will not invent a default.
- Mode, manual, volume, and other settings are not written.

## Action input differences

The schedule action intentionally requires zero-padded `HH:MM:SS` clocks;
seconds are not invented. DND also accepts `HH:MM` and normalizes seconds to
zero. Omit schedule `reference_date` (or use null) for today in its explicit
zone; an empty string is refused. DND also treats an empty date as omitted.
These existing contracts are retained, not silently widened. Both registered
actions authorize the selected device before handler parsing or timezone
executor work. Optional DND string fields accept null as absent, consistently
with direct validation. The DND action does not apply the app UI's ten-hour
cap; the legacy preparation helper retains that UI constraint. Neither claims
that constraint is a verified firmware/server limit.

## App evidence used

- `app-index.hasm` functions #12930, #12931, #12935, #12936, #13331, #14055,
  #15556, #17991, #18313, #18377, #18442, #18484, and #20995.
- `createRequestObject` joins `device/management` + `/` +
  `{manufacturerId}/configuration` and sends the configuration object as
  the PUT body.
- Prior read-only configuration inspection verified string-list schedule and
  string DND fields. Personal setting values are not reproduced here.
- Library `set_schedule` / `set_dnd` are the wrong wire shape and are unused.

## Approved live acceptance still required

Record `hass.config.time_zone` and the phone IANA zone. Do not write if they
disagree, and do not treat `-05:00` as `America/New_York`. Change one existing
clock by a known local amount that does not cross midnight or a DST gap or
overlap. PUT only `{schedule: existing-length HH:MM:SS strings}`. Read back that the
changed slot matches `localTimeToUtcTime` and that mode, manual, volume,
delay, DND, extra dry, and the other clocks are unchanged. Do not combine
that with an empty list or a mode change.
