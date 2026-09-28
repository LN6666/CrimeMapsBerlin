# Changelog

## Unreleased

- Treat the owner-selected POLIZEIKARTE rolling 365-day Munich snapshot as the upstream semantic and location basis, while retaining its independent-provider identity, original police links, precision and coordinates. Downstream checks verify completeness, municipality containment and geometry without repeating source-first interpretation or inventing missing points.
- Add source-, decision- and evidence-bound city geometry requests, a checked municipality OSM geometry index and explicit LLM geometry decisions for points, footprints, whole roads, intersections and administrative areas. The Düsseldorf pilot now covers every geometry request in its current supported review set; all results remain unpublished and require owner approval.
- Add a tracked, local-only 14-city POI pipeline with resumable Geofabrik acquisition, MD5 and SHA-256 verification, unique OSM municipal-boundary selection, metric 50 metre venue geometry, station footprint/point handling, category tiles and independent read-back validation. Generated extracts and city products remain ignored and unpublished.
- Add a local-only source review pack builder that reads one SQLite snapshot, rechecks every stored body hash, records incomplete channel coverage, batches raw originals for source-first LLM review and keeps its default output under the Git-ignored runtime directory. A verified `--base-pack` mode emits only new source IDs after checking any adjacent or explicit SHA-256 sidecar, every internal checksum and body hash, channel identity, safe ZIP paths and unchanged base records; the manifest binds the base digest and base/delta/combined counts.
- Move narrative meaning to source-first LLM review: remove the fixed scene extractor from the build, let rules only flag review, and use deterministic code solely to validate source hashes, verbatim evidence, OSM geometry and publication gates. Missing or stale scene decisions block publication.
- Preserve all reviewed locations from multi-location announcements as batched point, road, area or district scene geometry with explicit roles. Enforce at most one primary hex point per announcement and require scene-specific evidence for POI association.
- Stage Hamburg's official newsroom and checksum-verified OSM extract locally; report incomplete article fetches instead of dropping them.
- Preserve Hamburg article-derived district headings when its newsroom listing is rescanned, and repair cached headings erased by earlier scans.
- Recognize source-backed ATM damage, a police officer dragged by a vehicle, and deliberate vehicle fire in candidate headline categories; keep aggregate reports unclassified.
- Add a city-specific metric CRS path and a conservative singular `Tatort:` heading rule for Hamburg; same-source Berlin v4→v5 audit found no mapped-point changes and six aggregate-bulletin method corrections.
- Stage Hamburg candidates locally with a city-specific review queue and publication gate. Plural official scene headings, generic multi-location headings and moving road events now stay unlocated unless the source supplies one fixed scene; reviews remain bound to current source and extraction hashes. The manual Hamburg browser route accepts only a Hamburg manifest, while the public city selector stays disabled.
- Refine Hamburg review findings: accept a singular official `Ort:` as scene evidence, preserve `St.` place names when splitting narratives, prioritize a single official scene, retain supported junction anchors, recover explicit robbery and weapons-offence wording, and keep match-operation summaries, explicitly unlocated scenes, fictional crime readings and unnamed venues on long roads from receiving misleading crime points. Traffic reports remain in the traffic category while explicit accident-flight wording keeps its alleged-offence flag.
- Preserve Presseportal list items and preformatted description blocks in Hamburg and Frankfurt article bodies. A per-row parser version forces old cached bodies through the new parser before they can enter a candidate batch, while contact and originator blocks remain excluded.
- Persist Hamburg year-archive coverage only after a full newsroom scan crosses the requested year boundary, a repeated head page is stable, and no body, parser or source error remains; later unseen head records invalidate that proof until another full scan.
- Allow checked regional Geofabrik inputs to build local Cologne and Frankfurt OSM indexes; both cities remain unpublished and require municipality, archive, review and owner gates.
- Add local source intake adapters for Munich, Cologne and Frankfurt am Main, with a shared first-group city contract and publication permissions. Place the remaining nine cities in their correctly named 5/5/4 group repositories; every city now has a bounded official-source entry or a fail-closed offline boundary. Keep unapproved data out of Git.
- Add the 14-city selection registry in the requested three groups of 5/5/4; only Berlin is navigable until another map is verified.
- Block refreshed publications on source backlog, missing reports, location regressions, incomplete per-article AI review or absent owner approval of the current review packet; retain the last good snapshot.
- Retire six legacy PRs/branches and 205 old build artifacts; document the owner's one-time administrator approval for the default-branch migration.
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
