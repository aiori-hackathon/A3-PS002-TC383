"""The 28 lifecycle tests promised in the proposal (Evaluation Plan slide). Run: pytest -v
Each test keeps its number from the proposal; extra assertions that harden a behaviour are folded into the
test that already covers it, so the suite stays at exactly 28."""
import base64
import inspect
import json
import os
import random
import sqlite3
import stat
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.audit_service as audit_module
import app.consent_service as consent_module
from app.config import load_settings
from app.hashing import GENESIS, entry_hash
from app.main import create_app
from tests.helpers import (KEYS, add_purpose_without_notice, current_hash, drop_triggers, events, grant,
                           ledger, publish, raw_db, share, status_of, verify, withdraw)

ROOT = Path(__file__).resolve().parents[1]
PARTNER = lambda k: {"X-API-Key": KEYS[k]}


# ------------------------------------------------------------ Enforcement (1-12)
def test_01_grant_then_share_is_allowed(client):
    g = grant(client, "u001", "analytics")
    assert g.status_code == 200 and g.json()["notice_version"] == 1 and len(g.json()["notice_hash"]) == 64
    r = share(client, "analytics-co", "u001", "analytics")
    assert r.status_code == 200 and r.json()["reason"] == "CONSENT_VALID"
    assert set(r.json()["data"]) == {"age_band", "steps_per_day"}  # data minimisation
    grant(client, "u001", "marketing"); grant(client, "u001", "research_sharing")   # each purpose: only its own fields
    assert set(share(client, "mailer-co", "u001", "marketing").json()["data"]) == {"name", "email"}
    assert set(share(client, "research-lab", "u001", "research_sharing").json()["data"]) == {
        "age_band", "avg_heart_rate", "sleep_hours"}


def test_02_never_consented_is_denied_NO_CONSENT(client):
    r = share(client, "analytics-co", "u001", "analytics")
    assert r.status_code == 403 and r.json()["reason"] == "NO_CONSENT" and r.json()["allowed"] is False


def test_03_unknown_user_gets_identical_NO_CONSENT(client):
    a = share(client, "analytics-co", "u001", "analytics").json()
    b = share(client, "analytics-co", "u999", "analytics")
    assert b.status_code == 403 and b.json()["reason"] == a["reason"] == "NO_CONSENT"
    assert set(b.json()) == set(a)  # same shape: no way to tell the user does not exist


def test_04_withdraw_denies_next_request_immediately(client):
    grant(client, "u001", "analytics")
    assert share(client, "analytics-co", "u001", "analytics").status_code == 200
    assert withdraw(client, "u001", "analytics").status_code == 200
    r = share(client, "analytics-co", "u001", "analytics")
    assert r.status_code == 403 and r.json()["reason"] == "CONSENT_WITHDRAWN"
    # the organization that RECEIVED data is told to stop; one that never received data is not
    rev = client.get("/api/requester/revocations", headers=PARTNER("analytics-co")).json()
    assert len(rev) == 1 and rev[0]["user_pid"] == "u001" and rev[0]["acknowledged"] is False
    assert client.get("/api/requester/revocations", headers=PARTNER("mailer-co")).json() == []
    seq = rev[0]["withdraw_seq"]
    assert client.post(f"/api/requester/revocations/{seq}/ack", headers=PARTNER("mailer-co")).status_code == 404
    assert client.post(f"/api/console/requesters/analytics-co/revocations/{seq}/ack").status_code == 200
    assert client.get("/api/console/requesters/analytics-co/revocations").json()[0]["acknowledged"] is True


def test_05_regrant_after_withdrawal_allows_again(client):
    grant(client, "u001", "marketing"); withdraw(client, "u001", "marketing"); grant(client, "u001", "marketing")
    assert share(client, "mailer-co", "u001", "marketing").status_code == 200


def test_06_consent_for_purpose_A_cannot_be_used_for_purpose_B(client):
    grant(client, "u001", "analytics")
    assert share(client, "research-lab", "u001", "analytics").status_code == 200  # legitimate use
    r = share(client, "research-lab", "u001", "research_sharing")  # same requester, other purpose
    assert r.status_code == 403 and r.json()["reason"] == "NO_CONSENT"


def test_07_unknown_requester_or_bad_key_is_REQ_AUTH(app, client, tmp_path, monkeypatch):
    grant(client, "u001", "analytics")
    assert share(client, "analytics-co", "u001", "analytics", key="wrong").json()["reason"] == "REQ_AUTH"
    r = client.post("/api/share", json={"user_pid": "u001", "purpose": "analytics"})  # no key at all
    assert r.status_code == 403 and r.json()["reason"] == "REQ_AUTH"
    # keys are stored only as hashes, and no endpoint hands out keys, tokens or a reset
    for row in raw_db(app).execute("SELECT key_hash FROM requesters").fetchall():
        assert len(row["key_hash"]) == 64 and not row["key_hash"].startswith("key-")
    for path in ("/api/state", "/api/reset", "/api/session", "/api/demo/enter"):
        assert client.get(path).status_code in (404, 405) and client.post(path).status_code in (404, 405)
    assert "key-" not in client.get("/api/console/state").text
    # optional console password: protects the console and page, never health checks or the partner API
    s = load_settings(str(tmp_path / "pw.db")); s.console_password = "s3cret"; s.log_dir = str(tmp_path / "pwlogs")
    c2 = TestClient(create_app(settings=s))
    basic = lambda p: {"Authorization": "Basic " + base64.b64encode(f"u:{p}".encode()).decode()}
    assert c2.get("/api/console/state").status_code == 401 and c2.get("/").status_code in (401, 200)
    assert c2.get("/api/console/state", headers=basic("wrong")).status_code == 401
    assert c2.get("/api/console/state", headers=basic("s3cret")).status_code == 200
    assert c2.get("/api/health").status_code == 200
    assert c2.post("/api/share", json={"user_pid": "u001", "purpose": "analytics"}).json()["reason"] == "REQ_AUTH"
    # brute force: repeated wrong console passwords are throttled (429), even for the right password while locked
    codes = [c2.get("/api/console/state", headers=basic(f"guess{i}")).status_code for i in range(12)]
    assert 401 in codes and 429 in codes and c2.get("/api/console/state", headers=basic("s3cret")).status_code == 429
    assert c2.get("/api/health").status_code == 200       # health checks and the partner API are never locked out
    # brute force on API keys: wrong keys are throttled and stop writing to the ledger; a valid key still works
    s4 = load_settings(str(tmp_path / "bf.db")); s4.log_dir = str(tmp_path / "bf")
    c4 = TestClient(create_app(settings=s4))
    codes = [c4.post("/api/share", json={"user_pid": "u001", "purpose": "analytics"}, headers={"X-API-Key": f"bad{i}"}).status_code
             for i in range(30)]
    assert 429 in codes and codes.count(403) <= 20
    assert sum(e["event"] == "DENY" and e["reason"] == "REQ_AUTH" for e in ledger(c4)) <= 20
    grant(c4, "u001", "analytics")
    assert share(c4, "analytics-co", "u001", "analytics").status_code == 200
    # CSRF defence in depth: console writes from another site are refused, same-site writes work
    body = {"purpose": "analytics", "text": "t"}
    r = client.post("/api/console/notices", json=body, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"] == "CROSS_SITE"
    assert client.post("/api/console/people/u001/withdraw", json={"purpose": "analytics"},
                       headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post("/api/console/notices", json=body, headers={"Origin": "http://testserver"}).status_code == 200
    # key rotation: a key changed in the environment takes effect on restart, and the old key stops working
    s5 = load_settings(app.state.settings.db_path); s5.log_dir = str(tmp_path / "rot")
    s5.requester_keys = {**s5.requester_keys, "analytics-co": "rotated-key-0123456789"}
    c5 = TestClient(create_app(settings=s5)); grant(c5, "u002", "analytics")
    assert share(c5, "analytics-co", "u002", "analytics", key="rotated-key-0123456789").status_code == 200
    assert share(c5, "analytics-co", "u002", "analytics").json()["reason"] == "REQ_AUTH"
    # never start on Render with the built-in local keys
    monkeypatch.setenv("RENDER", "true")
    with pytest.raises(RuntimeError, match="built-in local API keys"):
        create_app(settings=load_settings(str(tmp_path / "render.db")))


def test_08_requester_not_authorised_for_purpose_is_REQ_PURPOSE(client):
    grant(client, "u001", "analytics")
    r = share(client, "mailer-co", "u001", "analytics")  # mailer-co is registered for marketing only
    assert r.status_code == 403 and r.json()["reason"] == "REQ_PURPOSE"


def test_09_malformed_request_is_403_ERROR(client):
    h = {"X-API-Key": KEYS["analytics-co"], "Content-Type": "application/json"}
    for payload in ("not json at all", json.dumps({"purpose": "analytics"}), json.dumps([1, 2]),
                    json.dumps({"user_pid": 5, "purpose": ["x"]}), "{" * 5000):
        r = client.post("/api/share", content=payload, headers=h)
        assert r.status_code == 403 and r.json()["reason"] == "ERROR" and "data" not in r.json()
    # HTTPS-ready hardening: security headers always, HSTS when the host's proxy says the request was HTTPS
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert "no-store" in r.headers["cache-control"] and "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "strict-transport-security" not in r.headers
    assert "max-age" in client.get("/api/health", headers={"X-Forwarded-Proto": "https"}).headers["strict-transport-security"]
    big = client.post("/api/share", content="A" * 70_000, headers=h)     # oversized bodies are refused outright
    assert big.status_code == 413 and "data" not in big.json()
    assert client.get("/openapi.json").status_code == 200                # docs on by default (local)
    s = load_settings(str(client.app.state.settings.db_path) + ".nodocs"); s.enable_docs = False
    c_nodocs = TestClient(create_app(settings=s))                        # ...and off on a deployment (render.yaml)
    assert c_nodocs.get("/docs").status_code == 404 and c_nodocs.get("/openapi.json").status_code == 404


def test_10_purpose_with_no_published_notice_is_NO_NOTICE(app, client):
    add_purpose_without_notice(app)
    r = share(client, "analytics-co", "u001", "telemetry")
    assert r.status_code == 403 and r.json()["reason"] == "NO_NOTICE"


def test_11_notice_change_denies_until_regrant(client):
    grant(client, "u001", "analytics"); grant(client, "u002", "marketing")
    assert share(client, "analytics-co", "u001", "analytics").status_code == 200
    assert publish(client, "analytics").json()["version"] == 2
    r = share(client, "analytics-co", "u001", "analytics")
    assert r.status_code == 403 and r.json()["reason"] == "NOTICE_STALE"
    assert grant(client, "u001", "analytics").json()["notice_version"] == 2
    assert share(client, "analytics-co", "u001", "analytics").status_code == 200
    # a person's timeline shows only their own entries, plus a server-reported integrity check
    t = client.get("/api/console/people/u001/timeline").json()
    assert {e["user_pid"] for e in t["entries"] if e["event"] != "NOTICE_PUBLISHED"} == {"u001"}
    assert t["server_check"]["chain_valid"] is True


def test_12_notice_change_on_another_purpose_leaves_others_valid(client):
    grant(client, "u001", "analytics"); grant(client, "u001", "marketing")
    publish(client, "analytics")
    assert share(client, "analytics-co", "u001", "analytics").json()["reason"] == "NOTICE_STALE"
    assert share(client, "mailer-co", "u001", "marketing").status_code == 200


# -------------------------------------------------- Grant and withdraw rules (13-18)
def test_13_stale_hash_grant_is_409_and_logged_GRANT_REJECTED(client):
    old = current_hash(client, "analytics")
    publish(client, "analytics")
    r = grant(client, "u001", "analytics", hash_=old)
    assert r.status_code == 409 and r.json()["error"] == "NOTICE_HASH_MISMATCH"
    assert "GRANT_REJECTED" in events(client) and "GRANT" not in events(client)


def test_14_rejected_grant_leaves_consent_state_unchanged(client):
    grant(client, "u001", "analytics"); withdraw(client, "u001", "analytics")
    old = current_hash(client, "analytics")
    publish(client, "analytics")
    assert grant(client, "u001", "analytics", hash_=old).status_code == 409
    assert status_of(client, "u001")["analytics"] == "withdrawn"
    assert share(client, "analytics-co", "u001", "analytics").json()["reason"] == "CONSENT_WITHDRAWN"


def test_15_grant_with_no_published_notice_is_rejected(app, client):
    add_purpose_without_notice(app)
    r = grant(client, "u001", "telemetry", hash_="abc")
    assert r.status_code == 409 and r.json()["error"] == "NO_NOTICE"
    assert any(e["event"] == "GRANT_REJECTED" and e["reason"] == "NO_NOTICE" for e in ledger(client))


def test_16_withdraw_with_stale_hash_succeeds(client):
    grant(client, "u001", "analytics"); old = current_hash(client, "analytics"); publish(client, "analytics")
    r = withdraw(client, "u001", "analytics", notice_hash=old)
    assert r.status_code == 200 and r.json()["was_active"] is True
    assert share(client, "analytics-co", "u001", "analytics").json()["reason"] == "CONSENT_WITHDRAWN"


def test_17_withdraw_with_missing_hash_succeeds(client):
    grant(client, "u001", "analytics")
    assert withdraw(client, "u001", "analytics").status_code == 200  # body has only the purpose


def test_18_withdraw_without_active_consent_succeeds_and_is_idempotent(client):
    for _ in range(2):
        r = withdraw(client, "u001", "analytics")
        assert r.status_code == 200 and r.json()["was_active"] is False
    assert events(client).count("WITHDRAW") == 2
    assert share(client, "analytics-co", "u001", "analytics").json()["reason"] == "CONSENT_WITHDRAWN"


# ---------------------------------------------------------------- Audit (19-25)
def test_19_history_preserved_and_UPDATE_DELETE_blocked(app, client):
    grant(client, "u001", "analytics"); withdraw(client, "u001", "analytics")
    ev = events(client)
    assert "GRANT" in ev and "WITHDRAW" in ev  # the grant was not overwritten by the withdrawal
    conn = raw_db(app)
    for sql in ("UPDATE ledger SET reason='x'", "DELETE FROM ledger",
                "UPDATE notices SET text='x'", "DELETE FROM notices"):
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(sql)
    assert len(ledger(client)) == len(ev)
    assert stat.S_IMODE(os.stat(app.state.settings.db_path).st_mode) & 0o077 == 0   # database readable by its owner only
    # architecture fidelity: Audit Service is read-only; notices are written only via the Storage Gateway
    assert "INSERT" not in inspect.getsource(audit_module) and "INSERT INTO notices" not in inspect.getsource(consent_module)


def test_20_chain_verifies_when_intact(client):
    grant(client, "u001", "analytics"); share(client, "analytics-co", "u001", "analytics")
    withdraw(client, "u001", "analytics"); share(client, "analytics-co", "u001", "analytics")
    v = verify(client)
    assert v["valid"] is True and v["entries"] == 7  # 3 seeded notices + grant, allow, withdraw, deny
    exp = client.get("/api/console/export?format=json")
    assert exp.headers["x-ledger-head-hash"] == v["head_hash"] == exp.json()["head_hash"]


def test_21_edit_is_detected(app, client):
    grant(client, "u001", "analytics"); withdraw(client, "u001", "analytics")
    target = next(e for e in ledger(client) if e["event"] == "WITHDRAW")["seq"]
    drop_triggers(app).execute("UPDATE ledger SET event='GRANT' WHERE seq=?", (target,))
    v = verify(client)
    assert v["valid"] is False and v["first_bad_seq"] == target


def test_22_delete_is_detected(app, client):
    grant(client, "u001", "analytics"); share(client, "analytics-co", "u001", "analytics")
    withdraw(client, "u001", "analytics")
    mid = next(e for e in ledger(client) if e["event"] == "ALLOW")["seq"]
    drop_triggers(app).execute("DELETE FROM ledger WHERE seq=?", (mid,))
    v = verify(client)
    assert v["valid"] is False and v["first_bad_seq"] == mid + 1


def test_23_reorder_and_forged_insert_are_detected(app, client, tmp_path):
    grant(client, "u001", "analytics"); withdraw(client, "u001", "analytics")
    rows = {e["event"]: e for e in ledger(client) if e["event"] in ("GRANT", "WITHDRAW")}
    conn = drop_triggers(app)  # swap the two entries' contents = reorder history
    conn.execute("UPDATE ledger SET event='WITHDRAW' WHERE seq=?", (rows["GRANT"]["seq"],))
    conn.execute("UPDATE ledger SET event='GRANT' WHERE seq=?", (rows["WITHDRAW"]["seq"],))
    v = verify(client)
    assert v["valid"] is False and v["first_bad_seq"] == rows["GRANT"]["seq"]
    # a forged entry appended with a made-up hash is detected too
    s = load_settings(str(tmp_path / "ins.db")); s.log_dir = str(tmp_path / "l2")
    app2 = create_app(settings=s); c2 = TestClient(app2); grant(c2, "u001", "analytics")
    head = ledger(c2)[-1]
    drop_triggers(app2).execute(
        "INSERT INTO ledger(seq,ts,event,user_pid,purpose,notice_hash,actor,reason,detail,prev_hash,entry_hash) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (head["seq"] + 1, "2026-01-01T00:00:00.000+00:00", "GRANT", "u003",
        "analytics", head["notice_hash"], "user:u003", "FORGED", None, head["entry_hash"], "0" * 63 + "1"))
    v2 = verify(c2)
    assert v2["valid"] is False and v2["first_bad_seq"] == head["seq"] + 1


def test_24_truncation_and_full_rewrite_are_detected_against_exported_head(app, client):
    grant(client, "u001", "analytics"); share(client, "analytics-co", "u001", "analytics")
    withdraw(client, "u001", "analytics")
    head = client.get("/api/console/export?format=json").headers["x-ledger-head-hash"]
    conn = drop_triggers(app)
    # (a) full rewrite: an attacker edits an entry and recomputes EVERY hash after it
    prev = GENESIS
    for r in [dict(x) for x in conn.execute("SELECT * FROM ledger ORDER BY seq")]:
        if r["event"] == "WITHDRAW":
            r["event"] = "GRANT"
        h = entry_hash(prev, r)
        conn.execute("UPDATE ledger SET event=?, prev_hash=?, entry_hash=? WHERE seq=?", (r["event"], prev, h, r["seq"]))
        prev = h
    assert verify(client)["valid"] is True  # the chain alone cannot see a consistent rewrite
    v = verify(client, expected_head=head)
    assert v["valid"] is False and "truncated or rewritten" in v["reason"]
    # (b) truncation: cut off the newest entries
    n = len(ledger(client))
    conn.execute("DELETE FROM ledger WHERE seq > ?", (n - 2,))
    assert verify(client)["valid"] is True
    assert verify(client, expected_head=head)["valid"] is False


def test_25_standalone_verifier_checks_an_export_file(client, tmp_path):
    grant(client, "u001", "analytics"); share(client, "analytics-co", "u001", "analytics")
    f = tmp_path / "export.json"
    f.write_text(client.get("/api/console/export?format=json").text, encoding="utf-8")
    run = lambda *a: subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_audit.py"), str(f), *a],
                                    capture_output=True, text=True, cwd=ROOT)
    assert run().returncode == 0
    data = json.loads(f.read_text(encoding="utf-8"))
    data["entries"][2]["event"] = "WITHDRAW"
    f.write_text(json.dumps(data), encoding="utf-8")
    bad = run()
    assert bad.returncode == 1 and "FAIL" in bad.stdout


# ------------------------------------------------------------- Robustness (26-28)
def test_26_db_fault_fails_closed_with_403_ERROR_and_no_data(app, client, monkeypatch):
    grant(client, "u001", "analytics")

    def boom(conn):
        raise RuntimeError("injected fault after consent check")
    app.state.pep.fault_hook = boom
    r = share(client, "analytics-co", "u001", "analytics")
    assert r.status_code == 403 and r.json()["reason"] == "ERROR" and "data" not in r.json()
    assert not any(e["event"] == "ALLOW" for e in ledger(client))     # rolled back: no ALLOW
    assert any(e["event"] == "DENY" and e["reason"] == "ERROR" for e in ledger(client))  # best-effort DENY
    app.state.pep.fault_hook = None

    def dead(*a, **k):
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(app.state.gateway, "transaction", dead)        # the ledger itself is down
    r2 = share(client, "analytics-co", "u001", "analytics")
    assert r2.status_code == 403 and r2.json()["reason"] == "ERROR" and "data" not in r2.json()
    assert (Path(app.state.settings.log_dir) / "errors.log").read_text().count("ERROR") >= 1
    monkeypatch.undo()
    # the Mock Data-Sharing API is internal: wrong token refused, and no HTTP route reaches it
    with app.state.gateway.read() as conn:
        with pytest.raises(PermissionError):
            app.state.mock.get_records(conn, "u001", "analytics", "wrong-token")
    assert not [r_.path for r_ in app.routes if "mock" in getattr(r_, "path", "").lower()]


def test_27_concurrent_requests_never_allow_after_withdrawal_commits(app, client):
    pep, consent = app.state.pep, app.state.consent
    users = ["u001", "u002", "u003"]
    for u in users:                                   # three rounds, with jitter so threads really interleave
        grant(client, u, "analytics")
        start = threading.Barrier(25)

        def req(_, u=u):
            start.wait(); time.sleep(random.random() * 0.01)
            return pep.share(KEYS["analytics-co"], {"user_pid": u, "purpose": "analytics"})

        def wd(u=u):
            start.wait(); time.sleep(random.random() * 0.005)
            return consent.withdraw(u, "analytics")
        with ThreadPoolExecutor(max_workers=25) as ex:
            futs = [ex.submit(req, i) for i in range(24)] + [ex.submit(wd)]
            for f in futs:
                f.result()
    led = ledger(client)
    for u in users:
        w = next(e["seq"] for e in led if e["event"] == "WITHDRAW" and e["user_pid"] == u)
        mine = [e for e in led if e["user_pid"] == u and e["event"] in ("ALLOW", "DENY")]
        assert len(mine) == 24                                              # every request logged exactly once
        assert not [e for e in mine if e["event"] == "ALLOW" and e["seq"] > w]   # never allowed after withdrawal
        assert all(e["reason"] == "CONSENT_WITHDRAWN" for e in mine if e["event"] == "DENY" and e["seq"] > w)
    assert verify(client)["valid"] is True


def test_28_every_outcome_is_logged(client):
    grant(client, "u001", "analytics")
    h = {"X-API-Key": KEYS["analytics-co"], "Content-Type": "application/json"}
    before = sum(e["event"] in ("ALLOW", "DENY") for e in ledger(client))
    share(client, "analytics-co", "u001", "analytics")                       # ALLOW
    share(client, "analytics-co", "u002", "analytics")                       # NO_CONSENT
    share(client, "mailer-co", "u001", "analytics")                          # REQ_PURPOSE
    share(client, "analytics-co", "u001", "analytics", key="bad")            # REQ_AUTH
    client.post("/api/share", content="{", headers=h)                        # ERROR (malformed)
    withdraw(client, "u001", "analytics")
    share(client, "analytics-co", "u001", "analytics")                       # CONSENT_WITHDRAWN
    publish(client, "analytics")
    share(client, "analytics-co", "u001", "analytics")                       # CONSENT_WITHDRAWN again
    after = [e for e in ledger(client) if e["event"] in ("ALLOW", "DENY")]
    assert len(after) - before == 7
    auth_entry = next(e for e in after if e["reason"] == "REQ_AUTH")
    assert auth_entry["user_pid"] is None and auth_entry["purpose"] is None   # nobody can write into a person's log
    assert sorted(e["reason"] for e in after[-7:]) == sorted(
        ["CONSENT_VALID", "NO_CONSENT", "REQ_PURPOSE", "REQ_AUTH", "ERROR", "CONSENT_WITHDRAWN", "CONSENT_WITHDRAWN"])
