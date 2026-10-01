# Reviewed Hamburg production consumers

This branch integrates the previously verified Hamburg runtime consumers into
the shared production modules. The selected checkpoint contains 494 primary
announcements, 3,359 phases and 3,973 formal locations. Those totals are not
independent crime counts. No source interpretation is performed by the program.

## Inputs and boundaries

Use the current source SQLite, reviewed inventory, geometry ledger, map ledger,
explicit POI membership binding and reviewed display packet. All source bodies,
choices, attachments, native captures, generated products and packets remain
under ignored local runtime directories.

The display packet can add existing reviewed notes, historical comparisons,
attachment summaries and claim overlays. It cannot change phases, times,
coordinates, classifications or count selections. Each record binds the current
source, source review and map decision. The original parent review of a historical
comparison remains separately recorded; the displayed primary binding uses the
current review. Original auxiliary stages are preserved, including unknown dates.
Six Rissen relation choices likewise retain their original meaning while their
presentation is rebound to the current 6315815 review instead of its old hash.

The POI binding names the actual policy, individual native choices and captured
records with SHA-256. The validator checks their current bytes, each selected
membership, unique objects, municipal geometry, search and every type tile.
Multiple types on one object retain one announcement–object association and all
explicit scene evidence. An unnamed venue remains unnamed.

Native platform collections use the explicitly reviewed original node IDs for
station context. Public coordinate rounding cannot omit those associations or
add nearby platforms. Display-only junctions, platforms, carrier lines and road
references cannot supply count points, including through malformed primary flags.
The map manifest exports validated membership counts for all available types.
Legacy manifests without those counts keep usable POI controls instead of being
misrepresented as having zero native objects.

## Local candidate command

```sh
PYTHONPATH=src uv run python -m crimemapsberlin.reviewed_city_map \
  --city hamburg --db /local/police.sqlite \
  --inventory /local/reviewed-scene-inventory.json \
  --geometry-ledger /local/geometry-ledger-current.json \
  --map-ledger /local/map-ledger-current.json \
  --poi-root /local/reviewed-poi-product --catalog /local/catalog.json \
  --reviewed-poi-binding /local/poi-product-binding.json \
  --reviewed-display /local/reviewed-display.json \
  --publication-timezone Europe/Berlin --month-basis publication_month \
  --out .runtime/hamburg-production-candidate
```

The timezone option explicitly normalizes publication wall clocks. It rejects
ambiguous and nonexistent DST clocks; it never changes an incident date. The
publication month option preserves original event times and conflicts. Compared
with D13's mixed filter, 6265603 moves May→April, 6285648 May→June, and 6363087
September→October. Category, phase, location and count choices stay unchanged.

Generation signatures include producer code, current ledgers, POI contract,
boundary, reviewed display and selected time policy. Changed consumers cannot
silently reuse an older browser cache generation.

## Verification and remaining work

Production source, geometry, classification and both relation compilers reproduced
the current canonical ledgers exactly. Focused negative tests reject stale or
unauthorized display changes, unreviewed POI additions, altered tiles and reference
counting. The real production candidate retains 489 mapped announcements, 3,334
phases, 3,947 locations, 2,108 display references, 622 explicit GIS request gaps,
109,326 unique POIs, 3,596 POI tiles and 1,838 context associations; count points
remain zero. Unknown displayed locations total 1,839, a different denominator
from the GIS request gaps.

Archived D13 and the prior full owner ZIP remain preserved. This integration does
not finish the remaining historical/native evidence work, city acceptance, owner
approval or external publication. No other city's runtime inputs are modified.
