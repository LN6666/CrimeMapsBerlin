# CrimeMapsBerlin working agreements

Read README.md and docs/HANDOFF.md. The former CiviFlux mission and model requirements are superseded by the owner's explicit project replacement.

- Deliver the Berlin police-report map and extend the owner-selected 14 cities in three repositories grouped 5/5/4, with Berlin as the default entrance. No traffic/fire plugin, SUMO or QGIS.
- Keep source crawling and GIS calculations deterministic. Source-backed Codex review of every announcement and the required source, semantic, geometry and browser checks remain mandatory. On 2026-10-02 the owner said “全部批准，以后这种批准不用问我”: the current delivered Essen batch, including its attachment findings, is approved, and the same routine owner-review approval step for authorized project batches has standing authorization; do not ask again or keep a completed batch blocked solely awaiting that approval. Record the applied authorization against the current batch hashes after its required checks pass. Missing, stale or uncertain source review still blocks the update. This supersedes older per-batch owner inspection/approval requirements; it does not itself perform publication. No paid API calls without a separate user instruction.
- Keep source acquisition, normalization, geocoding, metric geometry, publication and browser presentation separate.
- Retain source article IDs, URLs, revision hashes, location precision, provenance and incomplete coverage. A police announcement is not necessarily one crime or a complete crime inventory.
- Use native official archives when an intermediary feed is incomplete. Respect robots.txt, bounded request rates, retries and local checkpoints.
- No generated coordinates for district-only reports. Unknown venue geometry stays unknown. Nearby associations do not establish an offence at a named business.
- Browser work must preserve month/viewport loading, bounded caches, cancellation and batched WebGL layers. Test changed behavior with relevant checks.
- Never commit raw report bodies, runtime archives, source downloads, personal credentials or generated city data. Preserve previous good publications if ingestion fails.
- Git branches use codex/. Preserve Git history. Never force-push main, rewrite history, weaken branch protection or hide failed CI to make a release appear ready.
- Document source gaps and practical next actions. Do not describe partial Europe coverage or unverified geocodes as complete.
- “可能仇恨犯罪” is only an AI lead supported by explicit bias evidence in the official narrative, not a police finding. Do not infer hate motive from identity, origin, neighbourhood or immigration status alone; do not present selected announcements as a true-crime risk index.
- Do not introduce subagents without an explicit request. Keep unrelated user files intact.
