# Readable operation status

`sensor` key `operation_status` is a text entity. It does not replace
`operation_progress`, `operation_state`, or `operation_error`.

The numeric `operation_progress` sensor preserves finite reported numbers
from 0 through 100, including valid idle percentages such as `100`. It does
not guess whether an idle percentage is stale. Booleans, numeric strings,
out-of-range values and nonfinite numbers are unknown, not coerced percentages.
Its unit remains `%`, its state class remains measurement, and its identity
is unchanged.

A valid numeric percentage is preserved even while disconnected. It is last
reported progress, not current health or proof that a cycle is still running.
The text sensor is separately unavailable for explicit disconnection.

When progress is absent or the numeric vendor sentinel `255`, it displays
`0%` only for an explicit connected report with an explicitly supplied real
integer state `0`, an explicitly empty `activeErrors` list, and absent or
blank-string vendor error text. The vendor may omit `error` on idle
wire reports; a supplied null, malformed, or nonblank value still prevents
fallback. This optional-error rule is idle-only and does not change pause or
fault classification. This zero is a display convention for idle,
not measured progress or proof of a completed cycle. Missing/malformed state,
offline/unknown connectivity, faults, and unconfirmed error clearance never
receive this fallback. Running missing/sentinel progress remains unknown.
Valid reported percentages in other states are preserved, not synthetic zeros.
Raw model telemetry and `clean_progress_pct` are untouched. The pinned model
still rejects wire payloads missing required `progress`; the display helper's
absent-value handling does not relax dependency validation or update failures.
Visits/history semantics, commands, and text labels are unchanged.

The text sensor uses a stricter reading:

- Explicit `reportedStatus` of `connected`, in any letter case, plus explicit
  operation state `0`: **Idle**. Progress may be missing, `255`, or a stale
  `100`. An active fault does not change Idle and is not cleared.
- Explicit connected plus explicit operation state `1` and a finite progress
  from 0 through 100: percentage text such as `42%`. There is no unit or
  numeric state class on this entity.
- Explicit connected cleaning with missing, `255`, out-of-range, boolean,
  nonnumeric, or nonfinite progress: None. Home Assistant shows that as
  unknown. The text is never the string `unknown`, and no percentage is
  invented. Boolean and numeric-string progress are coerced by the pinned
  model; the original value is kept beside that coercion so both display
  sensors can reject it without modifying stored telemetry.
- Explicit `reportedStatus` that is not connected, including `disconnected`,
  `offline`, and an empty string: the text sensor is unavailable. Its value
  is not Idle.
- Missing `reportedStatus` is not online. The integer `status` field is not
  used as a substitute, including `2`. Pydantic's empty default is not an
  explicit offline report, so the entity stays available and the value is
  None rather than Idle.
- Missing `operationStatus` uses the model default of idle and progress
  `255`. That default is not an explicit idle report.
- Explicit connected reported state `2`, an explicit empty `activeErrors`
  list, and blank vendor error text: **Paused**. Numeric progress, including
  a value from 0 through 100, does not become percentage text. The numeric
  progress display still preserves a valid reported percentage.
- Any other operation state `2`, including active errors, missing errors,
  malformed errors, and offline, is not Idle and not Paused. Fault text, if
  any, remains on `operation_error`. Other unsupported integers stay that
  way too. They are not remapped to idle.

This is an offline contract. It does not change polling, commands, recovery,
or dashboard resources.
