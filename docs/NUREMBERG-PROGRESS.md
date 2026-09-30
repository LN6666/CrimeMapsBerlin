# Nuremberg current progress

Last verified: 2026-09-30T15:43:09.826997+00:00. This is the compact continuation entrypoint; historical source/GIS details remain in `HANDOFF.md`.

Latest targeted source check: 2026-09-30T18:49:42.150806+00:00 (October 1 in Japan). All fifteen question articles were fetched again from the selected police-signed channel after verifying robots.txt, with at least one second between requests. All fifteen body hashes are unchanged. This checks existing questions only; it does not refresh the archive head or certify later announcements. Canonical source and semantic decisions are unchanged. Resume Nuremberg's remaining source questions, relation/count treatment and browser candidate before switching this chat back to Stuttgart; Stuttgart's current work is saved locally.

| Stage | Current state |
|---|---|
| Selected 2026 police-signed channel | 849/849 complete bodies; zero fetch/parser backlog |
| Full-body LLM first pass | 849/849 read; 834 supported, 15 uncertain, zero pending/stale |
| Supported-inventory geometry | 1,561/1,561 explicit decisions; 918 checked geometries, 643 documented gaps, zero pending |
| Map-semantic draft | 398/398 current in-city/mixed articles; 729 retained scenes, 18 eligible announcement count references, zero pending |
| Additional classified drafts | 10 scope-uncertain articles preserved separately; all original 408 classifications complete |
| Relationship integrity | 113 current source/hash/scene/evidence bindings pass; final event-count compilation pending |
| Source-question audit | All 15 uncertain full bodies reread; conflicts preserved |
| Final map / owner approval | Not compiled, not approved, not published |

## Completed draft and next work

In `CrimeMapsDE-Cities-11-14`, restore the ignored `.runtime/review/nuremberg/checkpoint.json`, `map-draft-progress.current.json`, `map-decisions.draft.current.ndjson` and its five current parts. There is no unread supported map source. Ten additional classifications are in `map-decisions.scope-uncertain.current.ndjson`; their explicit municipality reassessments and old/new hashes are in `scope-correction.current.json`. A local history snapshot preserves the prior 408-article checkpoint.

Each current draft binds its original source and source-review digest. The current supported inventory digest is `ac43731e184250e7107d59efb30e0df436cc51c05820d6fa7dfa1bffff3c4ebe`, source decision-set digest `27187ea8d31369611d620dd10dfa8db57a5d7f1592c1ad411592f46f14506c26`, geometry-ledger digest `807019db364571c4d79e1f929d8a93a05bb7a1820f483e9024aa344bfa000156`, and map-draft digest `58464c4e7cb1513886de91ca44773140aba6f665d6c578870ab82787b5df8a33`. All 45 current files pass SHA-256 readback; all 849 stored source decisions pass validation with zero stale entries.

Every category, crime-report status and optional count choice is an explicit LLM decision. Ninety unique bodies were reread for specific ambiguities while reusing unchanged, personally completed full-body source reviews. No fixed narrative classifier was used. The ten scope corrections change no source body, scene, formal location, geometry request or native geometry; all 1,561 requests remain byte-identical, so their calculations were reused.

## Remaining gates

Fifteen uncertain source reviews still block formal map compilation. Their issues are eleven date conflicts, two A6 municipality gaps and two potentially matching scooter reports with different gate locations. Exact evidence and next questions remain in `source-questions.current.md` and `source-question-audit.current.json`. The A6 corridor already crosses the municipal boundary; repeating that geometry check cannot locate the actual crash. The scooter relation remains tentative and cannot silently merge counts or select a gate.

The targeted recheck is saved in the third repository under `.runtime/review/nuremberg/question-source-recheck-20261001/audit.json`, alongside the fifteen fetched bodies. All are local ignored files. The recheck supplies no new evidence to resolve the existing questions, so none is promoted to supported.

Finalize event relations/counts after the source gate is resolved, build the browser candidate, and obtain owner inspection/approval of its current digests before publication. Eighteen draft count references are announcement-level selections, not eighteen independently proven crimes. Road/area geometries and unresolved locations remain preserved; no district centres, arrest/discovery/route points or unverified POI offence associations may substitute for original offence points.
