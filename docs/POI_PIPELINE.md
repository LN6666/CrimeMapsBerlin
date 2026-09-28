# Fourteen-city POI pipeline

This pipeline builds a checked, local OpenStreetMap POI product for the 14
owner-selected German cities. It does not read police announcements, infer an
offence at a business, create a city publication, or change `web/public`.
Generated extracts, indexes and tiles remain under the Git-ignored
`.runtime/safety/poi-cities/` directory.

## Cities and inputs

Twelve Geofabrik extracts cover the 14 municipalities. Düsseldorf and Essen
share the Regierungsbezirk Düsseldorf extract; Leipzig and Dresden share the
Sachsen extract. Each retained input has the published Geofabrik MD5, a local
SHA-256, the PBF snapshot timestamp, retrieval metadata, ODbL identifier and
OpenStreetMap attribution.

| City | Geofabrik extract | Metric CRS |
| --- | --- | --- |
| Berlin | Berlin | EPSG:25833 |
| Hamburg | Hamburg | EPSG:25832 |
| Munich | Oberbayern | EPSG:25832 |
| Cologne | Regierungsbezirk Köln | EPSG:25832 |
| Frankfurt am Main | Hessen | EPSG:25832 |
| Düsseldorf | Regierungsbezirk Düsseldorf | EPSG:25832 |
| Stuttgart | Regierungsbezirk Stuttgart | EPSG:25832 |
| Leipzig | Sachsen | EPSG:25833 |
| Dortmund | Regierungsbezirk Arnsberg | EPSG:25832 |
| Bremen | Bremen | EPSG:25832 |
| Essen | Regierungsbezirk Düsseldorf | EPSG:25832 |
| Dresden | Sachsen | EPSG:25833 |
| Hannover | Niedersachsen | EPSG:25832 |
| Nuremberg | Mittelfranken | EPSG:25832 |

The builder scans the extract for an OSM administrative relation whose exact
city name, administrative level and metric area match the configured municipal
range. It fails if there is no unique plausible relation. This OSM relation is
a reproducible community-data boundary and is not presented as an official
cadastral boundary.

## Commands

From the repository root:

```sh
export PYTHONPATH="$PWD/src"

# Missing inputs are downloaded sequentially. Existing inputs are rehashed
# locally and reused. Add --refresh to compare against today's Geofabrik MD5.
uv run python scripts/safety/build_pois.py fetch --city all

# Select the municipal relation, extract and clip POIs, then create local tiles.
uv run python scripts/safety/build_pois.py build --city all

# Re-read every source manifest, index, search row and tile independently.
uv run python scripts/safety/build_pois.py validate --city all
```

`run` performs all three stages. `--city` also accepts one stable city slug.
Downloads are resumable and use a sidecar tied to the requested URL and MD5;
a changed remote checksum discards an incompatible partial download. A failed
download, hash check, build or validation leaves existing public map files
untouched.

## Geometry and browser contract

Every POI starts from an OSM node, closed way or multipolygon relation and
retains its stable OSM ID, source URL, name, aliases and actual
`location_geometry` in the local index. Both actual and display geometry are
clipped to the selected municipal relation.

- Small venues use a 50 metre circle computed in the city's metric CRS.
- A station with an OSM area uses that area. A station without a footprint is
  retained as a point with `geometry_mode=footprint_missing`.
- Area categories such as parks, parking, marketplaces and attractions retain
  an OSM footprint when present.
- Display tiles omit `location_geometry`, are split by POI category, and use
  the existing 0.04° × 0.025° browser transport grid. The grid is only for
  transport; metric geometry is never calculated in degrees.
- `search.json` contains only source-derived names, aliases, categories and
  centers. No police location or crime association is created here.

The independent validator recalculates input hashes, verifies the PBF timestamp
against its manifest, checks all retained geometry against the boundary,
measures every unclipped 50 metre circle, enforces the station area/point rule,
reconstructs tile membership from geometry bounds, compares every tile feature
with the display-only index, and checks category counts and colors. Any mismatch
writes a failed `validation.json` and returns a failing process status.

## Current local evidence

The checked 2026-09-29 local run passed all 14 cities: **202,597 POIs** and
**5,912 category tiles**. Its PBF files, source-derived POI indexes, tiles and
validation reports occupy about 2.7 GB under `.runtime/` and are not committed.
The three municipalities without a tagged airport-terminal POI inside their OSM
boundary naturally expose 12 rather than 13 populated categories.

Every city report remains `local_poi_only_unpublished` and records
`publication_ready=false`. A public city map still requires the separate
official police-source coverage, source-backed article review, current owner
inspection and approval, and versioned publication manifest.

Sources: [Geofabrik Germany extracts](https://download.geofabrik.de/europe/germany.html)
and [OpenStreetMap copyright and licence](https://www.openstreetmap.org/copyright).
