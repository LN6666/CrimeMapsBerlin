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

## Git workflow

Use `codex/` feature branches and pull requests. Check Python tests, TypeScript/build and browser tests. Do not disable failing checks or erase Git history. Main's reviewer requirements remain in force; completing code and passing CI is distinct from an approved merge.

Version 0.1.0 establishes the new project identity and deterministic ingestion/display pipeline. Follow-up changes should update CHANGELOG and affected docs, with regression fixtures for parser/geometry changes.
