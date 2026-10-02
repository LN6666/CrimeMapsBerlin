# Private feedback receiver — operator setup

This is a local, tested implementation. It has not been deployed or confirmed to receive real visitor messages. `wrangler.example.toml` starts with `ENABLED=false`; a missing binding, real key, operator name or health response keeps the UI unavailable. No external accounts, paid plans, email or public posts were created by this task.

## Free options checked on 2026-10-03

| Channel | Visitor privacy and operation | Decision |
|---|---|---|
| Public GitHub Issues / Discussions | Visible account and text; GitHub login required. Private-repository discussions exclude ordinary visitors who are not collaborators. | Public software issues only; unsuitable for private reports. [GitHub visibility](https://docs.github.com/en/repositories/creating-and-managing-repositories/about-repositories) |
| Tally form | A third party stores responses; private responses do not require publication. Tally says its form data is stored in Europe. Its configurable automatic retention is a Business feature; free operations need manual deletion, and backups have their own removal window. | Feasible fallback but less control over automatic deletion and deletion-code workflow. [Tally GDPR](https://tally.so/help/gdpr), [settings](https://tally.so/help/form-settings) |
| Email / mailto | Reveals a sender address, depends on a real mailbox, often copies content to multiple mail systems; a static mailto cannot prove receipt. | No email sent or mailbox invented; not selected. |
| Cloudflare Workers Free + D1 + Turnstile | Operator-owned private queue, no visitor account/contact field, server challenge and deletion-code support. Provider still processes IP, user agent and TLS/browser signals. It acts as processor for delivery and as a separate controller for improving bot detection; operators must reflect both roles in the real notice. [Turnstile privacy](https://www.cloudflare.com/turnstile-privacy-policy/). | Selected implementation; actual Free account/bindings/keys/notice still required. [Workers limits](https://developers.cloudflare.com/workers/platform/limits/), [D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/), [Turnstile Free](https://developers.cloudflare.com/turnstile/plans/) |

Workers Free currently permits 100,000 requests/day with 10 ms CPU/request. D1 Free includes 5 million rows read/day, 100,000 rows written/day and 5 GB total storage. These are account limits shared with any other workloads, not guaranteed capacity for this form. Application limits are lower: 5 submission attempts/IP/hour, 1,000 total private actions/day, 500 received messages/day. Platform burst limiter: 60 calls/minute per Cloudflare location, approximate; D1 enforces the global caps atomically. Quota exhaustion fails closed. No upgrade or billing switch is authorised here.

## Activation steps

1. On an existing or owner-selected **Free** Cloudflare account, create one D1 database and one Turnstile widget. All 14 repositories currently share `ln6666.github.io`, so one hostname can cover them. Never switch to a paid plan to pass a check. Confirm actual account plan and remaining free quotas.
2. Copy `wrangler.example.toml` to a non-secret deployment config, replace D1 UUID, and run `wrangler d1 execute crimemaps-private-feedback --remote --file schema.sql`. Obtain a current official Wrangler through the operator's approved tooling. This task does not install it or make remote changes.
3. Create independent 32-byte random `RATE_SECRET` and `ADMIN_TOKEN` (64 hex characters). Store those and the real `TURNSTILE_SECRET` using `wrangler secret put`; none belongs in static assets, Git, URLs, CI logs, source downloads or a public issue. Test keys are rejected. The namespace `10013` must be unique among unrelated Workers on the account.
4. Set the true operator identity and an actual public privacy notice URL. Fill operator contact, processing purpose and basis, recipients/transfers, retention, visitor rights and complaint route for the real deployment; the form's short policy and this implementation do not certify legal compliance. `docs/FEEDBACK.md` is a channel guide, not a complete operator notice. Do not activate the template operator name or a placeholder notice.
5. Set exact allowed HTTPS origins and Turnstile hostname. Deploy this Worker with D1 and `REQUEST_LIMITER` bindings and disabled Workers observability. Server verifies Turnstile success, hostname and action `feedback` through Siteverify. `CF-Connecting-IP` is used only when Cloudflare's request metadata exists; raw IP is never stored or returned. [Server verification](https://developers.cloudflare.com/turnstile/get-started/server-side-validation/), [rate binding](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/).
6. Configure frontend `FeedbackConfig {endpoint, siteKey, operatorName, privacyURL}` with the exact HTTPS API root and real site key. The site key is public; receiver secrets and admin token are server only. Security must explicitly allow the API origin in `connect-src` and `challenges.cloudflare.com` for Turnstile script/frame/connect. No `*.workers.dev` CSP allowance. CORS is browser access control, not authentication; all 14 GitHub Pages repositories share an origin.
7. Complete real challenge, receipt, operator read and deletion checks with a harmless test message, then clear it. Verify error/limit states. Only then set `ENABLED=true` and verify `GET /health?city=<slug>` returns that city, `enabled:true`, and `policyVersion:private-feedback-v1`. Complete the project’s full launch gates before exposing the site. An HTTP health response alone does not prove that operator access or challenges work.

## Processing and deletion

The only collected record fields are random receipt ID, city, type, optional source ID, short plain-text message, created/expiry times and SHA-256 of the random deletion code. Message input has no name/contact field and accepts no attachments or arbitrary forwarding URLs. Free text can still contain personal details; operators should delete unnecessary personal information promptly. Source bodies, visitor accusations and full audit files are never automatically published or sent to an AI service.

The temporary limit key is an HMAC of day and trusted connection IP using a secret, expires at the next UTC midnight; the following 03:10 UTC daily cleanup removes it, normally within 27 hours 10 minutes from creation and below 48 hours. Failed provider scheduling or quota exhaustion can delay physical cleanup; operators must monitor scheduled-run success and run cleanup after an outage. It is pseudonymous, not anonymous; users sharing a network may share a submission limit. No public endpoint exposes messages, hashes or connection identifiers. `/retract` accepts receipt ID and 256-bit code in a JSON POST, stores only a token hash and always returns the same 204 response for validly formed nonexistent/wrong-code/already-deleted records. Do not place codes in a query string. The CrimeMaps code keeps the receipt on screen only; it writes no cookies or persistent storage. Provider browser checks may use their own storage or cookies according to their policy; configure Turnstile without pre-clearance for this form. Changing page/language clears the code, so visitors must copy it privately.

Operator CLI:

```sh
# Set CRIMEMAPS_FEEDBACK_ENDPOINT and CRIMEMAPS_FEEDBACK_ADMIN_TOKEN privately.
node operator.mjs list berlin
node operator.mjs list berlin '<returned cursor>'
node operator.mjs delete '<receipt ID>'
```

CLI output is private content. Keep it out of public CI, GitHub Issues and source archives. Messages are JSON plain text; there is no public comment renderer or publication endpoint. Review requests manually, verify them against the official source, and pass corrections to the existing source/geometry workflow. A visitor claim cannot change a reviewed map directly. Any future public comment feature would require separate moderation, redaction, abuse handling and deletion support.

Admin access requires a server-only bearer secret and rejects browser Origin headers. This is a small operator queue, not multi-user account management; rotate its token if an operator leaves. Admin output is paginated, city-filtered and omits token hashes. Physical cleanup runs daily and on successful intake; expired messages cannot be read after 30 days and are removed within the next day. D1 Time Travel can contain deleted records for up to seven more days on Free. Do not export the queue, extend backups or restore old personal messages into the active service; restoring requires immediate expiry cleanup. [D1 backups](https://developers.cloudflare.com/d1/reference/time-travel/).

## Verification limits

Local checks use real SQLite, real loopback HTTP and actual IAB rendering. Cloudflare metadata, platform limiter and Siteverify responses are explicitly fixtures in local tests. Those fixtures never become a production bypass; the Worker uses real `fetch` and provider bindings by default. Tests establish application behaviour, not real account readiness, provider CPU headroom, exact network latency, actual mobile keyboard behaviour or complete legal compliance. Security and migration own real service/CSP integration and final launch acceptance.
