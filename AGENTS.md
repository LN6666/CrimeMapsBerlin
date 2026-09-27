# CrimeMapsBerlin working agreements

Read README.md and docs/HANDOFF.md. The former CiviFlux mission and model requirements are superseded by the owner's explicit project replacement.

- Deliver the Berlin police-report map and its deterministic update pipeline. No traffic/fire plugin, SUMO, QGIS or local model deployment.
- Do not require LLM calls for scraping, classification, geocoding, aggregation or daily updates. No paid API calls without a separate user instruction.
- Keep source acquisition, normalization, geocoding, metric geometry, publication and browser presentation separate.
- Retain source article IDs, URLs, revision hashes, location precision, provenance and incomplete coverage. A police announcement is not necessarily one crime or a complete crime inventory.
- Use native official archives when an intermediary feed is incomplete. Respect robots.txt, bounded request rates, retries and local checkpoints.
- No generated coordinates for district-only reports. Unknown venue geometry stays unknown. Nearby associations do not establish an offence at a named business.
- Browser work must preserve month/viewport loading, bounded caches, cancellation and batched WebGL layers. Test changed behavior with relevant checks.
- Never commit raw report bodies, runtime archives, source downloads, personal credentials or generated city data. Preserve previous good publications if ingestion fails.
- Git branches use codex/. Preserve Git history. Never force-push main, rewrite history, weaken branch protection or hide failed CI to make a release appear ready.
- Document source gaps and practical next actions. Do not describe partial Europe coverage or unverified geocodes as complete.
- Do not introduce subagents without an explicit request. Keep unrelated user files intact.
