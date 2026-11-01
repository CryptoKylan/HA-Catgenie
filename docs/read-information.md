# Read-only notification and firmware information

One account reader. It does not poll once per device or once per notification type, and it does not replace the device coordinator.

## What is read

- `GET notification/v1/push/user`, no query. The probed body was `{userId, notifications}` and the list length was 0. That empty list is this response, not a complete history and not proof that no events exist.
- `GET device/update/versions/comments?name=<version already in hand>`. The probed installed-firmware notes body was `{comments: string}`. The query key is `name`. An empty string is not shown.

The raw dict is parsed. The pinned list model is not used, because a missing type must not become 0 and a missing id must not become an empty string.

## Cadence

The app skips a refetch inside an environment value that was not recovered. Thirty minutes is a local bound, slower than the 15-minute history poll and the 15-second/60-second device poll. It is not a vendor limit.

## Entities

Three diagnostic sensors per device, attached to the existing device. Current firmware is represented by device-page `sw_version`, populated on setup/reload. The device page does not refresh firmware on each coordinator update; reload the integration after a firmware change. There is no second current-firmware sensor.

| Entity | State |
| --- | --- |
| Latest notification | App enum name, raw unknown integer, or `unknown` when this response has no authoritative attributed item |
| Announced firmware | `version` from one unambiguous device-attributed type-24 item, or `unknown` |
| Firmware release notes | `available` when comments is a non-empty string for the current installed version or an unambiguous announced version, otherwise `unknown` |

No type-24 item is unknown. It is not up to date, and it is not the installed version. Equal offset-aware times that do not agree are also unknown: the selection is `ambiguous`, not a response-order or version-text winner. Installed notes follow the device coordinator's current firmware. A firmware change drops the previous installed label immediately and does not GET notes by itself. Types 101–106 are counted and their bodies are discarded. Parent and device ids that disagree stay unattributed. Names, emails, and the account id are not attributes.

## Failures

Release-note attribution follows the device coordinator, not the possibly stale
device-page software version. Notes and history diaries remain available in
current UI attributes but are excluded from recorder attribute history; no
full-text historical notes retention is promised.

A feed failure becomes `UpdateFailed`. It does not start re-authentication and does not change the device poll. A notes failure for one version does not erase a successful feed. The notes entity is unavailable when every relevant notes query failed.

## Out of scope

No `UpdateEntity`, install, approve, delete, or `push/settings`. `get_firmware_info` is not called. Synthetic type-24 fixtures are parser tests, not a live latest version.
