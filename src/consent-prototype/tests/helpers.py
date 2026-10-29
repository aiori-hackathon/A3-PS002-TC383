import sqlite3

KEYS = {"analytics-co": "key-analytics-001", "mailer-co": "key-mailer-002", "research-lab": "key-research-003"}
CURRENT = object()


def current_hash(c, purpose):
    return next(p["notice"]["hash"] for p in c.get("/api/purposes").json() if p["purpose"] == purpose)


def grant(c, pid, purpose, hash_=CURRENT):
    body = {"purpose": purpose}
    if hash_ is CURRENT:
        body["notice_hash"] = current_hash(c, purpose)
    elif hash_ is not None:
        body["notice_hash"] = hash_
    return c.post(f"/api/console/people/{pid}/grant", json=body)


def withdraw(c, pid, purpose, **extra):
    return c.post(f"/api/console/people/{pid}/withdraw", json={"purpose": purpose, **extra})


def status_of(c, pid):
    return {x["purpose"]: x["status"] for x in c.get(f"/api/console/people/{pid}/consents").json()}


def share(c, requester, pid, purpose, key=None):
    """A partner system calling the API with its own key."""
    return c.post("/api/share", json={"user_pid": pid, "purpose": purpose},
                  headers={"X-API-Key": key if key is not None else KEYS.get(requester, "wrong")})


def publish(c, purpose, text="Updated notice text"):
    return c.post("/api/console/notices", json={"purpose": purpose, "text": text})


def ledger(c):
    return c.get("/api/console/ledger?limit=2000").json()


def events(c):
    return [e["event"] for e in ledger(c)]


def verify(c, expected_head=None):
    return c.get("/api/console/verify", params={"expected_head": expected_head} if expected_head else None).json()


def raw_db(app):
    conn = sqlite3.connect(app.state.settings.db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def drop_triggers(app):
    """Simulates an attacker with raw database-file access (the threat model's residual risk)."""
    conn = raw_db(app)
    for t in ("ledger_no_update", "ledger_no_delete"):
        conn.execute(f"DROP TRIGGER IF EXISTS {t}")
    return conn


def add_purpose_without_notice(app, name="telemetry"):
    conn = raw_db(app)
    conn.execute("INSERT INTO purposes VALUES(?,?,?,?)", (name, "test purpose", '["age_band"]', "test"))
    conn.execute("UPDATE requesters SET allowed_purposes='[\"analytics\",\"%s\"]' WHERE requester_id='analytics-co'" % name)
    conn.close()
