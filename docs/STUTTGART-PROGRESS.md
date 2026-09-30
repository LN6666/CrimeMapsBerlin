# Stuttgart current progress

Verified: 2026-09-30T16:15:28.431875+00:00. Counts describe local work, not published crimes.

| Stage | Current state |
|---|---|
| Selected source channel | 1,060/1,060 current full bodies; zero missing/error backlog |
| First-pass source verdict | All 1,060 supported; 1,718 scenes and 2,803 formal locations |
| Explicit time/details supplement | 15 scenes complete; 1,703 scenes still missing required decisions |
| Explicit location POI supplement | 26 locations complete; 2,777 still missing required decisions |
| Deterministic geometry | 2,060/2,060 decisions; 1,749 resolved, 311 documented gaps |
| Map classification | 460/1,050 articles; 590 pending; 106 provisional announcement count references |
| Browser candidate / approval / publication | Incomplete, unapproved, unpublished |

## Continue without repeating completed work

Canonical source decisions are in the second repository's ignored `.runtime/cities/stuttgart/police.sqlite`, table `llm_review_decisions`; the older main-repository intake SQLite is not the current review store. The second repository's `.runtime/review/stuttgart/integrated-451-460/` includes the validated ten-article delta, complete current 1,060-row restore files and checksums.

Main-repository ignored `.runtime/safety/cities/stuttgart/semantic-completeness-audit-current.json` records required semantic gaps. Its current inventory, geometry decisions/ledger, map decisions/ledger and review pack are covered by `CHECKSUMS.integrated-current.sha256`. Continue integrated full-body semantic and map review at article 461, source `6268305`; later backfill missing time/details/POI decisions in the earlier 450 articles and excluded-scope announcements. Do not automatically supply empty POI judgments or unknown dates.

All 2,058 earlier native geometries and the first 450 map classifications are preserved. Their hashes were rebound only after verifying unchanged mathematical/source inputs. Two new May-Day planned/background scopes have explicit GIS decisions; planning is not a completed crime. A source weekday/date conflict remains unnormalized. The new importer preserves optional explicit time, details and POI decisions; 19 focused tests and the actual staged/canonical imports passed.

Source decision digest: `542671f47f584a372409e5b74e3e4260b16b420977378319f9a9a32401a83388`. Inventory: `9c26e78c436ef2c46b453edcf0c7c33aafcba3c59c0f8f641cef70df2fa48316`. Geometry ledger: `ee64c0b3fc2a228dfd96a44184d7ddb465b0988cd7a377c55f91a3d4f8d29100`. Map ledger: `aad1f3ea712754e749d3209fc488260e7432d28f2c4466b0a457b78c013852a9`.

Preserve roads, background/arrest/discovery roles and unresolved geometry without creating district-centre crime points. First-pass supported verdicts do not prove full current semantic completion. Final counting, browser checks and the owner's approval of current digests remain necessary.
