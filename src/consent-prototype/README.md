# Consent Prototype (AIORI Hackathon 3, PS-002)

A prototype for purpose-based consent recording and withdrawal for a synthetic service. A mock data-sharing API checks consent on **every** request, and an audit log can be verified and exported.

Only synthetic data is used. The prototype records technical consent evidence; it is not a legal certification of DPDP Act compliance.

## Live demo

- **Deployed prototype:** https://a3-ps002-tc383.onrender.com/
- **Demo video:** https://www.youtube.com/watch?v=muiP8mVSKcc

The web console has no sign-in. The server acts for the person or organization selected in the interface.

The prototype runs on Render's free plan, so the service may take a short while to wake up on the first visit. The database, including the ledger, resets whenever the service restarts or redeploys.

## Run locally

With Docker:

```
docker compose up --build
```

Open http://localhost:8000 (API docs: http://localhost:8000/docs).

```
docker compose --profile tools run --rm tests     # the 28 lifecycle tests
docker compose --profile tools run --rm demo      # scripted grant -> share -> withdraw -> refused -> notice change
docker compose run --rm --no-deps api python -m scripts.bench_pep   # PEP latency with and without the check
docker compose down -v                            # reset: deletes the database volume for a clean start
```

Without Docker:

```
pip install -r requirements.txt
cd frontend && npm install && npm run build
```

Copy `frontend/dist` to `app/static`, then start the server:

```
uvicorn app.main:create_app --factory --port 8000
```

## How people and organizations use it

- **The web console** is the service's own interface. It has no sign-in: the server acts for the person or organization you pick. Real user authentication is out of scope.
- **A partner system** calls the API with its own organization key:
  ```
  curl -X POST https://<host>/api/share -H "X-API-Key: <key>" -H "Content-Type: application/json" \
       -d '{"user_pid":"u001","purpose":"analytics"}'
  ```
  `GET /api/requester/revocations` (same header) lists withdrawal notices; `POST /api/requester/revocations/{n}/ack` acknowledges one.
- The console sends requests for the seeded organizations through the **same** enforcement point and key check.

## Which consent this resolves

Consent as the lawful ground under **DPDP Act 2023 s.4(1)(a), read with s.6**: specific to a purpose, preceded by a notice (s.5), and withdrawable with comparable ease (s.6(4)).

Not covered: s.7 legitimate uses, children's consent (s.9), Consent Manager registration (s.6(7)-(9)), and erasure of data already shared.

| Requirement | Where it shows in the prototype |
|---|---|
| Specific, per-purpose consent (s.6(1)) | One agreement per purpose; data fields listed on each card; each organization registered per purpose |
| Notice precedes consent (s.5) | The grant must carry the hash of the notice the person saw; a stale or missing hash is refused (409) and logged |
| Withdraw as easily as agree (s.6(4)) | Same screen, one click, no reason; always accepted |
| Earlier processing stays lawful (s.6(5)) | Append-only ledger: earlier ALLOW entries stay visible after withdrawal |
| Stop processing; tell processors (s.6(6)) | The next request is refused immediately; organizations that received data get a withdrawal notice to acknowledge |
| Fiduciary can prove notice and consent (s.6(10)) | Ledger entries carry the notice hash; hash-chained, verifiable, exportable |

## Architecture

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

`tests/test_consent.py` holds exactly 28 tests, numbered as in the proposal. Extra assertions that harden a behaviour (revocation notices, key hashing, security headers, per-purpose fields) are folded into the tests that already cover it.

## Notes and limits

- Out of scope: real user authentication, erasure or retention of data held by organizations, and recall of data already shared.
- There are no per-person accounts, so anyone who can reach the console can act as any person or organization.
- The ledger blocks UPDATE and DELETE with triggers. Someone with raw access to the database file could drop the triggers; the hash chain then detects edits, deletions, reordering and forged entries, and an exported head hash detects truncation or a full rewrite.
- Wrong API keys are throttled at 20 per minute, counted globally because a client address cannot be trusted behind a proxy. Throttled requests are not logged, and valid keys still work. Before any real use, add per-client limits and real sign-in.
