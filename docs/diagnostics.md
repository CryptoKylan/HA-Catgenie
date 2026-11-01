# Reported configuration sensors

The helpers live in `reported_config.py`. These are diagnostic-category sensors,
not Home Assistant's Download diagnostics platform or a credentials export.

These sensors read the device already stored by the coordinator. They do not
poll, write configuration, or register a schedule or Do Not Disturb control.

## Cartridge type

`tagType` is mapped only when the payload set an integer:

| Code | State |
| --- | --- |
| 0 | missing |
| 1 | regular |
| 3 | maintenance |
| any other integer | unknown, with `raw_tag_type` |

There is no `normal` label. A missing field, boolean, float, or string is
unknown rather than cartridge type 0. App `TAG_TYPE` in Android 1.8.253 is
`MISSING_CARTRIDGE` 0, `REGULAR_CARTRIDGE` 1, and `MAINTENANCE_CARTRIDGE` 3.
Capacity ratings are unchanged: regular type 1 still uses 240 or 120, and
remaining cleanings are still the reported count.

## Reported timezone

The state is the explicit `configuration.timezone` string. The model default
`+00:00` is not published when the field was omitted. The sensor does not
guess a Home Assistant zone, interpret daylight saving time, or treat the
offset as a schedule conversion zone. Explicit `dstFrom` and `dstTo` strings,
when present, are raw attributes with `dst_semantics: unverified`.

## Do Not Disturb

`dndFrom` and `dndTo` are shown as reported configuration strings. A pair of
valid `HH:MM:SS` values is one entity, with those strings in `clock_entries`.
The state is not converted with `configuration.timezone` or with an IANA zone.
Empty or equal strings are `not set`. That is not a verified disable encoding.
A missing field stays unknown; it is not treated as an empty string.

## Schedule display hold

`scheduled_cycles` remains the count sensor and still carries the existing
entry dump. No second schedule entity is registered. `display_schedule` can
build a local view only for an explicit IANA zone and reference date, and it
labels device storage unverified. A reported UTC offset is not an IANA zone
and does not establish daylight-saving rules. Calling the helper
from this callback would be a guessed conversion, so local schedule display
is `hold`.
