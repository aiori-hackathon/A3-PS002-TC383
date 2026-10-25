"""
Scripted demonstration:
  grant -> data sharing -> withdrawal -> denied request -> notice change -> re-consent

Start the server first:   uvicorn app.main:app --port 8000
Then run:                 python demo.py
"""
import sys
import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
KEY = {"analytics-co": "key-analytics-001"}
c = httpx.Client(base_url=BASE, timeout=10)


def step(title):
    print(f"\n=== {title} ===")


def show(label, r):
    print(f"{label:<44} -> HTTP {r.status_code}  {r.json()}")


def ask():
    return c.post("/api/share/request",
                  json={"consumer_id": "analytics-co", "user_id": "u001", "purpose": "analytics"},
                  headers={"X-API-Key": KEY["analytics-co"]})


c.post("/api/reset")

step("1. No consent yet: request must be denied")
show("analytics-co asks for u001 data", ask())

step("2. User u001 grants consent for 'analytics' (notice v1)")
show("grant", c.post("/api/consent/grant", json={"user_id": "u001", "purpose": "analytics"}))

step("3. Data sharing now allowed (only the purpose's fields are returned)")
show("analytics-co asks for u001 data", ask())

step("4. User withdraws consent")
show("withdraw", c.post("/api/consent/withdraw", json={"user_id": "u001", "purpose": "analytics"}))

step("5. Very next request is denied")
show("analytics-co asks for u001 data", ask())

step("6. User re-grants, then the service publishes notice v2")
show("grant", c.post("/api/consent/grant", json={"user_id": "u001", "purpose": "analytics"}))
show("publish notice v2", c.post("/api/notices", json={
    "purpose": "analytics", "text": "FitLife notice v2: analytics data now retained for 24 months."}))

step("7. Old consent is stale -> denied until user re-consents")
show("analytics-co asks for u001 data", ask())

step("8. User re-consents to v2 -> allowed again")
show("grant", c.post("/api/consent/grant", json={"user_id": "u001", "purpose": "analytics"}))
show("analytics-co asks for u001 data", ask())

step("9. Audit integrity")
print(c.get("/api/audit/verify").json())
print("\nExport the evidence:  GET /api/audit/export?format=csv")