# Architecture

The pipeline is a set of independently callable modules, with SQLite as durable acquisition state and immutable static JSON generations as the browser contract.

```
Polizei Berlin archive → collector → SQLite reports + revision hashes
OSM extract → checksum + osmium extraction → local street index / POI geometry
SQLite + street index → geocode / keyword rules → events + review queue
Events + POIs → metric hexagons / associations → monthly JSON + spatial tiles
Versioned files → atomic manifest swap → MapLibre browser
```

`collector.py` owns transport, canonical police article IDs, HTTP validators, retry scheduling and database checkpoints. `feed.py` contains official article-body/keyword extraction. `location_text.py` owns German name variants, prefix-factored matching and narrative roles. `geocode.py` resolves those mentions against street, place, locality and address indexes, with explicit review outcomes. `spatial.py` owns EPSG:25833 geometry, hexes, 50 m circles and typed candidate associations. `tiles.py` owns display partitioning. `build.py` composes modules into a static snapshot. `update.py` orchestrates jobs without importing browser concerns.

## Contracts

Reports retain ID, source URL, publication date, body hash and revision. Derived events retain `time_basis=publication_month`, optional coordinates, location precision (`point`, `street`, `place`, `address`, `district`, `unknown`), rule version, method, matched aliases/sentence indexes, object IDs and optional scope/extent. Police event occurrence dates are not inferred from relative wording. An announcement may describe multiple incidents; counts are report counts.

The verified PBF extraction also produces local-only neighbourhood boundaries and address lookup rows. Real POI location geometry is kept separate from display circles; it is removed from published tiles to avoid duplicating heavy geometry. The browser never downloads the full address/locality index. `audit_geocodes.py` compares frozen previous events with current rules on identical article hashes, records gained/lost mappings and large moves, and refuses changed sources. These mapping counts measure coverage, not accuracy.

Publication v2: `manifest.json` references a unique generation directory. Its month index contains counts, with detailed reports, hexes and associations in one file per month. Roads and POIs use fixed geographic tiles (0.04° × 0.025°), for transport only; metric calculations never use degree distances. Files are written before the manifest is atomically replaced. Readers can finish fetching the previous generation. The database is read inside one transaction so counts and records are consistent even while the crawler runs.

## Browser budget controls

- Overview does not request POI geometry. Detailed geometry is loaded at zoom ≥ 12.5. POI tiles are also split by category so unchecked categories are not downloaded.
- At most 64 requested viewport tile coordinates, four simultaneous requests; 80-tile LRU and three-month LRU.
- Cancel old requests when moving or changing month; reject stale results before updating sources.
- MapLibre batched GeoJSON/WebGL layers, no individual DOM marker for each POI.
- Search index is fetched only on first search, not first load. Inputs are debounced.
- Small circles use 32 segments; maximum chord error is about 0.24 m at radius 50 m.
- Overview roads are restricted to major classes and batched into four multiline features, simplified at approximately 10 m. Detailed road geometry is simplified for display only. Published coordinates are rounded to six decimal places (approximately 0.1 m); calculation inputs retain full precision.
- `basemaps.ts` owns display-only street/aerial/local sources. One active raster source, viewport tile requests and browser HTTP caching; switching does not recreate the map, refetch monthly events or reset selections. Errors stop the failed source and show local roads. Basemap imagery is never used as a geocode or event-time oracle.

These are implemented resource bounds, not a blanket frame-rate guarantee on all devices. Browser tests check request behavior and stale/month state; actual devices and expanded datasets still need measurement.

## Extension rules

New sources implement an adapter returning canonical IDs and provenance. Do not place scraping logic in UI code. Add new categories in the source registry and deterministic rules; keep uncertainty visible. A later geocoder can replace the gazetteer behind the same event contract. Machine learning is optional and must justify improved measured quality over the deterministic baseline.
