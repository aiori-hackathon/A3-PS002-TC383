# Consent Prototype (AIORI Hackathon 3, PS-002)

Purpose-based consent recording and withdrawal for a synthetic service, with a mock data-sharing API that
checks consent on **every** request and an audit log that can be verified and exported. Synthetic data only.
This records technical consent evidence; it is not a legal certification of DPDP Act compliance.

## Run locally (Windows 11 / Docker Desktop)
```
docker compose up --build
```
Open http://localhost:8000 (API docs: http://localhost:8000/docs).

```
docker compose --profile tools run --rm tests     # the 28 lifecycle tests
docker compose --profile tools run --rm demo      # scripted grant -> share -> withdraw -> refused -> notice change
docker compose run --rm --no-deps api python -m scripts.bench_pep   # PEP latency with and without the check
docker compose down -v                            # RESET: deletes the database volume for a clean start
```
Without Docker: `pip install -r requirements.txt`; `cd frontend && npm install && npm run build`, copy `frontend/dist`
to `app/static` (`xcopy /E /I dist ..\app\static` on Windows); then
`uvicorn app.main:create_app --factory --port 8000`.

## Deploy on Render (HTTPS included)
1. Push this repository to GitHub. In Render choose **New > Blueprint** and select it (it reads `render.yaml`).
2. Render builds the `Dockerfile`, serves the app over HTTPS and generates the API keys. Read them in the service's
   **Environment** tab (`KEY_ANALYTICS_CO`, `KEY_MAILER_CO`, `KEY_RESEARCH_LAB`). The keys are for partner systems
   calling `POST /api/share`; the web console does not need them.
3. **The console is locked by default:** Render generates `CONSOLE_PASSWORD`. Read it in the **Environment** tab and share it with
   your evaluators (browser prompt, any username). Delete the variable to open the console. The health check and the partner API
   stay reachable (the partner API has its own API-key check). The app also refuses to start on Render with the built-in local
   API keys, and `/docs` is switched off there.
4. **Persistence:** `render.yaml` uses the free plan, which has **no persistent disk**. The database, including the
   ledger, resets when the service restarts or redeploys, and a free service sleeps when idle. For a ledger that
   survives, use a paid plan and uncomment the `disk:` block in `render.yaml`.
5. TLS ends at Render's proxy. The app trusts `X-Forwarded-Proto`, sends HSTS on HTTPS requests, and sets
   `nosniff`, framing, referrer and content-security-policy headers on every response.

## How people and organizations use it
- **The web console** is the service's own interface. It has no sign-in: the server acts for the person or
  organization you pick. Real user authentication is out of scope, so anyone who can reach the console can act in
  it. Set `CONSOLE_PASSWORD` on a public deployment.
- **A partner system** calls the API with its own organization key:
  ```
  curl -X POST https://<host>/api/share -H "X-API-Key: <key>" -H "Content-Type: application/json" \
       -d '{"user_pid":"u001","purpose":"analytics"}'
  ```
  `GET /api/requester/revocations` (same header) lists withdrawal notices; `POST /api/requester/revocations/{n}/ack` acknowledges one.
- The console sends requests for the seeded organizations through the **same** enforcement point and key check.

## Which consent this resolves
Consent as the lawful ground under **DPDP Act 2023 s.4(1)(a), read with s.6**: specific to a purpose, preceded by a
notice (s.5), withdrawable with comparable ease (s.6(4)). Not covered: s.7 legitimate uses, children's consent (s.9),
Consent Manager registration (s.6(7)-(9)), erasure of data already shared.

| Requirement | Where it shows in the prototype |
|---|---|
| Specific, per-purpose consent (s.6(1)) | one agreement per purpose; data fields listed on each card; each organization registered per purpose |
| Notice precedes consent (s.5) | the grant must carry the hash of the notice the person saw; a stale or missing hash is refused (409) and logged |
| Withdraw as easily as agree (s.6(4)) | same screen, one click, no reason; always accepted |
| Earlier processing stays lawful (s.6(5)) | append-only ledger: earlier ALLOW entries stay visible after withdrawal |
| Stop processing; tell processors (s.6(6)) | next request refused immediately; organizations that received data get a withdrawal notice to acknowledge |
| Fiduciary can prove notice and consent (s.6(10)) | ledger entries carry the notice hash; hash-chained, verifiable, exportable |

## Architecture to code
| Component | File |
|---|---|
| Consent UI (React) | `frontend/src` (API client generated from `/openapi.json` by `npm run gen:api`) |
| Consent Service | `app/consent_service.py` |
| Audit Service (read-only) | `app/audit_service.py`; standalone verifier `scripts/verify_audit.py` |
| Policy Enforcement Point | `app/pep.py` |
| Mock Data-Sharing API (internal, token-gated, no route) | `app/mock_api.py` |
| Storage Gateway (the single write path; one transaction) | `app/gateway.py` |
| D1 Ledger / D2 Notices / D3 Requester Registry / D4 Synthetic Data | SQLite tables `ledger`, `notices`, `requesters`, `users` |
| HTTP layer | `app/main.py` |
| Decision pseudocode | `docs/pseudocode.md` |

## Tests
`tests/test_consent.py` holds exactly 28 tests, numbered as in the proposal. Extra assertions that harden a behaviour
(revocation notices, key hashing, security headers, the optional password, per-purpose fields) are folded into the
tests that already cover it.

## Security
| Area | What is in place |
|---|---|
| Secrets | API keys are stored only as SHA-256 hashes (they are long random values). Keys, the console password and the internal token come from environment variables, never from the repository. `.env` is git-ignored. The app refuses to start on Render with the built-in local keys. |
| Console access | Optional HTTP Basic password (generated on Render), with lockout after repeated failures. Console writes from another website are refused (Origin / Sec-Fetch-Site check). There is no sign-in per person: anyone who passes the console password can act as any person. |
| Partner API | Organization API key on every call, wrong keys throttled, bodies over 64 KB refused, unauthenticated refusals are never attributed to a person. |
| Data | SQLite file readable by its owner only; append-only ledger enforced by triggers and a hash chain; each purpose returns only its own fields. |
| Transport | HTTPS is provided by Render. The app trusts `X-Forwarded-Proto`, sends HSTS, CSP, nosniff and anti-framing headers, and loads nothing from third-party sites. |
| Errors | Debug is off. Unexpected errors return a generic message; reason codes never include internal detail. |
| Dependencies | `pip-audit` and `npm audit` report no known vulnerabilities at build time; Python 3.12 and Node 22 base images. |

## Notes and limits
- Out of scope: real user authentication, erasure/retention of data held by organizations, recall of data already shared.
- The ledger blocks UPDATE/DELETE with triggers. Someone with raw access to the database file can drop the triggers; the
  hash chain then detects edits, deletions, reordering and forged entries, and an exported head hash detects truncation or
  a full rewrite.
- Wrong API keys are throttled (20 per minute, counted globally because a client address cannot be trusted behind a proxy;
  throttled requests are not logged, and valid keys still work), and wrong console passwords are throttled (10 per 5 minutes,
  so an attacker could briefly lock the owner out). Before any real use, add per-client limits and real sign-in.
- Anyone who has the console password can act as any person or organization: there are no per-person accounts.
- Report latency only from `scripts/bench_pep.py` run on your own deployment.

## Security checklist
| Check | Status |
|---|---|
| API keys hidden | Stored only as SHA-256 hashes (keys are long random values). The browser never receives keys. Render generates them; the app refuses to start on Render with the built-in local keys. |
| Secrets kept off GitHub | `.env`, databases and logs are git-ignored. The repo holds only local-development defaults; Render secrets live in the dashboard. Keep the repository private. |
| Admin page locked | Set by default on Render (`CONSOLE_PASSWORD`), throttled against guessing. Off locally unless you set it. |
| People see only their own data | Not implemented: the console has no per-person accounts (out of scope). Organizations calling the API see only their own requests and only the fields a purpose allows. |
| HTTPS | Render serves HTTPS and redirects HTTP; the app sends HSTS, and loads nothing from third parties. |
| Passwords hashed | There are no user passwords. The console password is a deployment secret compared in constant time. |
| Database locked | File readable by its owner only; ledger and notices are append-only by trigger; not served by any route. |
| Debug off / errors hidden | No debug mode or reload; unexpected errors return a generic message, and the enforcement point returns only a reason code. |
| Unused code removed | Checked with a dead-code scan. |
| Packages current | `pip-audit` and `npm audit` report no known vulnerabilities (build tools updated). |
Also checked: no SQL injection (all queries parameterized), no script injection (React text rendering, strict CSP),
cross-site request refusal on console writes, request size cap, and static-file path traversal.
