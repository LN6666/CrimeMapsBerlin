# Changelog

## Unreleased

- Add outbound POLIZEIKARTE Berlin and major German city links, without embedded scripts or automatic data imports.
- Display unresolved long/disconnected scene roads as orange dashed ranges, preserving locality scope and gaps; click or focus from a report card without changing hex counts or POI associations.
- Add standard OSM street, Berlin 2026 aerial imagery and local basemap choices; preserve selections/camera and stop failed raster sources.
- Improve station/genitive and scene context, district/Ortsteil ambiguity, generic place names and adjacent collision junctions; retain origin and evidence sentence indexes.
- Add regressions for moving-train dispatch, named venue/road collisions, fixed fire evidence, witness-only locations and scene-consistent locality scope.
- Prioritize incident scenes over escape/arrest/response places using deterministic clause roles; preserve additional scene candidates in the map.
- Resolve compact 2–4-road junctions and explicitly bounded incident sections, with selected section geometry shown in the browser.
- Add scene-priority regressions for fixed crime traces, injured-person discovery, time/person ranges, travel context and multi-scene announcements.
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
