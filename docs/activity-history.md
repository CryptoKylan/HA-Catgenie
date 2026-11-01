# Activity history

Read-only cloud history for visits and cleaning outcomes. It does not replace
user-created completed-cleaning or recovery counters, or the integration's
`total_cycles` / `last_clean` device-poll sensors. User-created helpers are
separate automations, not integration-provided measurements.

History failure messages contain only the exception class, not vendor text,
identifiers, token responses, or exception arguments. Failures stay isolated
from device polling and do not independently request reauthentication.

## What is read

`GET device/history/account/pet/statistics` returns three separate arrays:

- `visitResponses`: `rtcStart`, `serialNumber`, `durationSeconds`, `deviceId`,
  plus top-level `timestamp` and `machineTS`
- `flushResponses`: `rtcEnd`, `serialNumber`, `aborted`
- `petResponses`: account cat profiles, not visit owners

The pinned `catgenie==0.1.6` method `get_pet_statistics()` accepts no
arguments. The no-parameter window length is unverified, and the inspected
app does not send a pagination parameter. This integration therefore calls
the private `CatGenieClient._request` helper with one explicit `startTime`
query parameter. No other parameter is sent, and this code does not call the
public getter for a windowed read.

Prior read-only API inspection verified these array shapes and the parameterized
GET. A captured response is one bounded window, not a complete history.

`startTime` is the UTC ISO-8601 form of local midnight at the start of a
seven-local-day window, including today. Seven days is this integration's
choice. It is not a claim that the app requests seven days. The app chart
length constant is not a proven request operand.

## Clock and coverage

Visit time prefers an aware `fields.rtcStart`. Flush time prefers an aware
`fields.rtcEnd`. `time_source` names the field actually used: `rtcStart`,
`rtcEnd`, `machineTS`, or `timestamp`.

If that field is missing, aware `machineTS` and then integer `timestamp`
may be used. A well-formed timezone-naive ISO datetime, with a `T` and no
offset, is not labeled UTC or the Home Assistant timezone. Only then, aware
`machineTS` is used when present. If `machineTS` is missing, an in-range
integer `timestamp` may be used. A present but unusable `machineTS` does not
fall through to `timestamp`. A malformed primary value is skipped. It is not
replaced by another clock or by the current time. A bare date is not a
datetime clock and does not fall back.

Synthetic example (not captured owner activity): a naive `rtcStart` of
`2026-10-30T06:00:02` and an aware `machineTS` of
`2026-10-30T02:00:00-04:00` differ by two seconds if the naive digits are
arbitrarily labeled UTC. That is not the same instant and not proof a cycle
completed. The fallback source is `machineTS`. Prior API inspection established
that naive RTC and aware machine clocks can coexist; these example values are
invented to explain the rule and are also used in offline tests.

Accepted clocks are timezone-aware ISO-8601 strings and unix seconds or
milliseconds in 2000–2100. Naive strings are not assigned a zone. Booleans,
numeric strings and out-of-range epochs are uncertain. A skipped timestamp
is never replaced with the current time.

"Today" is the local date of the explicit window end in the Home Assistant
timezone. Chart-style day buckets follow that zone, including DST. A UTC date
is not used as the local day. If Home Assistant has no usable timezone, the
fallback is UTC and is labeled `unconfigured_utc_fallback`. It is not a guess
of the device zone.

Coverage is not a complete-history guarantee. `complete_history` is always
false.

| State | Meaning |
| --- | --- |
| `missing` | The array key is absent, null, or not a list. The sensor is unknown, not zero. |
| `empty_response` | The array is present and empty. Today's visit count is 0 because no records were returned, not because every day was observed. |
| `day_zero` | Today is inside the span of attributed events and has no visit. |
| `uncovered` | Attributed events exist, but today is outside their span, or all are outside the requested window. Today's count is unknown, not zero. |
| `uncertain` | A skipped timestamp or unattributed record could belong to this device today. The count is unknown. |
| `no_attributed_records` | Records exist, but none match this device, and none are unattributed. Today's count is 0. |
| `counted` | One or more attributed visits fall on the local today. |

Days before the first attributed event, or after the last, are uncovered.
Days strictly inside that span with no event are day zeros. Visit zeros and
flush zeros are separate.

## Devices, cats, and aborts

Prior read-only API joins established these field relationships, without
publishing account activity counts or identifiers:

- sampled visits had `fields.serialNumber` equal to the raw
  device `manufacturerId`, and `fields.deviceId` equal to `macAddress`, not
  `manufacturerId`
- sampled flushes had `fields.serialNumber` equal to
  `manufacturerId`; those flush records had no `deviceId`
- the raw device field list did not include `serialNumber` or `deviceId`
- on that unit `bleConnectionId` also equaled visit `deviceId`; it is not a
  second device id, because that would assume it stays identical to
  `macAddress`

A visit matches when `deviceId` equals `macAddress`, or an extra `deviceId`
that does not contradict `macAddress`. A flush matches when `serialNumber`
equals `manufacturerId`, or an extra `serialNumber` that does not contradict
it. A contradictory extra is ignored. It is not added as another identity.
`manufacturerId` is not a `deviceId` candidate.

Valid 12-hex MAC device ids are compared canonically across case and common
separator forms. Non-MAC ids and manufacturer serials remain exact strings;
contradictory cross-id attribution remains uncertain.

The Home Assistant device-registry serial remains the manufacturer id. That
value is the cloud serial, not the cloud `deviceId`.

Records with neither id are unknown attribution. Records whose device id and
serial disagree about this unit are conflicts. Either one makes today's count
unknown. Another device's bad timestamp does not.

Sampled visits had no `petId`. Profiles may be counted, but names, ids,
weights, images and `lastVisitTime` are not copied into state and are not
visit ownership. A `petId` on a record is reported only as
`present_unverified`. There is no app pet attribution and no per-cat sensor.

`aborted` is an integer. Nonzero integers are aborted; the app shows `!` for
that case. Integer 0 is not aborted. Missing, boolean, float and string values
are unknown. They are not completed cleanings. Flush record count is not a
completed-cleaning count. `cloud_not_aborted_flushes` is a cloud outcome
inside the window, not the local completed-cleaning helper.

`visits_per_not_aborted_flush` uses not-aborted flushes as the denominator.
A zero or unknown denominator is `null`, not zero and not infinity.

Duplicate identity is a stable hash of kind, UTC time, device id, serial and
duration or abort code. Identical records collapse. A different duration or
abort code does not.

## Entities

Added only when the history coordinator is attached. Existing sensor keys are
unchanged.

| Entity | State |
| --- | --- |
| Visits today | Attributed visits on the local today, or unknown |
| Last visit | Latest in-window attributed visit time |
| Last visit duration | That visit's `durationSeconds`, or unknown |
| Aborted cycles | Nonzero integer `aborted` flushes in the window. Diagnostic. |

Attributes carry the window, timezone, coverage, day zeros, abort split and
the statement that local counters are not replaced.

## Coordinator

History is a second coordinator stored on `coordinator.history`.
`entry.runtime_data` remains the device coordinator. History refreshes every
15 minutes, which is slower than the 15-second active and 60-second idle
device polls. Its own `update_interval` is None so it cannot shorten device
polling. A history failure is logged and isolated. It does not raise
`ConfigEntryAuthFailed`; the device coordinator still does that if the token
is dead.

## Not proven

- The naive-RTC fallback has not been replayed against the live account.
  This file does not claim that replay has run.
- Offline lifecycle and parser tests do not establish live identity-filter
  acceptance or prove that a deployed 15-minute tracker has fired.
- The prior parameterized GET with explicit `startTime` verified a response
  shape, not completeness. `complete_history` stays false.
- The unparameterized read is separate identity evidence, with no `petId`
  on sampled visits. It does not prove the no-parameter window length.
- Abort codes other than zero versus nonzero are not interpreted.
- Retention, pagination and the app's default day count remain unverified.
- This is not a calendar, and it does not install a frontend.
