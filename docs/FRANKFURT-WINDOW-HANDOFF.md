# Frankfurt parallel window handoff

Saved on 2026-09-30 (Asia/Tokyo). Destination Codex thread:
`01a0f10e-ea87-7373-bb92-5d5357cde5d2` (local). The owner authorized a separate window so
Frankfurt and Nuremberg can advance concurrently. Frankfurt belongs to the
first five-city repository. This window takes Frankfurt through the current
Berlin/Hamburg semantic standards, checked geometry, final map semantics,
browser candidate and owner inspection. The coordinating window keeps
Nuremberg and cross-city integration.

## Authoritative local state

- Repository: `/Users/liangjuanning/Documents/ChatGPT/CiviFlux`.
- Current feature branch: `codex/selected-german-cities`. Do not switch branches
  in this shared checkout or reset, stash or stage another window's work.
- Database: `.runtime/safety/cities/frankfurt/police.sqlite`.
- Selected official channel: Polizeipräsidium Frankfurt am Main-signed
  Presseportal newsroom 4970. Its 2026 traversal and source hash checks cover
  1,230/1,230 articles, with zero missing bodies or source errors. This is the
  selected channel's completeness, not a complete city crime inventory.
- First-pass full-text LLM review: **460 sources read, 458 supported,
  2 uncertain, 770 pending, 0 stale**.
- All reviewed verdicts preserve 884 source-local scenes and 1,739 formal
  locations. The supported-only inventory retains 880 scenes, 1,729 locations
  and 1,404 municipal geometry requests. These are source scenes, not 880
  independent confirmed crimes or count points.
- Decision-set digest:
  `d8bb96fc3a22ee7d617a926c175c206894ed73006dc4e4c4333ea20dbc9dac95`.
- Supported inventory digest:
  `21f89ba1f0d1e6164e16b6aa25de4642881396b85a7c5e2f86428d7fb251194c`.
- Geometry, final categories/count decisions, browser candidate and owner
  approval remain incomplete. Frankfurt has not been published.

## Recoverable files and next source

`.runtime/review/frankfurt/checkpoint.current.json` records current counts,
the two source questions, structural semantic gaps and the next batch.
`review-decisions.current.ndjson`, `scope-decisions.current.ndjson` and
`scene-decisions.current.json` reproduce all 460 decisions. Their reimport
validated all rows and was idempotent: 460 unchanged, zero inserted or changed.
`CHECKSUMS.current.sha256` binds these restore files and the checkpoint.
`restore-validation.current.json` preserves that result.

The supported inventory is
`.runtime/safety/cities/frankfurt/reviewed-scene-inventory.json`.
Parts 0001–0046 remain in `.runtime/review/frankfurt/`. The next unreviewed
article is ordinal **461**, in **source-batch-0047.ndjson** inside:

`.runtime/review-packs/frankfurt-selected-newsroom/CrimeMapsDE-frankfurt-source-review-input-20260929T144115Z.zip`

ZIP SHA-256:
`20d7d8c1b420e848b28e3deefb50cbb1eb65c2df54eae0f6894f6a142e0b81d7`.
Its entries use `source_body`, not `body`; verify each source ID, URL and body
hash against current SQLite before importing decisions. The serializer
`/tmp/frankfurt_review_authoring.py` only writes personally authored decisions
and invokes the existing evidence gate. It is a convenience, not semantic
analysis or a required implementation dependency.

## Required semantic repairs

First-pass progress does **not** establish current six-rule completeness.
An explicit structural audit found that the early 400 decisions omit event
time on 755 scenes. A further 1,484 locations in 371 articles lack an explicit
`poi_contexts` field. Parts 0041–0046 supply event times and explicit POI
lists, but a full source-stage completion claim still needs the retained
owner rules to be checked across the entire corpus.

Read each unchanged complete official body personally and decide the missing
time/transit/POI semantics. Preserve and correct the existing source-backed
scene and location inventory. Do not mechanically fill empty POI lists,
unknown times or “supported” verdicts just to pass a schema. Programs may
fetch, serialize, verify exact evidence/hashes, calculate selected geometry
and enforce duplication/publication gates; the LLM owns narrative analysis.

Keep discovery/treatment, original offence, arrest/escape, search/operation
and background locations separate. Retain all independent cases and formal
places, original event times, source-backed whole roads and moving transit
lines or segments. Never generate a city/district representative crime point,
invent a venue/address, or attribute an offence to nearby businesses. Explicit
POI emphasis is context, not proof an offence occurred at that POI. Bias labels
require explicit motive evidence in the narrative.

## Open source questions and counting relations

- `6249936`: A5 collision and AK Bad Homburg. Prove the relevant scene's
  municipality with checked geometry; the Frankfurt newsroom signature is
  not geographic evidence. Keep its current uncertain verdict until resolved.
- `6253296`: the same original says Friday morning on 10 April and 19:35.
  Preserve both statements and seek source clarification; do not choose one
  automatically or hide the contradiction.

`source-relations.continuation-0041-0046.json` saves five source-hash-bound
proposals: three missing-person closures; the background reference from
`6248829` scene 2 to `6248055` scene 1 (the current theft in scene 1 remains
independent); and the two announcements of the same planned Speedmarathon.
They are not compiled final map-count decisions.

Earlier known relations also remain required: `6226994` and `6226997` have
identical official text/hash and must not count twice; `6237497` follows
`6235858`'s fatal tram/E-scooter collision. Aggregate 2025 PKS or explosion
statistics are not individually located new 2026 cases. Read the corresponding
source evidence before authoring final relation decisions.

## Parallel ownership and delivery

Own Frankfurt runtime files and `docs/FRANKFURT-PROGRESS.md`. Read README and
`docs/HANDOFF.md` for common contracts. Leave Nuremberg, other cities, global
progress tables and other windows' code changes to the coordinator. Shared
code fixes may be needed: inspect and preserve current diffs, then make only
the necessary compatible fix with focused verification and document it.

There are existing unrelated edits in `geometry_decisions.py`, its tests and
the README/HANDOFF/CHANGELOG for the Essen/Dresden/Hannover
`--no-representative-points` mode. Preserve them. Do not bulk-stage these
files, overwrite the shared index or change branch history. The owner has
authorized GitHub development updates, but raw bodies, source downloads,
runtime ledgers and generated city data must stay ignored by Git. Keep city
code/document changes reviewable and coordinate shared-file integration.

Continue through checked geometry and map/browser stages without reopening
finished unchanged work merely for extra testing. Save resumable source-bound
checkpoints. Do not call approve, publish, merge protected branches, use paid
APIs or start further subagents/windows without separate authorization.
Completion requires a full current-source semantic pass, handled geometry
requests with explicit unresolved reasons, final categories and deduplication,
a validated browser candidate, and the owner's inspection/approval before
publication.
