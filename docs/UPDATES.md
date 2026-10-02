# Checked city updates

Official police announcements are checked every **72 hours**, including new announcements and source revisions. Stored map geometry and background POIs are refreshed once per calendar month in **Europe/Berlin**, including roads, buildings and administrative boundaries. Initial import is separate: an accepted initial snapshot can count for its own month. Only a successful, checked snapshot advances the month marker; failed attempts do not skip later retries.

The owner has created an active Codex coordination heartbeat for all 14 cities, every three days at 09:00 Asia/Tokyo. The host and app must be available. This coordination schedule is not a city-specific unattended collector or a promise of publication within three days. The first successful coordinated 14-city refresh remains pending. `config/update-cadence.json` keeps local OS timers and an unattended city worker disabled; this repository does not install an extra timer.

The former daily 07:15 LaunchAgent, shared Berlin-only label and direct collection/build wrapper are retired. `update.py` exits before source collection, extraction, status changes or a map build unless asked for a read-only plan. `schedule.py install` and `remove` also exit without changing any existing LaunchAgent.

## Inspect the policy

```sh
uv run python scripts/safety/cadence.py
uv run python scripts/safety/schedule.py show
uv run python scripts/safety/update.py --plan
# Optional checked local state and a deterministic, timezone-aware inspection time:
uv run python scripts/safety/cadence.py --state /absolute/path/to/update-state.json --now 2026-10-03T00:00:00Z
```

These commands only read configuration/state and print eligibility. They do not fetch, publish, install jobs or create runtime state. The planner verifies the lowercase city ID against this repository's identity. Announcement eligibility uses elapsed UTC hours, independent of daylight saving time; monthly eligibility uses Berlin's calendar month.

## Collection, review and release

Use each city's existing deterministic source acquisition entrypoint and accepted checkpoints. Reuse unchanged source, location and scientific review evidence. Review new or revised announcements and materially affected location matches; translate new public fields in German, English and Chinese, and run the affected source, semantic, geometry, count and browser checks. Keep acquisition, normalization, geocoding, metric geometry, packaging and publication separate. The old Berlin collector wrapper is not a universal 14-city worker.

Official archive coverage and article revisions must remain explicit. Respect robots.txt, bounded serial rates, retries and local checkpoints. Use native official archives if an intermediary feed is incomplete. A missing, unavailable or failed source check blocks claims of current coverage. A police announcement is not necessarily one crime or a complete crime inventory.

On failure, preserve the previous good candidate and release; retain local checkpoints and visible errors. Do not remove SQLite state to recover from a transient failure. Preserve source URLs, article IDs, revision hashes, source-bound historical location evidence and unknown geometry when present-day businesses change. Changed OSM inputs may be downloaded through the existing checked acquisition process where supported; unchanged background POIs do not need a new AI review. Third-party basemap tile updates and HTTP caching remain provider-controlled.

Record three separate dates: `last_successful_source_check`, `last_announcement_publication` and `last_map_poi_snapshot`. Collection or an artifact build must never advance the publication date. `record_success` only returns a proposed copy of checked state: its caller retains the external hash-bound evidence and persists state after success. An accepted snapshot's actual timestamp determines its successful month. Runtime state, raw reports, downloads, generated city data, private review evidence and credentials stay outside Git. Historical backups remain outside the current public site, and each city artifact stays within its size budget.

## Required before first public launch

Before publishing the 14 city sites, catch up every official source from its accepted checkpoint through the latest available entries and revisions. Reuse unchanged review evidence, then save a checked per-city update receipt and isolated candidate. At final publication preflight, all 14 receipts must be complete and each latest successful source check must be no more than **72 hours old**. If preparation crosses that window, check only subsequent changes; do not repeat the full historical import.

The detached release acceptance includes a `prelaunch_refresh` object with `status: passed`, the city and full repository identity, `last_successful_source_check` as an aware ISO timestamp, a `checked_candidate_receipt_sha256` matching the final artifact receipt, and a hash-bound `evidence_sha256` for the checked refresh receipt. The release verifier rejects missing, stale, future, naive or foreign-city refresh evidence. This requirement is in addition to the existing 15 product checks and bound scientific/presentation inputs.

Apply standing routine owner approval to the checked current batch hashes after the required checks pass. No additional routine approval question is needed. The active coordination heartbeat and configured cadence do not enable Pages, bypass release checks or establish completed source coverage. First-publication refresh and actual public deployment remain pending until their recorded checks pass.
