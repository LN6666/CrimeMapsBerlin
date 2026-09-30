# Stuttgart current progress

Verified: 2026-09-30T17:55:33.641538+00:00. Counts describe local work, not published crimes.

| Stage | Current state |
|---|---|
| Selected source channel | 1,060/1,060 current full bodies; zero missing/error backlog |
| First-pass source verdict | All 1,060 supported; 1,721 scenes and 2,810 formal locations |
| Explicit time/details supplement | 184 scenes complete; 1,537 still missing required decisions |
| Explicit location POI supplement | 351 locations complete; 2,459 still missing required decisions |
| Deterministic geometry | 2,062/2,062 decisions; 1,755 display geometries, 307 documented gaps |
| Map classification | 560/1,050 articles; 490 pending; 116 provisional announcement references |
| Browser candidate / approval / publication | Incomplete, unapproved, unpublished |

## Continue from the current checkpoint

Canonical source decisions are in the second repository's ignored `.runtime/cities/stuttgart/police.sqlite`, table `llm_review_decisions`. The older main intake SQLite is not this review store. Latest `.runtime/review/stuttgart/integrated-541-560/` contains twenty explicit source/map/POI decisions, a recovered operational geometry delta, complete 1,060-row restore files and checksums. The preceding `integrated-521-540/` retains another twenty-article delta and the U12 geometry corrections. Older missing-person/search-closure and strict single-link referral decisions remain preserved in their earlier checkpoints.

Main ignored `.runtime/safety/cities/stuttgart/semantic-completeness-audit-current.json` records remaining gaps. Current inventory, geometry/map decisions and ledgers, source review pack, OSM index, U15/U12/B27 proofs and B27 raw source extract pass all 12 `CHECKSUMS.integrated-current.sha256` checks; each new source checkpoint passes 16 checksums. Continue at article 561, source `6284021`. Backfill absent time/details/POI decisions in the earlier 450 and excluded-scope articles before declaring full completion; never automatically fill unknown dates or empty POI lists.

The latest forty complete bodies add 87 scene time/detail and 145 location-POI judgments. Two omitted blood-sampling locations and one traffic-impact range are recovered. The U12 hand injury is corrected to boarding/alighting at Hauptbahnhof, with the platform and door still unknown; a possible shard threat in a moving vehicle remains an uncertain event on an unknown U12 segment. Later station discovery, police action, arrest and medical transfer are kept separate. Four source announcements contain date/weekday conflicts that remain unnormalized; a stated June theft interval incompatible with the May escape is not silently changed to May. Six-home and three-vehicle announcements retain all distinct places and time windows. Parking/discovery spots, later arrests, unnamed parking lots and a roadside building-height reference do not become precise offence points. Prior 520 map classifications are unchanged.

## Native geometry and verification

U12 uses two complete original route relations, 1214006 and 1214007, with 199 operational path ways. The PBF's raw `light_rail` mode/ref tags are preserved. A whole-line display is a context range for unknown vehicle position, with no route-centre count. All previous index objects are unchanged. Of the two revised U12 requests, the unknown moving-vehicle segment now has a complete route range and the static Hauptbahnhof boarding injury remains unresolved. The recovered Alexanderstraße operation request uses the same previously checked 18 road ways; actual traffic-impact boundaries and duration remain unknown.

Earlier U15 proof retains six complete source relations and 186 operational path ways. B27 proof retains 448 exact-ref operational ways, excluding B27a and two proposed ways. Those repairs are unchanged; broad lines and road ranges are not exact incident coordinates or whole-road closure claims.

No executable code changed in this forty-source update. Existing 23 importer and 13 focused native-route test results remain applicable. Staged/canonical source import, source/hash/verbatim-evidence validation, U12 index readback and exact route relation IDs, preservation of all old index objects, three explicit GIS choices, map compilation and the checkpoint checksums passed. Generated city data and raw report bodies remain ignored and unpublished.

Source decision digest: `e160e99f1ad6544ec4d13fb6e7a288fc5222bcdac8dce8aa2d972f61edbb5acd`. Inventory: `8b7dfe3aa29aa6b5a50d4811a19f9833e6b1fab28a286554a8c9619c3c22b154`. OSM index: `1229499aad8ae80fed520926041f080a8d23a9e8ad28e11f9f6b2c1f67d7579c`. Geometry ledger: `9e8e3fe53d8f2efa87de0d17afc0913e99ce415e741a58fe05c18dd1a5429a3a`. Map ledger: `d27e506ff0d1f4b227478cd12577b399e20b6c457bb58d101a2c093729adab02`.

Preserve road ranges, arrest/discovery/background roles and unresolved geometry. Remaining semantics, final event/count compilation, browser inspection and owner approval of current digests are required before publication.
