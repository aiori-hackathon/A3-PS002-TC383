"""Consent Service (badges 3 and 4): grants, withdrawals, notice publication. Writes go through
the Storage Gateway only. Rejections are committed to the ledger first, then raised."""
import json

from .errors import ConsentError
from .hashing import notice_hash


class ConsentService:
    def __init__(self, gateway):
        self.gw = gateway

    # ---------------------------------------------------------------- grant
    def grant(self, user_pid, purpose, notice_hash_seen):
        rejection = None
        with self.gw.transaction() as conn:
            self._require_user_and_purpose(conn, user_pid, purpose)
            n = self.gw.current_notice(conn, purpose)
            if n is None:
                rejection = ("NO_NOTICE", "no notice is published for this purpose", None)
            elif not notice_hash_seen:
                rejection = ("HASH_MISSING", "the grant must carry the notice hash the user saw", n["hash"])
            elif notice_hash_seen != n["hash"]:
                rejection = ("NOTICE_HASH_MISMATCH", "the notice you saw is not the current notice", n["hash"])
            if rejection:
                self.gw.append(conn, "GRANT_REJECTED", user_pid, purpose, n["hash"] if n else None,
                               f"user:{user_pid}", rejection[0])
            else:
                e = self.gw.append(conn, "GRANT", user_pid, purpose, n["hash"], f"user:{user_pid}",
                                   "USER_GRANTED", f"notice v{n['version']}")
        if rejection:
            raise ConsentError(rejection[0], rejection[1], 409)
        return {"status": "granted", "purpose": purpose, "notice_version": n["version"],
                "notice_hash": n["hash"], "seq": e["seq"], "ts": e["ts"], "entry_hash": e["entry_hash"]}

    # ------------------------------------------------------------- withdraw
    def withdraw(self, user_pid, purpose):
        """Always accepted and idempotent. No notice-hash check: withdrawal is never blocked."""
        with self.gw.transaction() as conn:
            self._require_user_and_purpose(conn, user_pid, purpose)
            prev = self.gw.latest_consent_event(conn, user_pid, purpose)
            was_active = bool(prev and prev["event"] == "GRANT")
            nh = prev["notice_hash"] if prev else None
            e = self.gw.append(conn, "WITHDRAW", user_pid, purpose, nh, f"user:{user_pid}",
                               "USER_WITHDREW", "was active" if was_active else "no active consent")
        return {"status": "withdrawn", "purpose": purpose, "was_active": was_active,
                "seq": e["seq"], "ts": e["ts"], "entry_hash": e["entry_hash"]}

    # ------------------------------------------------------- publish notice
    def publish_notice(self, purpose, text):
        text = (text or "").strip()
        if not text or len(text) > 4000:
            raise ConsentError("BAD_NOTICE", "notice text must be 1-4000 characters", 422)
        with self.gw.transaction() as conn:
            if not conn.execute("SELECT 1 FROM purposes WHERE purpose=?", (purpose,)).fetchone():
                raise ConsentError("UNKNOWN_PURPOSE", f"unknown purpose {purpose}", 404)
            old = self.gw.current_notice(conn, purpose)
            version = (old["version"] if old else 0) + 1
            h = notice_hash(purpose, version, text)
            self.gw.insert_notice(conn, purpose, version, text, h)
            e = self.gw.append(conn, "NOTICE_PUBLISHED", None, purpose, h, "admin", None,
                               f"v{version - 1} -> v{version}")
            affected = conn.execute(
                "SELECT COUNT(*) c FROM (SELECT MAX(seq) m FROM ledger WHERE purpose=? AND "
                "event IN ('GRANT','WITHDRAW') GROUP BY user_pid) t JOIN ledger l ON l.seq=t.m "
                "WHERE l.event='GRANT' AND l.notice_hash != ?", (purpose, h)).fetchone()["c"]
        return {"purpose": purpose, "version": version, "hash": h, "seq": e["seq"],
                "users_needing_reconsent": affected}

    # --------------------------------------------------- withdrawal notices
    def acknowledge(self, requester_id, withdraw_seq):
        """An organization confirms it has stopped processing after a withdrawal."""
        with self.gw.transaction() as conn:
            self.gw.record_ack(conn, requester_id, withdraw_seq)
        return {"withdraw_seq": withdraw_seq, "acknowledged": True}

    # --------------------------------------------------------------- status
    def status_for(self, user_pid):
        with self.gw.read() as conn:
            if not conn.execute("SELECT 1 FROM users WHERE user_pid=?", (user_pid,)).fetchone():
                raise ConsentError("USER_NOT_FOUND", "unknown user", 404)
            out = []
            for p in conn.execute("SELECT * FROM purposes ORDER BY purpose").fetchall():
                n = self.gw.current_notice(conn, p["purpose"])
                ev = self.gw.latest_consent_event(conn, user_pid, p["purpose"])
                status, consented_version, receipt = "none", None, None
                if ev and ev["event"] == "WITHDRAW":
                    status = "withdrawn"
                elif ev:
                    row = conn.execute("SELECT version FROM notices WHERE hash=?", (ev["notice_hash"],)).fetchone()
                    consented_version = row["version"] if row else None
                    status = "granted" if n and ev["notice_hash"] == n["hash"] else "stale"
                    receipt = {"seq": ev["seq"], "ts": ev["ts"], "notice_hash": ev["notice_hash"],
                               "notice_version": consented_version, "entry_hash": ev["entry_hash"]}
                out.append({"purpose": p["purpose"], "description": p["description"],
                            "legal_basis": p["legal_basis"], "fields": json.loads(p["fields"]),
                            "status": status, "consented_version": consented_version, "receipt": receipt,
                            "notice": ({"version": n["version"], "hash": n["hash"], "text": n["text"]}
                                       if n else None)})
            return out

    def _require_user_and_purpose(self, conn, user_pid, purpose):
        if not conn.execute("SELECT 1 FROM users WHERE user_pid=?", (user_pid,)).fetchone():
            raise ConsentError("USER_NOT_FOUND", "unknown user", 404)
        if not conn.execute("SELECT 1 FROM purposes WHERE purpose=?", (purpose,)).fetchone():
            raise ConsentError("UNKNOWN_PURPOSE", f"unknown purpose {purpose}", 404)
