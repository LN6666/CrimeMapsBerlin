# Nuremberg current progress

Last verified: 2026-09-30T14:44:38.479588+00:00. This file is the compact continuation entrypoint; historical source/GIS details remain in `HANDOFF.md`.

| Stage | Current state |
|---|---|
| Selected 2026 police-signed channel | 849/849 complete bodies; no fetch/parser backlog |
| Full-body LLM first pass | 849/849 read; 834 supported, 15 uncertain, zero pending/stale |
| Supported-inventory geometry | 1,561/1,561 explicit decisions; 918 checked geometries, 643 documented gaps, zero pending |
| Map-semantic draft | 140/408 supported mappable articles; 273 retained scenes, six eligible announcement count references, 268 pending |
| Relationship integrity | All 113 current source/hash/scene/evidence bindings pass; final map relations/counts uncompiled |
| Source-question audit | All 15 uncertain full bodies reread; conflicts preserved; no automatic date repair or tentative same-case merge |
| Final map / owner approval | Not compiled, not approved, not published |

## Resume

In `CrimeMapsDE-Cities-11-14`, restore the ignored `.runtime/review/nuremberg/checkpoint.json`, `map-draft-progress.current.json`, `map-decisions.draft.current.ndjson` and its two current parts. The next supported map source is `6241603`. Draft decisions bind each current source and source-review digest plus the current checked geometry ledger; draft-set digest is `1a3fa55360caafb845e48988207aa6b65cb8c30e321b22ca678732599741bb9d`. All 36 current checkpoint files pass SHA-256 readback.

Use unchanged, personally completed full-body source-semantic reviews for classification/primary-scene decisions; reread a complete body when a concrete ambiguity remains. The first 140 drafts required twenty such rereads. Every category, crime-report status and optional count choice is an explicit LLM decision. Source extraction, evidence/hash checks, original OSM geometry and duplicate guards remain deterministic.

The draft is not a formal map ledger. Fifteen uncertain source reviews still block formal compilation; owner inspection/approval still blocks publication. Six draft count references are announcement-level selections, not six independently proven crimes. Preserve every other reviewed scene and all unresolved locations; never generate district/area centres or use arrest/discovery/route/POI references as original offence points.

## Source questions

The ignored `source-questions.current.md` and `source-question-audit.current.json` record eleven date issues, two A6 municipality issues and two possibly related gate-location conflicts. The actual A6 corridor already crosses the municipal boundary; checking it again will not locate the crash. An explicit follow-up supports the 2026 date of one original malformed-year report without changing that original body/hash. The possibly matching scooter reports remain tentative and cannot silently merge counts.
