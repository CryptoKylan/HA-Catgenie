# Cartridge capacity

The cartridge-remaining sensor preserves `remainingSaniSolution` exactly as
reported. The cloud already adjusts that count for the selected activation mode;
the integration must not divide it again or maintain a second consumption ledger.

The diagnostic cartridge-capacity sensor uses this precedence:

1. A positive, finite numeric `totalSaniSolution`, when supplied by the API.
2. Otherwise, the manufacturer's standard CatGenie A.I. rating: 240 cleanings
   in Cat Activation, or 120 in Manual/Time Activation.
3. Otherwise, unknown. Missing or maintenance cartridges are unknown even if
   the response includes a stale maximum.

`capacity_source` identifies `device_reported`, `manufacturer_rating`, or
`unknown`. A recognized configuration also supplies `cleaning_mode` (`cat`,
`manual`, or `time`). Existing entity identity and the `cycles` unit are retained.

The rated fallback requires an explicitly supplied configuration mode and
integer manual flag, plus regular-cartridge `tagType: 1`. The manual flag takes
precedence. Missing or unsupported inputs do not inherit Pydantic defaults.
The app's cartridge types 0 (missing) and 3 (maintenance) do not use a standard
cleaning-cartridge rating. Other types can supply their own numeric maximum,
but do not receive the fallback. This is not a Whoosh capacity calculation.

## Evidence

- [Manufacturer's A.I./Whoosh comparison](https://catgenie.com/pages/catgenie-ai-compared-to-catgenie-whoosh)
  specifies 240 for A.I. Cat Activation and 120 for manual/scheduled activation.
- [Standard SaniSolution cartridge](https://catgenie.com/collections/supplies-accessories/products/sanisolution-cartridge-scent-free)
  gives the same ratings for A.I./120 cartridges.
- Read-only API inspection around a mode round trip on A.I. V1, firmware
  8.7.205R, established mode-adjusted remaining counts. The table below is
  a synthetic illustration, not the owner's observed cartridge levels:

  | Activation | configuration.mode | configuration.manual | remainingSaniSolution |
  | --- | --- | --- | --- |
  | Cat | 0 | 0 | 160 |
  | Manual | 0 | 1 | 80 |
  | Time | 1 | 0 | 80 |
  | Cat, restored | 0 | 0 | 160 |

  In the prior inspection Home Assistant and the official app agreed, and
  `totalSaniSolution` was absent. This is evidence for mode-adjusted remaining
  counts, not a mixed-mode cleaning-consumption test. The synthetic numbers
  above do not add new live observations.
- Android app 1.8.253 defines `TAG_TYPE` as missing 0, regular 1, maintenance 3.
  See [app provenance](error-code-provenance.md) for the inspected archive.
- Predecessor integrations look for `totalSaniSolution`; that lookup does not
  demonstrate that every firmware supplies it. The pinned client preserves
  undeclared fields in `model_extra`, and this integration already reads that
  location. The observed absence is not a field discarded by its parser.

The percentage progress sensor and cleaning commands are unchanged.
