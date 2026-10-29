// AUTO-GENERATED from the FastAPI OpenAPI spec by scripts/gen-api.mjs - do not edit.
export const operations = {
  "health": {
    "method": "GET",
    "path": "/api/health",
    "summary": "Health"
  },
  "purposes": {
    "method": "GET",
    "path": "/api/purposes",
    "summary": "Purposes"
  },
  "share_request": {
    "method": "POST",
    "path": "/api/share",
    "summary": "Share"
  },
  "requester_me": {
    "method": "GET",
    "path": "/api/requester/me",
    "summary": "Requester Me"
  },
  "requester_feed": {
    "method": "GET",
    "path": "/api/requester/feed",
    "summary": "Requester Feed"
  },
  "requester_revocations": {
    "method": "GET",
    "path": "/api/requester/revocations",
    "summary": "Requester Revocations"
  },
  "requester_ack": {
    "method": "POST",
    "path": "/api/requester/revocations/{withdraw_seq}/ack",
    "summary": "Requester Ack"
  },
  "console_state": {
    "method": "GET",
    "path": "/api/console/state",
    "summary": "Console State"
  },
  "console_consents": {
    "method": "GET",
    "path": "/api/console/people/{user_pid}/consents",
    "summary": "Console Consents"
  },
  "console_timeline": {
    "method": "GET",
    "path": "/api/console/people/{user_pid}/timeline",
    "summary": "Console Timeline"
  },
  "console_grant": {
    "method": "POST",
    "path": "/api/console/people/{user_pid}/grant",
    "summary": "Console Grant"
  },
  "console_withdraw": {
    "method": "POST",
    "path": "/api/console/people/{user_pid}/withdraw",
    "summary": "Console Withdraw"
  },
  "console_request": {
    "method": "POST",
    "path": "/api/console/requests",
    "summary": "Console Request"
  },
  "console_revocations": {
    "method": "GET",
    "path": "/api/console/requesters/{requester_id}/revocations",
    "summary": "Console Revocations"
  },
  "console_ack": {
    "method": "POST",
    "path": "/api/console/requesters/{requester_id}/revocations/{withdraw_seq}/ack",
    "summary": "Console Ack"
  },
  "console_publish": {
    "method": "POST",
    "path": "/api/console/notices",
    "summary": "Console Publish"
  },
  "console_ledger": {
    "method": "GET",
    "path": "/api/console/ledger",
    "summary": "Console Ledger"
  },
  "console_verify": {
    "method": "GET",
    "path": "/api/console/verify",
    "summary": "Console Verify"
  },
  "console_export": {
    "method": "GET",
    "path": "/api/console/export",
    "summary": "Console Export"
  }
}
