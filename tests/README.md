# Offline decoder regression tests

For the full suite use an isolated Python 3.14 environment with the current
Home Assistant target (2026.10.4 requires Python >=3.14.2):

```sh
python -m pip install homeassistant==2026.10.4 catgenie==0.1.6 pydantic==2.14.2 curl_cffi==0.17.0 PyYAML==6.0.3
CATGENIE_REQUIRE_CONTRACTS=1 python -B -m unittest discover -s tests -v
```

Top-level `tests/test_*.py` files are discovery wrappers. Each launches its
`tests.unit_cases.test_*` implementation in a fresh interpreter through
`tests/process_harness.py`. `unit_cases` deliberately has no `__init__.py`, so
standard discovery does not collect both levels. Cross-harness imports use only
canonical `tests.unit_cases.test_*` names, including the shared settings harness;
the child checks its settings module and exported class/function identities.
Parent real HA/probatio modules and `sys.path` are not replaced by those children.
Legacy children own their synthetic HA/HTTP import worlds until process exit;
they do NOT promise to restore every child global. Most use actual pinned
CatGenie Pydantic models and integration adapters, but are not all real-HA tests.
Payloads are synthetic; no cloud requests or device commands are made.
These unit tests do not replace testing inside a running Home Assistant instance.

Run from the repository root, for example:

```sh
CATGENIE_REQUIRE_CONTRACTS=1 python -B -m unittest tests.test_schedule_actions -q
CATGENIE_REQUIRE_CONTRACTS=1 python -B -m tests.test_schedule_actions -q
```

Bare file/module invocation from inside `tests/` is not a supported import
layout; use the root commands above, not a second bare settings-harness name.
Every wrapper has a bounded subprocess timeout. Missing optional dependencies
skip by default, but `CATGENIE_REQUIRE_CONTRACTS=1` makes them fail (as in CI).
Full verification requires HA 2026.10.4, CatGenie 0.1.6, Pydantic 2.14.2,
curl_cffi 0.17.0 and PyYAML 6.0.3 plus HA's installed transitive dependencies
(including its real schema backend). The dependency-only compatibility job is
not a full-HA contract run. `test_process_harness.py` tests missing optional and
required dependencies separately; the schema stub's ALLOW_EXTRA/PREVENT_EXTRA
checks are fixture policy only. Actual schema refusal and registry/task method
signatures are verified against installed HA by `test_ha_setup_contract.py`.

`test_runtime_repairs.py` and `test_controls_repairs.py` run clean subprocesses
with real HA imports (no global HA stubs). Runtime cases cover phone/code and
reauth mapping with mocked auth, safe errors, malformed MAC omission, pinned
adapter single-flight refresh, cancellation/failure release, and workflow pins.
The 22 runtime methods also cover post-allocation setup boundaries, partial
platform forwarding, close failure and callback reentry, overlapping close
waiters, setup cancellation, late timer-registration failure, and core shutdown.
The control and data regression subprocesses each contain 13 methods. These
counts are nested coverage, not additions to the wrapper/child totals below.
`read_information_ha_contract.py` also executes real ConfigEntries setup/unload,
background cancellation, interval cleanup, first-refresh failure cleanup, and
action-setup failure cleanup. All use synthetic data and refuse vendor network
calls. They do not validate SMS delivery or real firmware acceptance.

CI runs the full required-mode suite and real-HA runtime/startup contracts on
HA 2025.7.0 / Python 3.13 and HA 2026.10.4 / Python 3.14. The minimum-runtime
job constrains `pycares==4.11.0`: historical HA's `aiodns==3.5.0` admits newer
pycares in metadata but cannot import the 5.x API. This is a test-environment
constraint, not an integration dependency override. Remote CI, lint, hassfest
and HACS validation are not established merely by these local executions.
A separate HA-absent Python 3.13 job runs only
`test_unknown_operation_state.py` with dependency pins and import seams; it is
not used as evidence of real-HA compatibility.

For offline review against an already-extracted copy of the pinned dependency,
set `CATGENIE_TEST_DEPENDENCY` to the directory containing its `catgenie` package.
The installed dependency is used when that variable is unset.

The suite covers strict integer-state validation, both field aliases, inherited
model fields and schedule normalization; observed error codes 2 and 5 and
app-derived codes 3, 4 and 6 in their separate namespace; vendor text, unmapped
and mixed codes; normal operation and fault clearing; missing/offline data;
stable entity identities; and long error states with complete diagnostic details.
It also replays a synthetic normal-cycle
sequence through the actual sensor classes without changing progress semantics.

`test_schedule_dnd.py` checks the app local/UTC clock contract, DST gap and overlap refusal, reported-offset disagreement, DND as one window with `catDelay`, empty-schedule and mode-coupling refusal, and that the old prepared fragment stays nonsendable. `test_dnd_action.py` and `test_schedule_actions.py` check the separate settings actions. `test_action_permissions.py` checks caller permission before vendor I/O. None of these call the vendor or a running Home Assistant.

`test_cartridge_capacity.py` checks reported-capacity precedence, labelled
manufacturer ratings for Cat/Manual/Time activation, the observed round-trip
remaining counts, manual-override precedence, missing/defaulted configuration,
invalid maxima, missing/maintenance/unsupported cartridges, and unchanged
entity identity, units and numeric progress semantics.

`test_settings_controls.py` checks the activation select and volume number
against the real configuration models. Mode writes are the paired raw fields
only: cat is mode 0/manual 0, time is mode 1/manual 0, and manual keeps the
current mode with manual 1. Volume writes are `volumeLevel` integers 1–7.
Schedule, nested `binaryElements`, and sibling settings are omitted rather
than rewritten. Guards refuse unknown, offline, and incomplete configuration
before any request. A PUT acknowledgement is not vendor confirmation and is
not written into the coordinator device. After the PUT await returns, the
select or number holds the requested value until a later poll matches it,
the device is missing, or two idle poll intervals elapse. The read-only
cleaning-mode and volume-level sensors are not part of that hold. These
tests do not validate a live vendor merge. Cat-delay and auto-lock number controls
are covered by `test_cat_activation_delay.py` and `test_auto_lock_timeout.py`:
5–30 minutes in 5-minute steps, plus 0/off for auto-lock only.

`test_settings_feedback.py` checks that hold against a refresh that applies
a new stale device snapshot, a matching snapshot, rejection, refresh
failure, offline/missing, the bounded deadline, and overlapping writes.

`test_activity_history.py` checks the cloud statistics parser: local day
boundaries, duplicate events, multi-device filtering, aborted versus missing
flush outcomes, unknown pet attribution, and a zero visits-to-cycles
denominator. Extreme integer epochs and unrepresentable UTC/local ISO clock
boundaries are skipped without hiding valid peers or fabricating a clock.
Payloads, including the naive-RTC example times, are synthetic. The public `get_pet_statistics()`
signature is the real pinned client and is not called. These tests do not
start Home Assistant or prove a live history poll.

`test_operation_status.py` checks the readable text sensor through the pinned
models and sensor callbacks. Explicit online idle is Idle even when progress
is absent in a constructed model or 100. Actual wire payloads missing required
progress are quarantined, not accepted as partial telemetry. Explicit online
cleaning shows `0%`, `42%` and `100%`.
Invalid progress, explicit offline, missing status, Pydantic defaults, faults
and unsupported states do not become a false Idle. Numeric progress identity,
unit and values stay unchanged.

`test_resume_control.py` checks the pause and resume buttons. Both are enabled by default for a new registration, require an explicit online report, and post through the pinned operation writer. Pause posts literal state 2. Resume posts literal state 3. Neither calls start or stop, retries, or writes coordinator state. The integration does not rewrite an existing entity-registry enabled or disabled choice. Reported integers are not a send guard. Payloads are synthetic. These tests do not start Home Assistant or send a device command.

`test_cycle_controls.py` checks the abort and no-scoop buttons. Both are enabled by default for a new registration and require an explicit online report. Abort posts literal state 4 and does not replace Stop. No-scoop posts literal state 129 only when letter-stripped `fwVersion` is a strict numeric version greater than or equal to 8.5.81, at most 256 characters, and with each component at most 9007199254740991. The shared writer enforces that gate for state 129; omitting firmware does not send. Missing, malformed, and oversized versions return false and nothing is sent. Payloads are synthetic. These tests do not start Home Assistant or send a device command.

`test_paused_state.py` checks reported state 2. An explicit connected report with an empty active-error list is paused on the enum, text, and error sensors. Water-fill code 2 with the same operation state stays a fault. Missing, malformed, offline, and unknown states do not become paused. Numeric progress is unchanged. Payloads are synthetic. These tests do not start Home Assistant or send a device command.

`test_read_information.py` checks the raw notification parser with synthetic fixtures and runs `read_information_ha_contract.py` against the installed Home Assistant. That contract starts a local core, registers the diagnostic entities, and proves a feed failure does not reauthenticate the entry. Equal-time conflicts stay unknown instead of an order-chosen version. A device-firmware change drops the previous installed-notes label without a new GET. it does not call the vendor. Synthetic type-24 fixtures are not firmware acceptance.

## Additional inventory and counting

The discovery total counts wrapper runner methods, not implementation methods.
Each `CATGENIE_TEST_RESULT` JSON line separately reports its implementation's
tests/failures/errors/skips. Do not add wrappers to child counts, or nested
runtime/controls/data runner methods to their nested methods, or call their sum
all-real-HA coverage. Legacy stub-backed cases and real-HA subprocess contracts
are mixed. A runner can execute several nested methods.
The required-mode discovery run currently reports 26 wrapper methods and 324
child methods, with zero failures, errors, or skips on both tested HA targets.
Do not add the runtime/control/data subprocess counts to those totals.
`test_data_repairs.py` runs `data_regression_cases.py` in a clean real-HA process
with real pinned Pydantic wire validation and fake HTTP only. Its 13 methods
cover per-device quarantine, unknown/default provenance, 812→missing→812,
strict mode/manual and capacity agreement, private snapshot serialization,
offline pause/progress, history coverage/MAC attribution, recorder exclusions,
and PNG format. This is not recorder database or live firmware acceptance.

Other modules: `test_idle_progress.py` checks idle fallback; `test_diagnostics.py`
checks reported cartridge/timezone/DND entities; `test_unknown_operation_state.py`
checks strict state parsing and entities through HA seams;
`test_action_metadata.py` and `test_metadata_sol_regressions.py` cover metadata
(the latter runs a real-HA subprocess); `test_settings_labels.py` checks labels;
`test_ha_setup_contract.py` checks selected setup contracts, not complete older-HA
compatibility. Auto-lock and cat-delay files cover payloads, supported choices,
seconds/minutes conversion and preservation/refusal paths. Missing wire progress
is rejected by the pinned model; constructed-model display tests are not proof
that such a partial wire report is accepted. Device-page firmware refresh is a
reload limitation, not a newly implemented registry listener.

Slash-containing synthetic device IDs in operation-writer cases pin the existing
unescaped path behavior only (CV-09). They do not establish a new accepted ID API,
escaping policy, or vendor acceptance. That residual production assumption is
unchanged and requires a separately approved cross-writer scope decision.
