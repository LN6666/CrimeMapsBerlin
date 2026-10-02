> Current working agreements (2026-10-03): the owner selected 14 independent city repositories and source-backed review of every announcement. Routine owner approval has standing authorization after required checks pass. See [coordination](PUBLIC-LAUNCH-COORDINATION.md), [current local data workflow](CITY-MIGRATION.md), and [old PR recovery](PR9-RECOVERY.md). The historical objectives and automated-classification/per-batch permission instructions below are superseded. Repository visibility and green code CI do not establish map publication or complete coverage.

# Handoff and owner decisions

## Current objective

CrimeMapsBerlin replaces CiviFlux. The owner authorized removal of the former plugin code locally and on GitHub, and renaming the repository. Git history is preserved. The old traffic disruption, digital twin, ontology/PPR and Qwen development plans are superseded for this product.

## Requirements retained from conversation

1. Public GitHub repository in the owner's LN6666 account; version control, usable documentation and cross-account handoff.
2. Software engineering: modular boundaries, small explicit contracts, reproducible source processing, focused tests, honest CI and maintainable code.
3. Berlin map matching the observable England/Wales reference behavior: year/month, two hex scales, zoom/click stats. Do not claim unknown reference internals are identical.
4. Europe-wide police source research for relevant POI categories, category colors, 50 m circles for small places, actual station areas, nearby mention darkening and Berlin kbO.
5. Fetch missing announcements directly from police, not just an intermediary feed.
6. Browser performance: staged/month/viewport loading, bounded caches, no thousands of DOM markers.
7. Continuous refresh via deterministic crawlers/structured extraction. No recurring LLM dependence. No paid APIs or local Qwen deployment.
8. Actual incident-scene location takes priority over boarding, travel, escape, arrest and later response locations. Preserve additional scene candidates and count an announcement only once; never silently call it one offence.

Nearby darkening defaults to **same mentioned type**, pending any owner change. The question was offered but no answer arrived; this avoids unrelated nearby businesses receiving identical highlighting.

## First steps for another maintainer/account

Read README → ARCHITECTURE → UPDATES → DATA. Run `git status`, check current branch and the migration PR, then run the focused test commands in README. Local ignored data is not available on another computer: run the documented download/import commands. A new GitHub account needs repository permissions for push, but no API subscription is needed for local development.

Source registry coverage and kbO vector completion remain open tasks. Geocoding is deliberately conservative and needs audited improvements before a claim of comprehensive incident mapping. The runtime build audit contains the current counts; do not freeze a partially imported count as permanent product status.

Geocoding v2 addresses the owner's observed omissions: full narrative scanning, German variants/abbreviations, parks/stations/venues, OSM locality clipping, explicit addresses and nearby fragment clustering. Every rebuild reruns these rules over all stored reports. Review reasons distinguish non-incident notices, district-only information, spelling suggestions, unscoped/multiple locations, disconnected/wide geometries and locality conflicts. There is no completed human correction interface; do not claim these remaining queues resolve themselves. See DATA for the actual heuristics and `scripts/safety/audit_geocodes.py` for a same-source comparison.

Rule version 3 adds incident-scene priority, action-linked temporal clauses, compact 2–4-road junctions, and explicitly bounded street sections. Public scene-selection/additional-candidate fields and selected section lines are implemented; missing or moving scenes still need review. The frozen v2→v3 comparison lives locally in `.runtime/safety/scene-priority/`; regression fixtures remain synthetic. DATA records actual counts and tolerances. Continue to distinguish crime traces on fixed objects from merely finding an injured person.

Rule version 4 adds station/genitive context, ordinary-word disambiguation, adjacent junction anchors, explicit origin/destination roles, fixed-fire evidence and scene-consistent locality context. The frozen v3→v4 comparison in `.runtime/safety/context-v4/` maps 746/1,098 announcements (66 gained, 14 withdrawn; 352 unresolved), using unchanged bodies/indexes. This is mapping coverage, not accuracy. All runtime evidence stays local and is unavailable on a fresh computer; synthetic regression fixtures remain in Git.

The owner also requested a familiar street/imagery map. `web/src/safety/basemaps.ts` owns standard OSM tiles, Berlin government 2026 aerial WMS and local simplified roads. Basemap switching preserves analytical state and cancels inactive sources; failed external tiles stop and fall back visibly. No API key/subscription is required. The aerial layer is not satellite/live imagery. See DATA for sources, licence, flight date and display-only use.

The owner requested visible road ranges for reports withheld because their matched road is long or disconnected. `candidate_road_geometry` is an additive display field, while geocoding remains v4. The orange dashed candidate-road layer and card focus action use the existing monthly loading/filtering path. Do not count these ranges as point-located reports, assign a midpoint to a hex, or darken every nearby POI along an uncertain road. Other review reasons (such as conflicting locality, travel origin or spelling suggestions) do not automatically receive road geometry. Automated review labels are diagnostic states: a `district_only` label can still hide an unrecognised named building/station in the source. Improving source context remains a separate task.

## External maps and supplementation

The owner requested links to POLIZEIKARTE and asked whether it could supplement missing records. The page now includes a direct Berlin link and a German-city directory. External maps remain references: no automatic coordinate import or copied third-party summaries. Missing source records, missed location extraction and genuinely vague scenes are different review tasks. Follow original police article IDs/URLs when supplementing; the external feed's 50-entry limit cannot cover the whole archive. See DATA for terms and the boundary between references and authoritative source ingestion.

## Git workflow

Use `codex/` feature branches and pull requests. Check Python tests, TypeScript/build and browser tests. Do not disable failing checks or erase Git history. Main's reviewer requirements remain in force; completing code and passing CI is distinct from an approved merge.

Default-branch migration is tracked in [PR #8](https://github.com/LN6666/CrimeMapsBerlin/pull/8); verify its merged state and the `main` tree rather than equating development-branch checks with publication. On 2026-09-28 (Asia/Tokyo), the owner explicitly authorized one administrator merge of PR #8 after its checks pass, bypassing the outstanding human-review requirement for this PR only while preserving branch protection. This is not authorization to bypass reviews on future changes. Old PRs #2–#7 are closed, their six remote feature branches are removed, and all 205 retired Actions artifacts are deleted. Repository metadata describes CrimeMapsBerlin. Commit history and Actions run logs remain intact; retired branch tips are also archived locally under `refs/archive/retired-civiflux/`.

Version 0.1.0 establishes the new project identity and deterministic ingestion/display pipeline. Follow-up changes should update CHANGELOG and affected docs, with regression fixtures for parser/geometry changes.
