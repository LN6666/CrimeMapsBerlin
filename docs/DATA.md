# Data provenance and interpretation

Primary report source: [Polizei Berlin current announcements](https://www.berlin.de/polizei/polizeimeldungen/), [2026 archive](https://www.berlin.de/polizei/polizeimeldungen/archiv/2026/). Archive list pages provide publication timestamp, title, district and article link. The adapter fetches the original incident narrative and excludes navigation and police headquarters contact details. No reliance on the intermediary site's last-50 RSS limit remains.

Keep original report bodies in local ignored SQLite only. The public code repository includes algorithms and synthetic fixtures, not a republished full-text police database. Public accessibility is not asserted to be a blanket redistribution licence. Derived publication contains short titles, IDs, classifications and original links; a deployer must check applicable reuse terms before wider redistribution.

Geometry source: [Geofabrik Berlin](https://download.geofabrik.de/europe/germany/berlin.html), OpenStreetMap under ODbL. Store download timestamp, source URL and checksum. The extract can include areas outside municipal Berlin; POIs outside the administrative boundary should not be treated as an official Berlin inventory. Basemap display and source indexing follow the supplied extract extent.

Classification is headline keyword based with an explicit unclassified bucket. POI mentions are extracted from original narrative using German patterns. Both can miss synonyms or misread context; these fields are reproducible candidate annotations, not validated event taxonomy labels.

Location matching uses exact normalized street names from local OSM. A single short road gives an approximate midpoint; a unique intersecting pair gives an approximate junction. Long/disconnected roads or multiple unrelated locations go to review. No house-number lookup, street-view inference, external paid geocoder or LLM. The initial 900 narrative characters are considered; a mentioned road can still be a chase/destination rather than the original incident. That is why street matches remain candidates.

POI color denotes type. Opacity reflects the count of reports with nearby matching type; it does not score individuals, predict offending, estimate personal danger, or establish a named business caused an offence. Public police-designated kbO areas are a separate source layer. Official kbO map images are linked until verified vectors can be supplied.

Europe source catalogue: `data/safety/europe_sources.json`, with material type distinguishing designated areas, observed hotspots, and general prevention advice. General advice about pickpocketing near stations does not designate every Berlin station a crime hotspot. Check the per-country coverage ledger rather than assuming all Europe is finished.
