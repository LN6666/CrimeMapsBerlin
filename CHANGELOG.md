# Changelog

## Unreleased

- Replace 900-character exact-name matching with full narrative roles, German name variants and a prefix-factored matcher.
- Add local OSM neighbourhood/address indexes, named-place resolution and one-time scheduled index upgrades.
- Resolve near-connected street fragments by geographic extent; retain review for separated/wide/ambiguous locations.
- Distinguish address/place representatives in hexes and UI; restrict named-place associations to the matched object.
- Add frozen-source geocode comparison and regressions for omissions, false names, destinations and moving scenes.

## 0.1.0 — 2026-09-27

- Replace the former CiviFlux plugin tree with CrimeMapsBerlin; retain Git history.
- Add official police archive discovery, incremental SQLite checkpoints, revisions, backoff and local scheduling.
- Add local OSM extraction, conservative street matching, 1,100/275 m hexes and typed POI associations.
- Add month/viewport-based MapLibre loading with bounded caches and request cancellation.
- Add explicit source coverage, kbO original-map links, testing and maintainer documentation.
