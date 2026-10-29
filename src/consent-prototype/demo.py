"""
Scripted walkthrough on the running system:
  grant -> data sharing -> withdrawal -> refused request -> notice change -> re-consent -> verify

Start the server first (docker compose up --build), then:
    python demo.py                              # http://127.0.0.1:8000
    python demo.py https://your-app.onrender.com
Organization key: environment variable KEY_ANALYTICS_CO (default: the local key).
If the console is password-protected: set CONSOLE_PASSWORD too.
For a clean run start from a fresh database (README: reset).
"""
import os
import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
ORG_KEY = os.environ.get("KEY_ANALYTICS_CO", "key-analytics-001")
PW = os.environ.get("CONSOLE_PASSWORD", "")
c = httpx.Client(base_url=BASE, timeout=15, auth=("console", PW) if PW else None)
PERSON = "/api/console/people/u001"


def step(title):
    print(f"\n=== {title} ===")


def show(label, r):
    print(f"{label:<44} -> HTTP {r.status_code}  {r.json()}")


def notice_hash(purpose="analytics"):
    return next(p["notice"]["hash"] for p in c.get("/api/purposes").json() if p["purpose"] == purpose)


def ask():  # a partner system calling the API with its own key
    return httpx.post(BASE + "/api/share", json={"user_pid": "u001", "purpose": "analytics"},
                      headers={"X-API-Key": ORG_KEY}, timeout=15)


def agree():
    return c.post(PERSON + "/grant", json={"purpose": "analytics", "notice_hash": notice_hash()})


step("1. Before consent: the organization's request must be refused")
show("analytics-co asks for u001's data", ask())
step("2. u001 reads the notice and agrees (the grant carries the notice hash she saw)")
show("grant", agree())
step("3. Data sharing is allowed - only this purpose's fields are returned")
show("analytics-co asks for u001's data", ask())
step("4. u001 withdraws consent (one action, always accepted)")
show("withdraw", c.post(PERSON + "/withdraw", json={"purpose": "analytics"}))
step("5. The very next request is refused; the organization receives a withdrawal notice")
show("analytics-co asks for u001's data", ask())
show("withdrawal notices", httpx.get(BASE + "/api/requester/revocations", headers={"X-API-Key": ORG_KEY}, timeout=15))
step("6. u001 agrees again, then a new notice v2 is published")
show("grant", agree())
show("publish notice v2", c.post("/api/console/notices", json={
    "purpose": "analytics", "text": "Notice v2. Data: age band, step count. Purpose: analytics. Now retained 24 months."}))
step("7. The old consent no longer covers the new notice -> refused")
show("analytics-co asks for u001's data", ask())
step("8. u001 agrees to notice v2 -> allowed again")
show("grant", agree())
show("analytics-co asks for u001's data", ask())
step("9. Audit: verify the hash chain")
print(c.get("/api/console/verify").json())
print("Export: GET /api/console/export?format=json|csv ; standalone check: python scripts/verify_audit.py export.json")
