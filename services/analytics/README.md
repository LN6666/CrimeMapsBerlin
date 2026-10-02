# CrimeMaps visit statistics

This service collects optional page views for the 14 CrimeMaps maps and publishes country totals. It is a separate Cloudflare Worker with one D1 database. Each city has its own namespace. The static GitHub Pages site only reads published totals and sends a verified event when a visitor chooses to count the current page view.

The delivered configuration is **not connected**: collection is disabled, the database ID is a placeholder, and no production secrets or public sitekey have been supplied. Local tests and screenshots use clearly labelled fixtures. They are not live visitor statistics.

## What the figures mean

A PV is one page view sent after the visitor chooses to share it, passes a browser check, and is admitted by the backend. The frontend sends at most one event for that document and city. Language, month and viewport changes do not send events. Reloading or opening another page can count again if the visitor chooses to share it. README image requests never count as map page views.

Unique visitors are not measured. CrimeMaps creates no persistent browser identifier, analytics cookie or visitor profile. Provider browser signals are described below. Visitors who opt out, enable GPC/DNT, block the service, fail verification, or arrive after a limit is reached are absent from these counts. A successful browser check does not prove that the request came from a human or that a map was viewed. Country estimates can reflect a proxy or VPN. The figures describe accepted events and remain open to manipulation.

Internally, country totals are exact accepted-event counters. Public totals and country groups are shown only from 20 events, rounded down to multiples of 10. Up to eight countries are shown; unknown countries, small groups and other countries are combined. A combined group below 20 stays hidden. Rounding and omitted groups mean the visible bars may not sum to the displayed total. No per-visitor information or individual visit times are published.

## Interfaces

| Endpoint | Method | Result |
|---|---|---|
| `/v1/events/{city}` | POST | Validated page view; `202 {"accepted":true}` only after committed storage |
| `/v1/stats/{city}` | GET / HEAD | Public aggregate JSON, schema 1, no write |
| `/v1/chart/{city}.svg?lang=de` | GET / HEAD | Safe horizontal SVG with localized labels, title, description and UTC generation time |

`city` is one of berlin, hamburg, munich, cologne, frankfurt, dusseldorf, stuttgart, leipzig, dortmund, bremen, essen, dresden, hannover, nuremberg. Chart languages are `de`, `en`, `zh`.

POST body has exactly three keys: `{ "event": "pageview", "path": "/crimemaps-Berlin/", "token": "<single-use Turnstile token>" }`. There is no client-supplied country, URL, count or timestamp. Server verification requires `hostname=ln6666.github.io`, `action=pv_berlin`, `cdata=berlin`. Origin must be `https://ln6666.github.io`. CORS and path checks are input checks, not proof of a real visitor. All 14 repositories share the GitHub Pages origin, so the challenge bindings and fixed city paths are also checked. Repository page paths use `/crimemaps-{City}/`, with only the first letter of the existing English slug capitalized. Internal city IDs, API routes, challenge action/cdata and snapshot source URLs remain lowercase; old and differently cased page paths are rejected.

Errors are `400/403/404/405/415/429/503`, with short non-sensitive error codes. Collection and API errors use `no-store`; successful reads use a canonical server cache key and a five-minute cache. GET is public read-only, including requests made by GitHub's image proxy. `COLLECTION_ENABLED=false` returns `503 not_connected`, not a fabricated zero.

## Local checks

Node 22 and npm are sufficient; tests use the actual workerd runtime and D1 SQLite implementation. Siteverify is replaced by a local test service, so tests do not call Cloudflare or need an account.

```sh
npm ci --no-audit --no-fund
npm test
WRANGLER_SEND_METRICS=false npm run check:deploy
npx wrangler d1 migrations apply crimemaps-analytics --local
npm run dev
```

The last command starts a real local Worker, with collection disabled by default. The separate frontend fixture is `npm exec vite -- --config test/preview/vite.config.mjs`, on loopback port 4188. `/?fixture=success` supplies labelled synthetic responses; failure, malicious, privacy, delay and unconnected modes exercise the actual component. The fixture never submits an external page-view event. Keep `test/preview/` out of site builds.

`npm run test:browser` contains seven Playwright cases and requires an installed Chrome channel (or a locally configured Chromium executable). This host has no standalone Chrome/Chromium, so those cases were not run successfully here. The actual Codex IAB checks cover rendering, language changes, one opt-in POST, errors, GPC and cancellation. Mobile's separate IAB evidence covers three languages at 320/390/430 pixels. Those are desktop Chromium viewport checks, not Android/iOS or WebKit acceptance.

## Privacy and abuse limits

Only `request.cf.country` supplies the country; JSON and country headers cannot override it. Raw IP is never written to D1 or passed in the Siteverify payload. The backend uses the edge-supplied IP only to compute a server-secret HMAC that changes every minute. The temporary table contains that code, a count, a random admission nonce and an expiry, with no country or article association. These records are pseudonymous rather than anonymous.

A preliminary edge limit allows 30 attempts per minute per temporary code. The database then admits at most ten verified events per minute across all cities for that code. An atomic SQL batch binds the aggregate write to the current admission nonce. Triggers and a database constraint enforce a global ceiling of 5,000 accepted events per UTC day, across the 14 cities. Shared NAT addresses can be limited together. The preliminary Cloudflare limiter is permissive and local to each edge location; it is not used for exact accounting. The D1 limit and daily ceiling are checked atomically.

Temporary codes expire within 120 seconds. A minute cron deletes expired rows, so they normally disappear from the active application within three minutes. If cron or D1 fails, physical deletion is delayed until cleanup succeeds; expiry still prevents a stable long-term identifier because the next minute uses a different code. Daily budget rows are removed after two days; cumulative country totals remain. D1 recovery history on the Free plan can retain deleted temporary rows for up to seven days. Do not export this database or keep separate backups of temporary records. After any authorized restoration, immediately purge expired temporary rows and verify the current UTC daily-budget row before reopening collection; a restore may otherwise lower the budget or revive old temporary rows.

Workers observability is explicitly disabled. The worker does not write request bodies, IPs, tokens, user agents or secrets to logs, and has no tail/Logpush export. Verify account-level logs, tracing and attached tail services before enabling collection. Cloudflare still handles network connections and has its own privacy and security operations. Turnstile processes connection and browser signals, including IP, TLS fingerprint and user-agent information, both to detect bots and to improve detection. It has service-provider and independent processing roles under its addendum. The application cannot promise that no provider handles an IP or browser fingerprint, or that the whole service is fully anonymous.

The application ceiling protects accepted database writes, not all request/CPU/read quotas. A distributed attacker can exhaust free quotas, poison allowed counts or deny collection. Verification is not a WAF, and the daily cap intentionally sacrifices completeness rather than enabling billing. Quota failure leaves the map usable and statistics unavailable.

## Free plan and official sources

Checked 2026-10-03, Japan time. Workers Free currently permits 100,000 requests/day and 10ms CPU per invocation. D1 Free has 5 million rows read/day, 100,000 rows written/day and 5GB total storage. The single-database Free maximum is 500MB; ten free databases means fourteen separate free databases are not an option, which is why this design uses isolated city keys in one database. Index/trigger operations and deletions also consume row writes. The 5,000-event application cap leaves conservative write headroom; it is not a guarantee for an account that shares quotas with other services. D1 stops queries when its free limits are exhausted. Turnstile Free allows up to 20 widgets and 10 hostnames per widget; all fourteen GitHub Pages paths use one hostname and can share a widget with city actions.

[Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/), [D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/), [D1 limits](https://developers.cloudflare.com/d1/platform/limits/), [Turnstile plans](https://developers.cloudflare.com/turnstile/plans/), [edge country](https://developers.cloudflare.com/workers/runtime-apis/request/), [rate limiter](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/), [server verification](https://developers.cloudflare.com/turnstile/get-started/server-side-validation/), [D1 recovery history](https://developers.cloudflare.com/d1/reference/time-travel/), [Workers logs](https://developers.cloudflare.com/workers/observability/logs/workers-logs/), [Turnstile privacy addendum](https://www.cloudflare.com/turnstile-privacy-policy/).

## Production connection

Migration owns shared integration and any remote deployment. This module has not registered an account, enabled a paid plan or deployed a Worker. To connect the delivered implementation, use an existing authorized Workers Free account and record its real free-plan status; do not upgrade or enable automatic billing. Create one database and a Managed Turnstile widget for `ln6666.github.io`, fill the D1 ID, apply the migration, and store `TURNSTILE_SECRET` and `RATE_HMAC_SECRET` through Wrangler's secret store. Generate the latter from at least 32 random bytes, encoded as base64url; never commit it or put it in a Vite variable. Test keys are rejected by the production worker. Keep local `.dev.vars` ignored.

The operator must provide the actual privacy-notice controller/contact, purpose, legal basis, rights, transfer and provider-contract information required for the chosen deployment; validate the account's region/backup/log settings and cleanup operation with security. The supplied opt-in screen is a product control, not a legal-compliance certification. Leave `COLLECTION_ENABLED=false` until the real connection and those deployment requirements are checked. The final URL and public sitekey can then be supplied to the frontend. Verify real geographic metadata, challenge rejection/replay, all city keys, read-only cache behavior and database writes on the deployed service before calling it connected. Full-map launch gates still apply.
