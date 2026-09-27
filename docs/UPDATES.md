# Updates without LLM calls

## Routine commands

```sh
export PYTHONPATH="$PWD/src"
uv run python scripts/safety/update.py
# Full archive discovery plus bounded body fetching
uv run python scripts/safety/update.py --full --limit 1500
```

Default update: inspect the first two official archive pages, fetch new articles, revisit recently published articles, rotate previously fetched articles older than seven days. On Sundays it scans all archive index pages. It processes up to 250 eligible article requests per run. Full initial import is separate. Source requests are serial, at least one second apart, with a 25-second timeout; same-origin redirects only. Robots.txt must be successfully fetched and permit requests.

SQLite commits after each article. Canonical numeric `pressemitteilung` IDs prevent duplication when an article moves into a year subdirectory. HTTP ETag/Last-Modified save unchanged response bodies where supported. A SHA-256 of normalized article text detects revisions even when HTTP validators are absent. A separate hash-only revision ledger records changes; old full text is not duplicated.

Failures use a persisted retry-after with exponential backoff from five minutes to one day. An error does not erase a previous good report. Parser failures remain visible and do not silently generate empty events. Local lock files prevent simultaneous scheduled and manual collection.

The current-year archive is discovered automatically. Previously stored years remain in SQLite. Historical years not previously collected must be explicitly imported with `collector --year YEAR --full`; the pipeline does not claim missing years are covered.

## Scheduling

macOS, daily at **07:15 in the machine's local time zone**:

```sh
uv run python scripts/safety/schedule.py show
uv run python scripts/safety/schedule.py install
uv run python scripts/safety/schedule.py remove
```

The installer creates a user LaunchAgent pointing at this checkout's `.venv`; no administrator privileges and no Codex/LLM run. It does not immediately fetch. If the computer is asleep/offline the job cannot provide continuous coverage; inspect the status on return. Moving the checkout requires reinstalling the timer.

Linux example, after setting an absolute checkout path:

```cron
15 7 * * * cd /absolute/CrimeMapsBerlin && PYTHONPATH=src .venv/bin/python scripts/safety/update.py >> .runtime/safety/scheduled.log 2>&1
```

OSM refresh is separate to avoid downloading ~100 MB daily:

```sh
uv run python scripts/safety/fetch_osm.py --refresh
uv run python scripts/safety/extract_pbf.py
uv run python scripts/safety/build.py
```

## Inspect and recover

- `.runtime/safety/update-status.json`: latest completed scheduled update counts.
- `.runtime/safety/build-audit.json`: discovered/fetched/pending/errors, mapped/unlocated and output generation.
- `.runtime/safety/review-queue.json`: source URL, extracted name candidates and reason for abstaining.
- `.runtime/safety/police.sqlite`: durable state; back it up locally with SQLite's backup API.
- `.runtime/safety/scheduled*.log`: schedule stdout/stderr.
- `runs` rows without `finished` indicate interruption or source-level failure. The last published manifest remains usable.

To resume, rerun the same command. Do not delete SQLite to recover from a transient failure. If HTML changes, save a minimal anonymized fixture and repair `listings` or `article_text`; do not weaken the non-empty-content guard. Investigate repeated failures and unexpectedly low mapping rates before publishing claims about coverage.

Publication retains old generation directories for active readers. Periodically remove generations no longer referenced by any open/deployed session; retain at least current and previous. No automatic deletion of evidence is performed.

No automatic public deployment or raw-data upload is included. Static hosting must configure gzip/Brotli for JSON/JS, short caching for `manifest.json`, and immutable caching for generation paths. Code CI never crawls the live police site.

Article-level HTTP 404/410 and other refresh failures are retained as source status. The map marks an unavailable/stale original instead of presenting cached content as freshly verified. Refresh success clears the failure state. Article removal is not interpreted as proof that the original event did not happen.

An open browser checks the small manifest every five minutes while visible. When a new generation appears, it offers a refresh button; it does not silently discard the user's selected report. Network failure leaves the loaded snapshot readable.
