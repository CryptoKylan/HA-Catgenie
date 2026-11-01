# Abort and no-scoop

Normal-cycle Abort and No-scoop were owner-verified. Abort stopped the cycle. No-scoop went straight to wash, skipping scoop. Fault resume, cartridge allowance effects, and physical finishing-cycle equivalence are not proven. These are behavior capabilities, not a statement about any host's deployment.

Both buttons are enabled by default for a new entity registration. Home Assistant applies that default only when the entity is first registered. This integration does not rewrite an existing enabled or disabled choice. A previously disabled entry needs an explicit Home Assistant enable.

## Abort

The app `stopClean` posts `{"state": 4}`. That is ABORT, not the integration Stop command. Stop still calls `stop_cleaning` and posts state 0. This button does not replace Stop and does not call start or stop.

It requires an explicit connected `reportedStatus`. A reported integer is not a send guard. It does not recover a water-fill fault. It does not restore cartridge allowance. A failed press is not retried by this button. The pinned writer may repeat the same POST once after HTTP 401. That inherited retry is not a new retry here.

## No-scoop wash

The app `playSpecial` posts `{"state": 129}` for the wash-only no-scoop cycle. That is not a finishing cycle, not state 4, and not extra wash. The press handler does not re-check firmware. The settings row that leads to that screen does.

The traced gate, in app `render` at hasm 573777–573803:

- Source field is `device.fwVersion`.
- Letters are stripped with `replace(/[A-Za-z]/g, '')`.
- `validateString` with one argument requires a non-empty string. Missing or empty skips `gte` and the row stays hidden.
- If that check passes, `semver.gte(stripped, '8.5.81')` is `compare >= 0`. The threshold string is `specialCycleThresholdVersion` at hasm 251367.
- Strict `gte` has no loose option. A malformed non-empty version throws in the app. This writer refuses missing and malformed versions instead of sending.
- Bundled SemVer also refuses a version longer than 256 characters (`MAX_LENGTH` at hasm 576783) and a major, minor, or patch above `9007199254740991` (`Number.MAX_SAFE_INTEGER`, hasm 576778–576784 and 577125–577140). This gate applies those limits to the letter-stripped string and rejects an oversized component before converting it. A very long digit string returns false. It does not raise.
- This is not full node-semver. Whitespace-wrapped versions, prerelease tags, and build metadata stay refused, even when bundled semver would accept them after trim.

Equal `8.5.81` passes. `8.5.80` does not. Comparison is numeric, so `8.5.9` does not pass and `8.10.0` does. `9007199254740991.0.0` passes. `9007199254740992.0.0` does not. A trailing letter such as `8.7.205R` is stripped before the compare. A passing gate is not proof the unit accepts state 129.

State 129 is not on the ungated allowlist. That allowlist is states 2, 3, and 4. The shared operation writer posts 129 only when firmware is passed into that call and this gate accepts it. A button or helper check is not a substitute. Omitted, malformed, below-threshold, and oversized firmware are refused before any writer call.

The button requires an explicit online report. An ineligible, missing, or malformed `fwVersion` makes it unavailable, and a press raises before any request. It does not call start or stop. It does not recover a water-fill fault. It does not restore cartridge allowance. It does not replace Stop.

Offline regression tests do not establish firmware acceptance beyond the observations above.

## Start, Stop, and offline policy

Start, Stop, Pause, Resume, Abort, No-scoop, and configuration switches require
an explicit connected report; unavailable, missing-connectivity, and explicitly
offline devices are refused locally without actuation. No reported operation
integer is used to choose a command. Existing entity ids, names, registration
defaults, confirmations, and opcodes are preserved.

Stop cleaning remains the library's state 0 command. Abort cleaning remains the
app stopClean state 4 command. These are distinct commands, not interchangeable
labels or a new recovery flow. Neither is removed, renamed, or disabled here;
any consolidation requires an owner decision. Firmware fault recovery and
cartridge allowance effects remain unproven.

There are no integration-level command retries. The pinned catgenie 0.1.6
client can refresh authentication and resend the same POST/PUT once on HTTP
401. Thus "once" here describes the integration's writer invocation, not an
exactly-once firmware execution guarantee.
