"""
Consent store + tamper-evident audit log + mock data-sharing decision logic.

Synthetic service : FitLife (a fictional fitness-tracking app)
Data-sharing purposes (3):
    analytics         -> aggregate usage analytics
    marketing         -> promotional e-mails
    research_sharing  -> de-identified health research

This module records TECHNICAL consent evidence only. It is not a legal
certification of DPDP Act / GDPR compliance.
"""
import csv
import hashlib
import io
import json
import sqlite3
import threading
from datetime import datetime, timezone

GENESIS = "0" * 64


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ConsentError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    user_id TEXT PRIMARY KEY, name TEXT, email TEXT, age_band TEXT,
    steps_per_day INTEGER, avg_heart_rate INTEGER, sleep_hours REAL);
CREATE TABLE IF NOT EXISTS purposes(
    purpose TEXT PRIMARY KEY, description TEXT, fields TEXT);
CREATE TABLE IF NOT EXISTS notices(
    purpose TEXT, version INTEGER, text TEXT, hash TEXT, published_at TEXT,
    PRIMARY KEY(purpose, version));
CREATE TABLE IF NOT EXISTS consumers(
    consumer_id TEXT PRIMARY KEY, key_hash TEXT, purposes TEXT, demo_key TEXT);
CREATE TABLE IF NOT EXISTS consents(
    user_id TEXT, purpose TEXT, status TEXT, notice_version INTEGER,
    notice_hash TEXT, updated_at TEXT, PRIMARY KEY(user_id, purpose));
CREATE TABLE IF NOT EXISTS audit_log(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, event TEXT, user_id TEXT,
    purpose TEXT, notice_version INTEGER, notice_hash TEXT, actor TEXT,
    detail TEXT, prev_hash TEXT, entry_hash TEXT);
"""

SEED_USERS = [
    ("u001", "Asha Rao", "asha@example.test", "25-34", 9200, 72, 7.5),
    ("u002", "Bikram Das", "bikram@example.test", "35-44", 6100, 80, 6.2),
    ("u003", "Charu Iyer", "charu@example.test", "18-24", 11800, 68, 8.0),
    ("u004", "Dev Malhotra", "dev@example.test", "45-54", 4300, 84, 5.9),
    ("u005", "Esha Sen", "esha@example.test", "25-34", 8700, 70, 7.1),
]

SEED_PURPOSES = {
    "analytics": ("Aggregate app-usage analytics", ["age_band", "steps_per_day"]),
    "marketing": ("Promotional e-mail offers", ["name", "email"]),
    "research_sharing": (
        "De-identified health research sharing",
        ["age_band", "avg_heart_rate", "sleep_hours"],
    ),
}

NOTICE_V1 = {
    "analytics": "FitLife notice v1: we share your age band and step count with our analytics partner to improve the app.",
    "marketing": "FitLife notice v1: we share your name and e-mail with our mailing partner to send offers.",
    "research_sharing": "FitLife notice v1: we share de-identified age band, heart rate and sleep data with a research lab.",
}

# consumer_id -> (demo api key, purposes it is registered for)
SEED_CONSUMERS = {
    "analytics-co": ("key-analytics-001", ["analytics"]),
    "mailer-co": ("key-mailer-002", ["marketing"]),
    "research-lab": ("key-research-003", ["research_sharing"]),
}

class ConsentStore:
    def __init__(self, path: str = "consent.db"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.db.executescript(SCHEMA)
            if not self.db.execute("SELECT 1 FROM purposes").fetchone():
                self._seed()

    # ------------------------------------------------------------------ setup
    def _seed(self):
        d = self.db
        d.executemany("INSERT INTO users VALUES(?,?,?,?,?,?,?)", SEED_USERS)
        for p, (desc, fields) in SEED_PURPOSES.items():
            d.execute("INSERT INTO purposes VALUES(?,?,?)", (p, desc, json.dumps(fields)))
            text = NOTICE_V1[p]
            d.execute("INSERT INTO notices VALUES(?,?,?,?,?)", (p, 1, text, sha256(text), now()))
        for cid, (key, purposes) in SEED_CONSUMERS.items():
            d.execute("INSERT INTO consumers VALUES(?,?,?,?)", (cid, sha256(key), json.dumps(purposes), key))
        d.commit()
        self._log("SYSTEM_INITIALISED", detail="seeded 5 synthetic users, 3 purposes, 3 consumers")

    def reset(self):
        with self.lock:
            for t in ("users", "purposes", "notices", "consumers", "consents", "audit_log"):
                self.db.execute(f"DELETE FROM {t}")
            self.db.execute("DELETE FROM sqlite_sequence WHERE name='audit_log'")
            self.db.commit()
            self._seed()

    # ------------------------------------------------------------- audit log
    @staticmethod
    def _entry_hash(prev_hash: str, body: dict) -> str:
        return sha256(prev_hash + json.dumps(body, sort_keys=True))

    def _log(self, event, user_id=None, purpose=None, notice_version=None,
             notice_hash=None, actor="system", detail=""):
        """Append a hash-chained audit entry. Caller must hold self.lock."""
        row = self.db.execute("SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
        prev = row[0] if row else GENESIS
        body = dict(ts=now(), event=event, user_id=user_id, purpose=purpose,
                    notice_version=notice_version, notice_hash=notice_hash,
                    actor=actor, detail=detail)
        h = self._entry_hash(prev, body)
        self.db.execute(
            "INSERT INTO audit_log(ts,event,user_id,purpose,notice_version,notice_hash,actor,detail,prev_hash,entry_hash)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (body["ts"], event, user_id, purpose, notice_version, notice_hash, actor, detail, prev, h))
        self.db.commit()

    def audit_entries(self):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM audit_log ORDER BY id")]

    def verify_audit(self) -> dict:
        prev = GENESIS
        for r in self.audit_entries():
            body = {k: r[k] for k in ("ts", "event", "user_id", "purpose", "notice_version",
                                      "notice_hash", "actor", "detail")}
            if r["prev_hash"] != prev or r["entry_hash"] != self._entry_hash(prev, body):
                return {"valid": False, "first_bad_entry_id": r["id"]}
            prev = r["entry_hash"]
        return {"valid": True, "entries": len(self.audit_entries()), "head_hash": prev}

    def export_audit(self, fmt: str = "json") -> str:
        rows = self.audit_entries()
        if fmt == "csv":
            buf = io.StringIO()
            cols = ["id", "ts", "event", "user_id", "purpose", "notice_version",
                    "notice_hash", "actor", "detail", "prev_hash", "entry_hash"]
            w = csv.DictWriter(buf, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
            return buf.getvalue()
        return json.dumps({"integrity": self.verify_audit(), "entries": rows}, indent=2)
    

    # --------------------------------------------------------------- lookups
    def _user(self, user_id):
        r = self.db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not r:
            raise ConsentError("USER_NOT_FOUND", f"unknown user {user_id}", 404)
        return r

    def _purpose(self, purpose):
        r = self.db.execute("SELECT * FROM purposes WHERE purpose=?", (purpose,)).fetchone()
        if not r:
            raise ConsentError("UNKNOWN_PURPOSE", f"unknown purpose {purpose}", 404)
        return r

    def current_notice(self, purpose) -> dict:
        r = self.db.execute("SELECT * FROM notices WHERE purpose=? ORDER BY version DESC LIMIT 1",
                            (purpose,)).fetchone()
        return dict(r)


    # --------------------------------------------------------- consent flows
    def grant(self, user_id, purpose, notice_hash=None, actor="user"):
        with self.lock:
            self._user(user_id)
            self._purpose(purpose)
            n = self.current_notice(purpose)
            if notice_hash is not None and notice_hash != n["hash"]:
                self._log("GRANT_REJECTED", user_id, purpose, n["version"], notice_hash, actor,
                          "client presented an outdated/incorrect notice hash")
                raise ConsentError("NOTICE_HASH_MISMATCH",
                                   "the notice you saw is not the current notice", 409)
            self.db.execute(
                "INSERT INTO consents VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,purpose) DO UPDATE SET "
                "status=excluded.status, notice_version=excluded.notice_version, "
                "notice_hash=excluded.notice_hash, updated_at=excluded.updated_at",
                (user_id, purpose, "granted", n["version"], n["hash"], now()))
            self.db.commit()
            self._log("CONSENT_GRANTED", user_id, purpose, n["version"], n["hash"], actor)
            return {"user_id": user_id, "purpose": purpose, "status": "granted",
                    "notice_version": n["version"], "notice_hash": n["hash"]}

    def withdraw(self, user_id, purpose, actor="user"):
        with self.lock:
            self._user(user_id)
            self._purpose(purpose)
            r = self.db.execute("SELECT * FROM consents WHERE user_id=? AND purpose=?",
                                (user_id, purpose)).fetchone()
            if not r or r["status"] != "granted":
                raise ConsentError("NOT_GRANTED", "no active consent to withdraw", 409)
            self.db.execute("UPDATE consents SET status='withdrawn', updated_at=? WHERE user_id=? AND purpose=?",
                            (now(), user_id, purpose))
            self.db.commit()
            self._log("CONSENT_WITHDRAWN", user_id, purpose, r["notice_version"], r["notice_hash"], actor)
            return {"user_id": user_id, "purpose": purpose, "status": "withdrawn",
                    "notice_version": r["notice_version"], "notice_hash": r["notice_hash"]}

    def publish_notice(self, purpose, text, actor="admin"):
        """New notice version. Consents given under older versions stop being valid."""
        with self.lock:
            self._purpose(purpose)
            if not text or not text.strip():
                raise ConsentError("EMPTY_NOTICE", "notice text required", 422)
            old = self.current_notice(purpose)
            version, h = old["version"] + 1, sha256(text)
            self.db.execute("INSERT INTO notices VALUES(?,?,?,?,?)", (purpose, version, text, h, now()))
            self.db.commit()
            self._log("NOTICE_PUBLISHED", None, purpose, version, h, actor,
                      f"v{old['version']} -> v{version}")
            stale = self.db.execute(
                "SELECT user_id, notice_version, notice_hash FROM consents "
                "WHERE purpose=? AND status='granted' AND notice_version<?", (purpose, version)).fetchall()
            for s in stale:
                self._log("CONSENT_INVALIDATED_BY_NOTICE_CHANGE", s["user_id"], purpose,
                          s["notice_version"], s["notice_hash"], "system",
                          f"re-consent required for notice v{version}")
            return {"purpose": purpose, "version": version, "hash": h, "invalidated_users": len(stale)}

    def check(self, user_id, purpose):
        """Real-time consent decision -> (allowed, reason, record)."""
        r = self.db.execute("SELECT * FROM consents WHERE user_id=? AND purpose=?",
                            (user_id, purpose)).fetchone()
        if not r:
            return False, "NO_CONSENT_RECORD", None
        if r["status"] != "granted":
            return False, "CONSENT_WITHDRAWN", r
        if r["notice_version"] != self.current_notice(purpose)["version"]:
            return False, "NOTICE_VERSION_STALE", r
        return True, "CONSENT_VALID", r


    # ------------------------------------------------- mock data-sharing API
    def share(self, consumer_id, api_key, user_id, purpose) -> dict:
        with self.lock:
            def deny(status, reason, ver=None, h=None):
                self._log("ACCESS_DENIED", user_id, purpose, ver, h, f"consumer:{consumer_id}", reason)
                return {"allowed": False, "status": status, "reason": reason}

            c = self.db.execute("SELECT * FROM consumers WHERE consumer_id=?", (consumer_id,)).fetchone()
            if not c or c["key_hash"] != sha256(api_key or ""):
                return deny(401, "INVALID_CREDENTIALS")
            if not self.db.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone():
                return deny(404, "USER_NOT_FOUND")
            p = self.db.execute("SELECT * FROM purposes WHERE purpose=?", (purpose,)).fetchone()
            if not p:
                return deny(404, "UNKNOWN_PURPOSE")
            if purpose not in json.loads(c["purposes"]):
                return deny(403, "CONSUMER_NOT_AUTHORIZED_FOR_PURPOSE")
            ok, reason, rec = self.check(user_id, purpose)
            ver = rec["notice_version"] if rec else None
            h = rec["notice_hash"] if rec else None
            if not ok:
                return deny(403, reason, ver, h)
            user = self._user(user_id)
            data = {f: user[f] for f in json.loads(p["fields"])}  # data minimisation
            self._log("ACCESS_GRANTED", user_id, purpose, ver, h, f"consumer:{consumer_id}",
                      "fields=" + ",".join(data))
            return {"allowed": True, "status": 200, "reason": reason, "purpose": purpose,
                    "notice_version": ver, "notice_hash": h, "data": data}
            


    # ------------------------------------------------------------ UI helpers
    def user_consents(self, user_id):
        with self.lock:
            self._user(user_id)
            out = []
            for p in self.db.execute("SELECT purpose FROM purposes"):
                p = p["purpose"]
                n = self.current_notice(p)
                r = self.db.execute("SELECT * FROM consents WHERE user_id=? AND purpose=?",
                                    (user_id, p)).fetchone()
                if not r:
                    status, ver = "none", None
                elif r["status"] == "withdrawn":
                    status, ver = "withdrawn", r["notice_version"]
                elif r["notice_version"] != n["version"]:
                    status, ver = "stale", r["notice_version"]
                else:
                    status, ver = "granted", r["notice_version"]
                out.append({"purpose": p, "status": status, "consented_version": ver,
                            "current_version": n["version"], "current_hash": n["hash"],
                            "notice_text": n["text"]})
            return out

    def state(self):
        with self.lock:
            return {
                "service": "FitLife (synthetic fitness app)",
                "users": [dict(r) for r in self.db.execute("SELECT user_id,name FROM users")],
                "purposes": [{"purpose": r["purpose"], "description": r["description"],
                              "fields": json.loads(r["fields"])} for r in self.db.execute("SELECT * FROM purposes")],
                "consumers": [{"consumer_id": r["consumer_id"], "purposes": json.loads(r["purposes"]),
                               "demo_key": r["demo_key"]} for r in self.db.execute("SELECT * FROM consumers")],
            }


