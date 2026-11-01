# Review overview: changes from upstream

This branch collects additions and reliability fixes relative to upstream
[`317e41f`](https://github.com/PrimeAutomation/HA-Catgenie/commit/317e41f14315841da313d030194ba74d76f09306).
It is a reference for review and possible smaller follow-up PRs, not a request
to merge everything together. [PR #3](https://github.com/PrimeAutomation/HA-Catgenie/pull/3)
remains focused on operation-state compatibility and error reporting.

## New controls and settings actions

- **Cycle buttons:** Pause, Resume, Abort, and firmware-gated No-scoop wash.
  These are distinct from the existing Start and Stop commands. Existing entity
  enabled/disabled choices are preserved. See [pause and resume](pause-resume-control.md)
  and [abort and no-scoop](cycle-controls.md).
- **Settings controls:** Cat / Manual / Time activation selector, volume,
  panel auto-lock timeout, and cat activation delay. These add writable controls
  alongside reported values; the upstream integration already exposed several
  of those values as sensors. See [activation delay](cat-activation-delay.md)
  and the [entity list](../README.md#entities-per-device).
- **Native HA actions:** `catgenie.set_schedule` and
  `catgenie.set_do_not_disturb`, with explicit IANA timezone and reference date,
  caller authorization and guarded fresh reads. Schedule writes do not activate
  Time mode. These are action forms, not device-page time editors. See
  [schedule actions](schedule-actions.md) and [schedule/DND](schedule-dnd.md).

## Additional read-only information

- **Activity history:** visits today when coverage supports a count, last visit
  and duration, aborted-cycle information, and history/attribution diagnostics.
  A separate reader keeps history failures from replacing device-state polling.
  See [activity history](activity-history.md).
- **Notification and firmware information:** notification events and firmware
  availability/release-note information from the account feed. No firmware
  installation or account-notification settings are exposed. See
  [read-only information](read-information.md).
- **Reported diagnostics:** additional cartridge, timezone/DST and configuration
  details. Missing or unsupported measurements remain unknown rather than
  becoming library-default values. See [reported diagnostics](diagnostics.md).

## Improvements to existing behaviour

- **Status and errors:** preserve unknown integer operation states, distinguish
  normal paused reports from faults, describe supported active-error codes, and
  retain unknown codes. Readable status and narrowly evidence-gated Idle progress
  improve display without inventing running-cycle telemetry. See
  [operation status](readable-operation-status.md) and
  [error-code evidence](error-code-provenance.md).
- **Cartridge capacity:** refine the existing capacity calculation and describe
  its mode-dependent basis; capacity was already an upstream entity. See
  [cartridge capacity](cartridge-capacity.md).
- **Settings safety:** serialize integration-local writes per device across fresh
  reads, writes and refreshes. Preserve supported companion settings and refuse
  uncertain writes. This does not provide concurrency control over the vendor app.
- **Reliability and privacy:** isolate malformed device records, retain raw-value
  provenance before model coercion, serialize overlapping token refreshes, avoid
  logging vendor exception payloads in relevant failure paths, contain malformed
  history timestamps, and clean up setup failures, unload and core shutdown.
- **Existing features retained:** phone/SMS authentication, Start/Stop, panel lock,
  supported extra-cycle switches and the dashboard card are not new features of
  this contribution.

## Compatibility and verification

- Declared minimum: **Home Assistant 2025.7.0 / Python >=3.13.2**. The typed
  schedule-row selector needs HA object-selector support introduced in that
  release; this is not a minimum inferred from Python alone.
- Also tested: **HA 2026.10.4 / Python >=3.14.2**.
- Both targets pass **26 test wrappers / 324 child test methods**, with no
  failures, errors or skips. Most legacy cases use HA/transport test seams;
  native HA contracts supplement them. Focused runtime/control/data counts
  overlap and must not be added to the child total.
- Runtime code at `7c3e8cff` was installed and checked on HA 2026.10.4:
  source readback, entity preservation,
  dashboard, recovery configuration and counters. This overview and its README
  link are documentation-only additions to that runtime revision.

See [test instructions and validation scope](../tests/README.md) for commands,
actual test environments and the historical test-environment dependency
constraint. Local results do not establish remote GitHub CI or HACS validation.

## Deliberate boundaries

Missing history coverage is not a measured zero. Vendor nested-settings merge
semantics, recurring firmware DST execution, fault Resume effects on physical
cartridge allowance, and finishing-cycle equivalence remain unverified. Device
commands do not implement an automatic water-fill recovery workflow. Personal
recovery automation and dashboard customizations are not part of this branch.

For the complete capability/deferred-work inventory, see
[feature coverage](feature-coverage.md). Its entries are topics, not an entity
count; a topic can remain on hold while an implemented subset is available.
