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

Munich's separately supplied daily documents have unverified source
provenance, and the Bavarian police site's robots rules currently disallow
automated crawling. `city_candidates.py --city munich` and
`build.py --city munich` fail before touching any source or public files.
Cologne and Frankfurt can be staged once their checked OSM indexes are
available locally with Geofabrik source provenance, but `build.py` always stops before publication for these
two cities. The existing Berlin/Hamburg publication gate still requires
current source-backed reviews and owner approval.

No source downloads or OSM extracts for Cologne, Frankfurt or Munich are
initiated by this candidate contract. Coverage remains incomplete until the
native/partner archive cross-check, city boundary validation, per-announcement
review and owner's inspection have been done. The Cologne native archive and
the publisher newsroom currently show different 2026 totals; these figures
must be compared article by article before any completeness claim.
