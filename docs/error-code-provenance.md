# App-derived active-error descriptions

Codes 3, 4 and 6 were derived by statically inspecting the CatGenie Android app,
package [`com.petnovations`](https://play.google.com/store/apps/details?id=com.petnovations),
version 1.8.253 (version code 623), obtained from its
[public distribution listing](https://apkpure.net/catgenie/com.petnovations/download).
They have not been reproduced on the observed A.I./firmware 8.7.205R.

## Evidence path

The app's shared `NOTIFICATION_TYPES` object defines:

- `DRAINAGE_PROBLEM = 3`, displayed as **Drainage Issue**.
- `BI_METAL = 4`, displayed as **Dryer Overheating**.
- `EMPTY_CARTRIDGE = 6`, displayed as **Empty Cartridge**.

These are also used for device faults. The device-card constructor passes its
`activeErrors` array into `_getStatusMap`, which passes it into
`_getErrorWarningsSortedList`. Each raw code indexes the shared
`TYPE_TO_LEVEL_MAPPER`, establishing the active-error namespace connection.

For labels, `getNotificationIntlMessage` switches on an object's `type` field
using the same enum. A separate status-label call passes `{type: code}` and
selects the corresponding English message object. The raw-code call in the
sorted-list helper alone would not prove successful message selection.

This trace is important: matching notification numbers alone would not establish
that they describe the device's active-error namespace. Operation-state integers
remain a separate namespace and do not select these descriptions.

## Reproduction

The inspected XAPK's SHA-256 is:

```text
549da129a62b396cefe8dbe69677ea3f2033622b60e859eff501678432b1f249
```

The listing/latest download may change. Match the version and hash rather than
assuming a newer archive is identical. The archive contains `com.petnovations.apk`,
whose `assets/index.android.bundle` is Hermes bytecode 96. It was disassembled
with [`hermes-dec`](https://github.com/P1sec/hermes-dec) 0.1.8 using
`hbc-disassembler`; the Android app was never installed or executed.

In that disassembly, the enum object is at line 338496, and the English message
objects are at lines 491304–491310. `_getErrorWarningsSortedList` is function 12958
and `_getStatusMap` is function 12959. Message-switch destinations `0x400`, `0x3df`
and `0x3be` select the drainage, overheating and empty-cartridge messages.

The archive came from a third-party distributor; this is static app evidence,
not manufacturer documentation, independent publisher attestation or a live
hardware test. No app binaries are included in this repository.
