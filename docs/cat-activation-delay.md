# Cat activation delay

Minutes box. Wire value is seconds. No Do Not Disturb editor.

## Proven

- Constants are 300, 600, and 1800 seconds. Snap is multiples of 300 from 300 through 1800.
- The label divides the stored integer by 60. 1800 is 30 minutes.
- Choices are 5, 10, 15, 20, 25, and 30 minutes. There is no 0.
- The save object is exactly `dndFrom`, `dndTo`, and `catDelay`.
- A null DND selection copies the stored strings with no conversion.
- Both empty strings are echoed only when both stored fields are already empty.
- Both `HH:MM:SS` strings are echoed, including a cross-midnight pair and equal clocks.
- `fixConfigurationSchedules` leaves an object with no `schedule` key unchanged.

## Refused before any request

- Missing device, unavailable cached data, or an explicitly offline cached device.
- A minute value outside the six choices.

## Refused after the fresh GET, before PUT

- Missing or ambiguous fresh device, offline fresh device, or missing configuration.
- Missing `catDelay`. The library default of 600 is not used.
- A missing DND key, a non-string, a mixed empty/clock pair, or any string that is not empty or `HH:MM:SS`.
- These refusals perform no PUT, do not blank DND, and do not apply `configuration.timezone`.

## Not this control

This delay control still only echoes a supported DND pair. It does not convert clocks. The separate Do Not Disturb action owns window writes. The diagnostic sensor remains seconds and was not changed.

## Local write coordination

All configuration writers on the same account coordinator share one async lock
per manufacturer id, including delay, DND, schedule, activation, volume,
auto-lock, and switches. The lock spans the fresh read (where required), PUT,
and refresh. Failure and cancellation release it. Other devices do not wait on
this device's lock. This closes local HA read/modify/write overlap, not races
with the official app, another client, or another integration instance. It is
not remote compare-and-swap, and a refresh is not vendor confirmation.
