# Architecture

The pipeline is a set of independently callable modules, with SQLite as durable acquisition state and immutable static JSON generations as the browser contract.

```
Polizei Berlin archive → collector → SQLite reports + revision hashes
OSM extract → checksum + osmium extraction → local street index / POI geometry
SQLite + street index → geocode / keyword rules → events + review queue
Events + POIs → metric hexagons / associations → monthly JSON + spatial tiles
Versioned files → atomic manifest swap → MapLibre browser
```

`collector.py` owns transport, canonical police article IDs, HTTP validators, retry scheduling and database checkpoints. `feed.py` contains official article-body/keyword extraction. `geocode.py` owns deterministic name matching and conservative abstention. `spatial.py` owns EPSG:25833 geometry, hexes, 50 m circles and typed candidate associations. `tiles.py` owns display partitioning. `build.py` composes modules into a static snapshot. `update.py` orchestrates jobs without importing browser concerns.

## Contracts

Reports retain ID, source URL, publication date, body hash and revision. Derived events retain `time_basis=publication_month`, optional coordinates, location precision, method and candidate names. Police event occurrence dates are not inferred from relative wording. An announcement may describe multiple incidents; counts are report counts.

Publication v2: `manifest.json` references a unique generation directory. Its month index contains counts, with detailed reports, hexes and associations in one file per month. Roads and POIs use fixed geographic tiles (0.04° × 0.025°), for transport only; metric calculations never use degree distances. Files are written before the manifest is atomically replaced. Readers can finish fetching the previous generation. The database is read inside one transaction so counts and records are consistent even while the crawler runs.

## Browser budget controls

- Overview does not request POI geometry. Detailed geometry is loaded at zoom ≥ 12.5. POI tiles are also split by category so unchecked categories are not downloaded.
- At most 64 requested viewport tile coordinates, four simultaneous requests; 80-tile LRU and three-month LRU.
- Cancel old requests when moving or changing month; reject stale results before updating sources.
- MapLibre batched GeoJSON/WebGL layers, no individual DOM marker for each POI.
- Search index is fetched only on first search, not first load. Inputs are debounced.
- Small circles use 32 segments; maximum chord error is about 0.24 m at radius 50 m.
- Overview roads are restricted to major classes. Detailed road geometry is simplified for display only.

These are implemented resource bounds, not a blanket frame-rate guarantee on all devices. Browser tests check request behavior and stale/month state; actual devices and expanded datasets still need measurement.

## Extension rules

New sources implement an adapter returning canonical IDs and provenance. Do not place scraping logic in UI code. Add new categories in the source registry and deterministic rules; keep uncertainty visible. A later geocoder can replace the gazetteer behind the same event contract. Machine learning is optional and must justify improved measured quality over the deterministic baseline.
