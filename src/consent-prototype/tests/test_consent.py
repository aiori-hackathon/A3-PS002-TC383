"""Lifecycle + enforcement tests (20 tests). Run: pytest -v"""
import csv
import io

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

KEYS = {"analytics-co": "key-analytics-001", "mailer-co": "key-mailer-002",
        "research-lab": "key-research-003"}


@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(str(tmp_path / "test.db")))


def grant(c, user, purpose, **extra):
    return c.post("/api/consent/grant", json={"user_id": user, "purpose": purpose, **extra})


def withdraw(c, user, purpose):
    return c.post("/api/consent/withdraw", json={"user_id": user, "purpose": purpose})


def request(c, consumer, user, purpose, key=None):
    return c.post("/api/share/request",
                  json={"consumer_id": consumer, "user_id": user, "purpose": purpose},
                  headers={"X-API-Key": key if key is not None else KEYS.get(consumer, "x")})


def events(c):
    return [e["event"] for e in c.get("/api/audit").json()]


# ---------------------------------------------------------------- lifecycle
def test_01_grant_records_purpose_notice_version_and_hash(client):
    r = grant(client, "u001", "analytics")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "granted" and body["notice_version"] == 1
    assert len(body["notice_hash"]) == 64


def test_02_granted_consent_allows_sharing_with_minimised_fields(client):
    grant(client, "u001", "analytics")
    r = request(client, "analytics-co", "u001", "analytics")
    assert r.status_code == 200
    assert set(r.json()["data"]) == {"age_band", "steps_per_day"}  # no email, no heart rate


def test_03_withdrawal_denies_next_request_immediately(client):
    grant(client, "u001", "analytics")
    assert request(client, "analytics-co", "u001", "analytics").status_code == 200
    assert withdraw(client, "u001", "analytics").status_code == 200
    r = request(client, "analytics-co", "u001", "analytics")
    assert r.status_code == 403 and r.json()["reason"] == "CONSENT_WITHDRAWN"


def test_04_regrant_after_withdrawal_restores_access(client):
    grant(client, "u001", "marketing")
    withdraw(client, "u001", "marketing")
    grant(client, "u001", "marketing")
    assert request(client, "mailer-co", "u001", "marketing").status_code == 200


def test_05_notice_change_invalidates_existing_consent(client):
    grant(client, "u001", "analytics")
    pub = client.post("/api/notices", json={"purpose": "analytics", "text": "New notice v2 text"})
    assert pub.json()["version"] == 2 and pub.json()["invalidated_users"] == 1
    r = request(client, "analytics-co", "u001", "analytics")
    assert r.status_code == 403 and r.json()["reason"] == "NOTICE_VERSION_STALE"


def test_06_reconsent_under_new_notice_restores_access_with_new_version(client):
    grant(client, "u001", "analytics")
    client.post("/api/notices", json={"purpose": "analytics", "text": "New notice v2 text"})
    g = grant(client, "u001", "analytics").json()
    assert g["notice_version"] == 2
    r = request(client, "analytics-co", "u001", "analytics")
    assert r.status_code == 200 and r.json()["notice_version"] == 2


# -------------------------------------------------------------- enforcement
def test_07_no_consent_record_is_denied_by_default(client):
    r = request(client, "research-lab", "u002", "research_sharing")
    assert r.status_code == 403 and r.json()["reason"] == "NO_CONSENT_RECORD"


def test_08_consent_is_purpose_specific(client):
    grant(client, "u001", "analytics")
    r = request(client, "mailer-co", "u001", "marketing")
    assert r.status_code == 403 and r.json()["reason"] == "NO_CONSENT_RECORD"


def test_09_withdrawing_one_purpose_leaves_others_intact(client):
    grant(client, "u001", "analytics")
    grant(client, "u001", "marketing")
    withdraw(client, "u001", "analytics")
    assert request(client, "analytics-co", "u001", "analytics").status_code == 403
    assert request(client, "mailer-co", "u001", "marketing").status_code == 200


def test_10_consent_is_user_specific(client):
    grant(client, "u001", "analytics")
    r = request(client, "analytics-co", "u002", "analytics")
    assert r.status_code == 403 and r.json()["reason"] == "NO_CONSENT_RECORD"


def test_11_consumer_not_registered_for_purpose_is_denied_even_with_consent(client):
    grant(client, "u001", "marketing")
    r = request(client, "analytics-co", "u001", "marketing")  # wrong consumer
    assert r.status_code == 403 and r.json()["reason"] == "CONSUMER_NOT_AUTHORIZED_FOR_PURPOSE"


def test_12_invalid_api_key_is_rejected(client):
    grant(client, "u001", "analytics")
    r = request(client, "analytics-co", "u001", "analytics", key="wrong-key")
    assert r.status_code == 401 and r.json()["reason"] == "INVALID_CREDENTIALS"


def test_13_unknown_user_and_unknown_purpose(client):
    assert request(client, "analytics-co", "u999", "analytics").status_code == 404
    assert request(client, "analytics-co", "u001", "telepathy").status_code == 404


def test_14_grant_with_outdated_notice_hash_is_rejected(client):
    old_hash = client.get("/api/consent/u001").json()[0]["current_hash"]
    client.post("/api/notices", json={"purpose": "analytics", "text": "New notice v2 text"})
    r = grant(client, "u001", "analytics", notice_hash=old_hash)
    assert r.status_code == 409 and r.json()["error"] == "NOTICE_HASH_MISMATCH"
    assert request(client, "analytics-co", "u001", "analytics").status_code == 403


def test_15_withdraw_without_active_consent_is_rejected(client):
    r = withdraw(client, "u001", "analytics")
    assert r.status_code == 409 and r.json()["error"] == "NOT_GRANTED"


# -------------------------------------------------------------- audit trail
def test_16_every_decision_is_logged_allowed_and_denied(client):
    grant(client, "u001", "analytics")
    request(client, "analytics-co", "u001", "analytics")
    withdraw(client, "u001", "analytics")
    request(client, "analytics-co", "u001", "analytics")
    ev = events(client)
    for e in ("CONSENT_GRANTED", "ACCESS_GRANTED", "CONSENT_WITHDRAWN", "ACCESS_DENIED"):
        assert e in ev


def test_17_audit_chain_verifies_after_full_lifecycle(client):
    grant(client, "u001", "analytics")
    request(client, "analytics-co", "u001", "analytics")
    withdraw(client, "u001", "analytics")
    client.post("/api/notices", json={"purpose": "analytics", "text": "New notice v2 text"})
    v = client.get("/api/audit/verify").json()
    assert v["valid"] is True and v["entries"] >= 5


def test_18_audit_tampering_is_detected(client):
    grant(client, "u001", "analytics")
    withdraw(client, "u001", "analytics")
    store = client.app.state.store
    store.db.execute("UPDATE audit_log SET event='CONSENT_GRANTED' WHERE event='CONSENT_WITHDRAWN'")
    store.db.commit()
    v = client.get("/api/audit/verify").json()
    assert v["valid"] is False and v["first_bad_entry_id"] is not None


def test_19_audit_export_csv_contains_evidence_columns(client):
    grant(client, "u001", "analytics")
    r = client.get("/api/audit/export?format=csv")
    assert r.status_code == 200 and "text/csv" in r.headers["content-type"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    granted = [x for x in rows if x["event"] == "CONSENT_GRANTED"][0]
    assert granted["purpose"] == "analytics" and granted["notice_version"] == "1"
    assert len(granted["notice_hash"]) == 64 and granted["entry_hash"]


def test_20_audit_export_json_includes_integrity_block(client):
    grant(client, "u001", "analytics")
    body = client.get("/api/audit/export?format=json").json()
    assert body["integrity"]["valid"] is True and len(body["entries"]) >= 2