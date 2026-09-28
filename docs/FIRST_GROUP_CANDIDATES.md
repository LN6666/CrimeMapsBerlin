# First-group city candidate contract

The first repository groups Berlin, Hamburg, Cologne, Frankfurt am Main and
Munich. `city_contract.py` is the shared path, source-schema and metre CRS
registry. Berlin uses EPSG:25833; the other four entries use EPSG:25832.
Source SQLite checkpoints live under `.runtime/safety/`, OSM input/indexes
under `data/raw/safety/`, and public snapshots under `web/public/safety/`.
Non-Berlin paths add `cities/<city>/`. These three trees are ignored by Git.

`city_candidates.py` stages only local `review-candidates.json` and
`candidate-audit.json`; it does not write a public map. Its source reader
normalizes the collector-style Hamburg/Frankfurt rows and the native Cologne
rows to the same geocoding input. For Cologne, the native Drupal node ID is
the retained article ID. Only reports with an explicit Cologne city-scope
lead enter that city's extraction batch. Reports labelled outside or needing
scope review remain in SQLite and are counted separately in the audit. For
Frankfurt, `Frankfurt (ots)` and the issuing authority are ignored as city
evidence; only explicit municipality wording creates a local candidate.
These are still review leads, not verified incident scenes or boundary checks.

Munich uses the owner-selected POLIZEIKARTE rolling 365-day dataset. Its
collector partitions the capped city page by all ten exclusive categories,
checks every paginated list ID against the category-wide map payload and
requires the category sum to equal the displayed city total. Candidate rows
retain POLIZEIKARTE's category, summary, precision, upstream coordinate,
detail URL and original police URL. `city_candidates.py --city munich` writes
the hash-checked local candidate snapshot. `munich_map.py` combines that
snapshot with the independently validated Munich POI product, checks every
upstream coordinate against the OSM municipality boundary, and writes a
browser-shaped 13-month map candidate under `.runtime/`. It retains all rows
but removes outside-city and nonpoint representatives from hex counts. It does
not infer POI offence associations. The browser recognizes `?city=munich` for
local inspection, but the normal city menu retains its in-progress label and no
candidate files are committed. `build.py --city munich` still stops before publication.
Cologne and Frankfurt can be staged once their checked OSM indexes are
available locally with Geofabrik source provenance. `fetch_osm.py` uses the
Regierungsbezirk Köln extract for Cologne and the Hessen extract for Frankfurt;
the source-scope and locality checks must still exclude the rest of those regional
files. `build.py` always stops before publication for these two cities. The existing Berlin/Hamburg publication gate still requires
current source-backed reviews and owner approval.

The candidate contract never starts a source or OSM download itself. Munich's
source collector is a separate explicit command; POI integration and owner
inspection remain separate gates. The local Munich candidate has completed POI
display integration but remains unapproved and unpublished. The Cologne native archive and
the publisher newsroom currently show different 2026 totals; these figures
must be compared article by article before any completeness claim.
