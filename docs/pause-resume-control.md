# Pause and resume cleaning

Normal-cycle Pause and Resume were owner-verified. Fault resume and cartridge allowance effects are not proven. These are behavior capabilities, not a statement about any host's deployment.

The official app builds `POST device/management/{id}/operation` for both commands. Pause (`suspendClean`) sends `{"state": 2}`, the outbound `SUSPENDED` value. Resume (`resumeClean`) sends `{"state": 3}`, the outbound `RESUMED` value. The pinned `catgenie==0.1.6` writer already posts that path. `start_cleaning` sends state 1. `stop_cleaning` sends state 0. These buttons reuse that writer once with those literal bodies. They do not replace the package, read stored login material, or call the start or stop methods.

Pause and Resume are enabled by default for a new registration. `entity_registry_enabled_default` is true only then. Home Assistant applies that default only when the entity is first added to the entity registry. This integration does not read or write the registry, so an existing enabled or disabled choice is left alone. A previously disabled entry needs an explicit Home Assistant enable. They are not diagnostic sensors: pressing one sends a command. They are not given a config category, because they are not settings.

Neither button runs during setup, polling, or refresh. Neither sends start or stop. Each button does not recover a water-fill fault. Each button does not restore cartridge allowance. Each button is not abort and is not a special cycle. A reported integer is not a command guard. Outbound state 2 is not a claim about what a reported 2 means, and outbound state 3 is not a claim about what a reported 3 means. Availability requires an explicit connected `reportedStatus`. A missing status, a disconnected report, or the integer `status` field does not make either button available.

A refused or failed press does not change coordinator data and is not retried by these buttons. After the writer returns, the existing command helper refreshes once. That refresh is not proof the unit accepted state 2 or state 3. The pinned writer may repeat the same POST once after an HTTP 401 token refresh. These buttons add no retry of their own.

Normal-cycle firmware acceptance was owner-verified. Fault resume during a water-fill fault is not proven. Offline tests do not establish that acceptance.
