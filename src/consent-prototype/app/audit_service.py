"""Audit Service (badge 5): read-only views of D1, export, chain verification, role-scoped
monitoring (user / organization / administrator) and the revocation feed."""
import csv
import io
import json
from datetime import datetime, timezone

from .gateway import now
from .hashing import GENESIS, entry_hash

COLS = ["seq", "ts", "event", "user_pid", "purpose", "notice_hash", "actor", "reason", "detail",
        "prev_hash", "entry_hash"]


class AuditService:
    def __init__(self, gateway):
        self.gw = gateway

    # ------------------------------------------------------------------ reads
    def _rows(self, sql, params=()):
        with self.gw.read() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def entries(self, limit=500, user_pid=None, event=None):
        sql, p = "SELECT * FROM ledger WHERE 1=1", []
        if user_pid:
            sql += " AND user_pid=?"; p.append(user_pid)
        if event:
            sql += " AND event=?"; p.append(event)
        with self.gw.read() as conn:
            rows = [dict(r) for r in conn.execute(sql + " ORDER BY seq DESC LIMIT ?", (*p, limit)).fetchall()]
            for r in rows:
                if r["event"] == "WITHDRAW":
                    r["downstream"] = self._recipients(conn, r)
        return rows[::-1]

    # ----------------------------------------------------------------- verify
    def verify(self, expected_head=None) -> dict:
        rows = self._rows("SELECT * FROM ledger ORDER BY seq")
        prev, want, anchored = GENESIS, 1, expected_head is None
        for r in rows:
            if r["seq"] != want:
                return self._bad(r["seq"], "missing or re-ordered entry", len(rows))
            if r["prev_hash"] != prev or r["entry_hash"] != entry_hash(prev, r):
                return self._bad(r["seq"], "entry or chain hash mismatch", len(rows))
            prev, want = r["entry_hash"], want + 1
            if expected_head and r["entry_hash"] == expected_head:
                anchored = True
        if not anchored:
            return {"valid": False, "entries": len(rows), "head_hash": prev, "first_bad_seq": None,
                    "reason": "exported head hash not found: log truncated or rewritten after export"}
        return {"valid": True, "entries": len(rows), "head_hash": prev, "first_bad_seq": None,
                "reason": None, "anchored_to_export": expected_head is not None}

    @staticmethod
    def _bad(seq, reason, n):
        return {"valid": False, "entries": n, "head_hash": None, "first_bad_seq": seq, "reason": reason}

    # ----------------------------------------------------------------- export
    def export(self, fmt="json"):
        rows = self._rows("SELECT * FROM ledger ORDER BY seq")
        head = rows[-1]["entry_hash"] if rows else GENESIS
        if fmt == "csv":
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=COLS)
            w.writeheader(); w.writerows(rows)
            return buf.getvalue(), head
        body = {"exported_at": now(), "count": len(rows), "head_hash": head,
                "verification": self.verify(), "entries": rows}
        return json.dumps(body, indent=2), head

    # ------------------------------------------------------------ user view
    def user_view(self, user_pid):
        with self.gw.read() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM ledger WHERE user_pid=? OR event='NOTICE_PUBLISHED' ORDER BY seq DESC LIMIT 200",
                (user_pid,)).fetchall()]
            for r in rows:
                if r["event"] == "WITHDRAW":
                    r["downstream"] = self._recipients(conn, r)
        v = self.verify()
        return {"entries": rows, "server_check": {"chain_valid": v["valid"], "entries": v["entries"],
                "head_hash": v["head_hash"], "note": "server-reported; full verification needs the export"}}

    # ------------------------------------------------------------- org view
    def requester_view(self, requester_id):
        actor = f"requester:{requester_id}"
        rows = self._rows("SELECT * FROM ledger WHERE actor=? ORDER BY seq DESC LIMIT 200", (actor,))
        counts = {"ALLOW": 0}
        for r in self._rows("SELECT event, reason, COUNT(*) c FROM ledger WHERE actor=? GROUP BY event, reason", (actor,)):
            if r["event"] == "ALLOW":
                counts["ALLOW"] += r["c"]
            else:
                counts[r["reason"]] = counts.get(r["reason"], 0) + r["c"]
        return {"entries": rows, "counts": counts}

    # ------------------------------------------------------ revocation feed
    def _recipients(self, conn, w):
        """Requesters that received data (ALLOW) for this user+purpose before withdrawal `w`."""
        rs = conn.execute(
            "SELECT DISTINCT actor FROM ledger WHERE event='ALLOW' AND user_pid=? AND purpose=? AND seq<?",
            (w["user_pid"], w["purpose"], w["seq"])).fetchall()
        out = []
        for r in rs:
            rid = r["actor"].split(":", 1)[1]
            ack = conn.execute("SELECT acked_at FROM revocation_acks WHERE requester_id=? AND withdraw_seq=?",
                               (rid, w["seq"])).fetchone()
            out.append({"requester_id": rid, "acknowledged": bool(ack), "acked_at": ack["acked_at"] if ack else None})
        return out

    def revocations_for(self, requester_id):
        out = []
        with self.gw.read() as conn:
            for w in conn.execute("SELECT * FROM ledger WHERE event='WITHDRAW' ORDER BY seq DESC").fetchall():
                mine = [x for x in self._recipients(conn, dict(w)) if x["requester_id"] == requester_id]
                if mine:
                    out.append({"withdraw_seq": w["seq"], "ts": w["ts"], "user_pid": w["user_pid"],
                                "purpose": w["purpose"], "acknowledged": mine[0]["acknowledged"],
                                "acked_at": mine[0]["acked_at"],
                                "instruction": "Cease processing this user's data for this purpose."})
        return out
