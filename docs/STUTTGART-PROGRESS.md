# Stuttgart current progress

Verified: 2026-09-30T16:45:49.523032+00:00. Counts describe local work, not published crimes.

| Stage | Current state |
|---|---|
| Selected source channel | 1,060/1,060 current full bodies; zero missing/error backlog |
| First-pass source verdict | All 1,060 supported; 1,718 scenes and 2,803 formal locations |
| Explicit time/details supplement | 41 scenes complete; 1,677 still missing required decisions |
| Explicit location POI supplement | 88 locations complete; 2,715 still missing required decisions |
| Deterministic geometry | 2,060/2,060 decisions; 1,750 resolved, 310 documented gaps |
| Map classification | 480/1,050 articles; 570 pending; 108 provisional announcement references |
| Browser candidate / approval / publication | Incomplete, unapproved, unpublished |

## Continue from the current checkpoint

Canonical source decisions are in the second repository's ignored `.runtime/cities/stuttgart/police.sqlite`, table `llm_review_decisions`; the older main intake SQLite is not the review store. `.runtime/review/stuttgart/integrated-461-480/` contains the latest twenty-article delta, complete 1,060-row restore files and checksums; the preceding ten-article integrated checkpoint remains historical evidence.

Main ignored `.runtime/safety/cities/stuttgart/semantic-completeness-audit-current.json` records remaining semantic gaps. Its inventory, current geometry/map decisions and ledgers, review pack, OSM index and U15 proof pass `CHECKSUMS.integrated-current.sha256`. Continue at article 481, source `6272197`. Backfill absent time/details/POI decisions in the earlier 450 and excluded-scope articles before declaring full semantic completion; do not automatically fill unknown dates or empty POI lists.

The first 460 map choices remain unchanged. The latest twenty full bodies supplied 26 scene time/detail and 62 location-POI judgments, retained aggregated and potentially overlapping theft accounts, and separated later treatment locations from original accidents. Unknown-cause fire is not declared arson, witness counts do not become crime counts, and a building-height reference is not a precise roadway collision point. Classification and source supplements are explicitly authored LLM decisions; serialization, source/hash/evidence validation and GIS calculations are deterministic.

## Native U15 geometry repair

The accepted local PBF supplies six U15 `light_rail` relations and 186 operational path ways. The importer preserves the explicit moving-line review; the native geometry tool now supports the original OSM mode, and the compiler accepts compatible subway/tram review without rewriting raw tags. All six complete relations remain in the municipal line display. The actual vehicle incident segment is unknown; Ruhbank is the later arrest, and no route/count centre is generated. All prior index objects and 2,059 other compiled geometry decisions are unchanged.

The second-repository importer passes 23 focused tests; the isolated committed main route/geometry patch passes 13 relevant tests. Actual staged/canonical source import, complete-line geometry validation and partial map compilation pass. Current restore/checksum files pass readback. No raw police body or generated city data enters Git.

Source decision digest: `ef0e02ce6cad3c99c3a4f9a5c97b80be29b4c56b9c37190e07ca76f5ae5b67fb`. Inventory: `c02f7ac3ae5559b54e2ec226f4a237623ad9c43a6473a049313e1302616e28a9`. OSM index: `0732b2a333ce27a5fe5aae55e8477a15df1ecbc5459c43ff325d543620afe5c8`. Geometry ledger: `c05c65a7fd69dd23f55e0517156303cb9bef0e62c4389656d76bd108d4f8a43c`. Map ledger: `7856270eb81080f385b90987958af025fc71c49cc8b9596d4bf07ac8c56a12b7`.

Preserve road ranges, arrest/discovery/background roles and unresolved geometry. Remaining semantics, final event/count compilation, browser inspection and owner approval of current digests are required before publication.
