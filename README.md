# CatGenie A.I. for Home Assistant
 
An unofficial Home Assistant integration and dashboard card for the
[CatGenie A.I.](https://www.catgenie.com/) self-washing litter box by PetNovations.
It signs in the way the official app does (phone number plus SMS code), so no
token has to be captured by hand, and it exposes the unit's status, controls
and an animated dashboard card.
 
## Credits
 
This project builds on the work of others and through vibe coding with Claude. Thank you to:
 
* [Rukongai/CatDjinni](https://github.com/Rukongai/CatDjinni): reverse engineering research: signing algorithm, Frida scripts
* [appkins/hass-catgenie](https://github.com/appkins/hass-catgenie): earlier HA integration (requires manual refresh token)
* [PrimeAutomation/petnovations](https://github.com/PrimeAutomation/petnovations): earlier HA integration (same limitation)
Also used directly:
 
* [kclif9/catgenie-api](https://github.com/kclif9/catgenie-api) (MIT), published on PyPI as
  [`catgenie`](https://pypi.org/project/catgenie/). This is the async Python client that
  does the authentication, request signing and API calls. The integration depends on it.
The integration was written from scratch. The sensor list follows the earlier
PrimeAutomation integration, but no code was copied from it.
 
## Observed active-error codes

The `operation_error` sensor preserves nonempty vendor error text. When that
text is absent, it describes `activeErrors` without changing the separate
`operationStatus.state` value:

- **5 — Cleaning solution cartridge missing.** Observed on a CatGenie A.I.
  running firmware 8.7.205R after physically removing its SaniSolution
  cartridge. In that observation the operation state remained 0 (idle).
- Other active-error codes remain explicitly unknown, with their raw values
  retained in the `active_errors` attribute. This is not a complete or
  manufacturer-verified error catalogue.

This diagnostic mapping does not start, stop, retry or reset the device.

## Repository layout
 
```
catgenie-ha/
├── hacs.json
├── README.md
└── custom_components/catgenie/
    ├── __init__.py        setup and teardown
    ├── manifest.json      domain, version, requirements
    ├── const.py           constants and polling intervals
    ├── config_flow.py     phone + SMS login, re-authentication
    ├── coordinator.py     polling and error handling
    ├── client.py          client subclass that fixes a payload quirk
    ├── entity.py          base entity, device info, command helper
    ├── sensor.py
    ├── binary_sensor.py
    ├── button.py
    ├── switch.py
    └── translations/en.json
```
 
Delivered separately as front-end files:
 
* `catgenie-card.js`: the animated custom Lovelace card (copy to `/config/www/`).
* `catgenie-card.yaml`: an earlier, simpler card made only from built-in cards. The custom card replaces it.
* `catgenie-card-preview.html`: a standalone preview of the card using simulated data.
## The integration
 
| Item | Detail |
|---|---|
| Domain | `catgenie` |
| Version | 0.1.2 |
| Dependency | `catgenie==0.1.6` (needs Python 3.13, so a recent Home Assistant; `hacs.json` sets 2025.1.0 as the minimum) |
| IoT class | `cloud_polling` |
| Polling | Every 60 seconds, or every 15 seconds while a cycle is running |
| Transport | The library uses `curl_cffi` to present a mobile TLS fingerprint, which PetNovations requires |
 
### How it works
 
* **Login (`config_flow.py`).** Two steps: the user enters a country code and
  phone number, an SMS code is requested, then the code is exchanged for credentials.
  Only the long-lived refresh token and account IDs are stored. The access token
  is refreshed automatically by the library. A re-authentication flow handles a
  rejected login, and a mismatched account aborts instead of overwriting the entry.
* **Setup (`__init__.py`).** Creates one `curl_cffi` session, rebuilds the
  credentials from the config entry, and makes sure the auth object and client
  share the same credentials instance so a refresh is seen by both.
* **Coordinator (`coordinator.py`).** Polls all devices on the account.
  Authentication failures start re-authentication. Network, API and
  validation errors surface as update failures. Polling speeds up while a
  cycle is running.
* **Client fix (`client.py`).** Real devices report schedule entries as time
  strings such as `06:00:00`, but the library's model only accepts
  dictionaries. The subclass converts them before validation and keeps the
  original string.
* **Entities (`entity.py`).** Every entity belongs to one device per unit, with
  MAC address, serial number and firmware shown on the device page instead of as
  separate sensors. Commands share a helper that reports failures cleanly and
  refreshes state afterwards.
### Entities (per device)
 
| Platform | Entities |
|---|---|
| Sensor | Last clean (timestamp), total cycles, cartridge remaining, cartridge capacity, operation state, operation progress, operation error, cleaning mode, scheduled cycles (times in attributes), cat activation delay, panel lock delay, cat sensitivity, volume level, network type |
| Binary sensor | Online, cleaning; low heater and fan shutter (raw diagnostics, disabled by default because their meaning is undocumented) |
| Button | Start cleaning, stop cleaning |
| Switch | Panel lock, extra dry, and extra wash and extra shake where the unit reports them |
 
### Known limitations
 
* The library validates responses strictly. A value it doesn't know, such as an
  unexpected operation state or cleaning mode, causes an update failure that
  names the field in the log.
* Cleaning mode follows the earlier PrimeAutomation interpretation (a separate
  manual flag, otherwise cat or time activation). The library names the modes
  differently, so this mapping is unconfirmed.
* Schedule times may be in the device's timezone or UTC. This has not been verified.
* Do Not Disturb hours are not exposed.
* A second device on the account needs an integration reload to appear.
* This is an unofficial integration that talks to PetNovations' cloud. The API
  can change without notice and the vendor does not support it.
  
## The dashboard card
 
A custom element, `catgenie-card`, drawn as an SVG that follows the unit's state.
 
| State | What it shows |
|---|---|
| Idle | Green status light, rake stowed in its bay, a grey cat that walks up to the unit |
| Cleaning | Blue pulsing light, the inner bowl spinning, clumps carried around to the rake, which dips in, lifts them and retracts into the housing, falling water drops, and a progress bar |
| Error | Red blinking light with the error text in the header |
| Offline | Greyed-out unit that doesn't respond to taps |
 
Tapping the unit asks for confirmation inside the card, then presses the start
or stop button. The cartridge window on the housing drains as the cartridge
runs down and turns red below 15%. Tapping the cartridge stat opens the sensor's
history. The stats row shows cartridge remaining, last clean (or progress while
cleaning) and mode.
 
### Installation
 
1. Copy `catgenie-card.js` to `/config/www/`.
2. Add `/local/catgenie-card.js` as a JavaScript module under Settings, Dashboards, Resources.
3. Hard-refresh the browser, or add `?v=N` to the resource URL after an update.
### Configuration
 
```yaml
type: custom:catgenie-card
prefix: catgenie      # matches entity names such as sensor.catgenie_cartridge_remaining
name: CatGenie A.I.
max_cartridge: 120    # defaults to the cartridge capacity sensor
confirm: true         # ask before starting or stopping
width: 420px          # optional maximum width, centered
height: 260px         # optional maximum illustration height
font_scale: 1         # optional text scale
compact: false        # hide the stats row
```
 
An `entities:` block can map individual entities by key (`state`, `progress`,
`error`, `cartridge`, `capacity`, `last`, `mode`, `online`, `start`, `stop`).
 
**Sizing.** With no `width` or `height`, the card fills its panel or grid cell
and the illustration scales to fit. With either set, the card shrinks to fit its
content. In sections dashboards the card registers a default grid size of 6 by 6
(minimum 3 by 3) so it can be resized in edit mode.
 
### Card limitations
 
* The illustration is stylized, based on photos of the real unit, and not a photographic match.
* The rake and bowl animation is a timed loop, not tied to the unit's real scoop, wash and dry phases.
* The cat is decorative and does not react to a real cat.
* The animation and gradients are heavier than a flat card and have not been tried on low-power tablets.
 
