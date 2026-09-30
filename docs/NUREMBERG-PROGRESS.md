# Nuremberg current progress

Verified: 2026-09-30T20:24:43.558739+00:00. Nuremberg's current local candidate is complete and awaiting the owner's separate inspection/approval. This supersedes the earlier 834-supported / 15-uncertain draft checkpoint.

| Stage | Current checkpoint |
|---|---|
| Selected police-signed 2026 channel | 849/849 full bodies; no missing/error rows |
| Personal full-body LLM review | 849 supported; zero pending, stale or uncertain source-verdict rows |
| Source scenes and locations | 1,391 scenes with time/details; 3,582 formal locations with explicit POI decisions; not crime totals |
| Native GIS | 1,594 decisions: 932 checked display geometries, 662 explicit gaps, zero pending |
| Final map-semantic ledger | 407 in-city/mixed articles; 757 retained scenes; 19 announcement count references |
| Relation/count audit | 114 explicit treatments; 31 confirmed occurrence groups; no duplicated confirmed-occurrence references |
| Candidate | 2,050 formal display locations, 4,645 POIs / 241 tiles; 80 context-only associations |
| Owner approval / publication | Both false |

## Accepted source handling and corrections

The owner explicitly chose: retain literal date/weekday/year conflicts with actual conflicting event dates unknown; keep A6 municipality uncertain and outside verified city counts; keep the two possibly related Scooter accounts independent without selecting a certain gate. This is source-handling authorization, not map approval. All fifteen affected bodies were personally reread and fifteen new source decisions imported. Their factual conflicts have not been declared resolved.

New phase distinctions separate robbery from later victim/property discovery; neighbour violence from later police resistance; the 31 August and 1 September arrests from undated judicial orders. A6's explicitly referenced original accident now has its missing source-occurrence edge. A literal year `206` remains unchanged; only the separate corroborating follow-up supplies its explicit 2026 date in the relationship audit.

All 1,561 prior compiled geometry rows and all 398 prior map choices remain canonically identical. Thirty-three new GIS choices and nine new map choices complete the current inventory. The one added count reference uses the actual Ansbacher Straße/Röthenbacher Hauptstraße shared native node `253853434`; no city/district midpoint or uncertain gate is counted. Nuremberg's existing 106,632-object native index is unchanged.

The browser build exposed 450 historical publication-clock strings without timezones. These now use the existing newsroom parser's `Europe/Berlin` local-clock interpretation, preserving the recorded date/time values. This concerns publication metadata, not inferred incident dates. Two current source pages corroborated the clock strings; body hashes and source reviews are unchanged by that metadata repair.

## Reproduction, inspection and remaining limits

Restore the third repository's ignored `.runtime/review/nuremberg/checkpoint.json`, `*.current` files, formal `map-ledger.current.json`, and `.runtime/safety/cities/nuremberg/newsroom.sqlite` / `reviewed-scene-inventory.json`. Do not overwrite them with historical part files.

The `owner-policy-rereview-20261001/` directory contains a pre-change SQLite/file checkpoint, explicit fifteen-source delta, native junction proof, compilation/install audits, candidate, reproducibility check, browser evidence and `OWNER_REVIEW.md`. The owner ZIP and its checksum remain outside Git. The local route is `?city=nuremberg`; city-switch publication links remain unavailable until approval.

Two builds match across all 257 candidate files. Both hex scales total the nineteen reviewed announcement references. Actual in-app browser loading, month/category filtering, unknown Scooter gate display and separate dated arrests passed. The isolated committed frontend plus city-view addition passes TypeScript and Vite build; no unrelated shared working-tree changes were included.

The 849-source snapshot is the selected channel checkpoint, not a freshly certified archive head or a full crime inventory. Forty municipality-uncertain announcements and 402 out-of-city announcements remain preserved outside the verified city map. Of the requested city geometries, 662 remain unknown; mapped mixed articles also retain unlocated/out-of-city formal locations. Fifty POI footprints, including 46 station footprints, remain unknown.

Current source decision digest: `360b149963cb83fcf35f225f35b44f019e48ef548605300f6f550d7b2b32807f`. Inventory: `3d4285d3adafe2df744efc1f0dc5516d8c21e2b4c638bb696b6d451b33e558a1`. Geometry: `f3f0b0ae42d0644034e23737bc7804f186ec8495562193f61df22cd1a9a89279`. Map ledger: `acdfb6782b7aa357e3a3e71da0a6d1f8aab4855b322de6ddbe33568d54b46bdd`. Relation/count audit: `3464b0d453b4e039942b8c9d8c20d02b0bf5d2b04c31b54e8b9bd27e514489e4`. Candidate: `78b927f8e3a58f6c5db067f44930663ac3deb21a805d2055ca698e09b0d4ba8e`.

Next: owner inspection/questioning and separate approval of this exact candidate before any publication. Stuttgart's saved work and other user-owned chats remain intact.
