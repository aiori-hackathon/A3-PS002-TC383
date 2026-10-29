"""Storage Gateway (badge 1): the ONLY write path to D1 (ledger). Every decision runs in one
SQLite transaction opened with BEGIN IMMEDIATE, so the ledger head is locked while a
consent check, the data fetch and the audit append happen together."""
import contextlib
import hmac
import os
import sqlite3
from datetime import datetime, timezone

from .hashing import GENESIS, entry_hash, sha256_hex

EVENTS = ("GRANT", "WITHDRAW", "GRANT_REJECTED", "NOTICE_PUBLISHED", "ALLOW", "DENY")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS users(user_pid TEXT PRIMARY KEY, name TEXT, email TEXT, age_band TEXT,
    steps_per_day INTEGER, avg_heart_rate INTEGER, sleep_hours REAL);                  -- D4
CREATE TABLE IF NOT EXISTS purposes(purpose TEXT PRIMARY KEY, description TEXT, fields TEXT, legal_basis TEXT);
CREATE TABLE IF NOT EXISTS notices(purpose TEXT, version INTEGER, text TEXT, hash TEXT,
    published_at TEXT, PRIMARY KEY(purpose, version));                                 -- D2
CREATE TABLE IF NOT EXISTS requesters(requester_id TEXT PRIMARY KEY, name TEXT,
    key_hash TEXT UNIQUE, allowed_purposes TEXT);                                      -- D3
CREATE TABLE IF NOT EXISTS ledger(seq INTEGER PRIMARY KEY, ts TEXT NOT NULL,
    event TEXT NOT NULL CHECK(event IN ({",".join("'%s'" % e for e in EVENTS)})),
    user_pid TEXT, purpose TEXT, notice_hash TEXT, actor TEXT NOT NULL, reason TEXT, detail TEXT,
    prev_hash TEXT NOT NULL, entry_hash TEXT NOT NULL UNIQUE);                         -- D1
CREATE TABLE IF NOT EXISTS revocation_acks(requester_id TEXT, withdraw_seq INTEGER,
    acked_at TEXT, PRIMARY KEY(requester_id, withdraw_seq));  -- operational state, not consent evidence
CREATE INDEX IF NOT EXISTS idx_ledger_state ON ledger(user_pid, purpose, seq);
CREATE INDEX IF NOT EXISTS idx_ledger_actor ON ledger(actor, seq);

CREATE TRIGGER IF NOT EXISTS ledger_no_update BEFORE UPDATE ON ledger
BEGIN SELECT RAISE(ABORT, 'ledger is append-only: UPDATE blocked'); END;
CREATE TRIGGER IF NOT EXISTS ledger_no_delete BEFORE DELETE ON ledger
BEGIN SELECT RAISE(ABORT, 'ledger is append-only: DELETE blocked'); END;
CREATE TRIGGER IF NOT EXISTS notices_no_update BEFORE UPDATE ON notices
BEGIN SELECT RAISE(ABORT, 'notices are immutable once published: UPDATE blocked'); END;
CREATE TRIGGER IF NOT EXISTS notices_no_delete BEFORE DELETE ON notices
BEGIN SELECT RAISE(ABORT, 'notices are immutable once published: DELETE blocked'); END;
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _clip(value, n=64):
    return None if value is None else str(value)[:n]


class StorageGateway:
    def __init__(self, path: str):
        self.path = path
        conn = self.connect()
        conn.execute("PRAGMA journal_mode=WAL")
        cols = [r[1] for r in conn.execute("PRAGMA table_info(users)")]
        if cols and "user_pid" not in cols:  # database left over from an older version of the prototype
            conn.close()
            raise RuntimeError("This database was created by an older version of the prototype. Reset it: "
                               "'docker compose down -v' (Docker) or 'python -m scripts.reset_db' (local).")
        conn.executescript(SCHEMA)
        conn.close()
        try:
            os.chmod(path, 0o600)  # owner only; the -wal/-shm files inherit this mode
        except OSError:
            pass

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    @contextlib.contextmanager
    def transaction(self):
        """BEGIN IMMEDIATE ... COMMIT. Any exception rolls everything back (fail closed)."""
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    @contextlib.contextmanager
    def read(self):
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    # -------------------------------------------------- the single write path
    def append(self, conn, event, user_pid=None, purpose=None, notice_hash=None,
               actor="system", reason=None, detail=None) -> dict:
        if event not in EVENTS:
            raise ValueError(f"unknown ledger event {event}")
        head = conn.execute("SELECT seq, entry_hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
        seq = head["seq"] + 1 if head else 1
        prev = head["entry_hash"] if head else GENESIS
        entry = dict(seq=seq, ts=now(), event=event, user_pid=_clip(user_pid), purpose=_clip(purpose),
                     notice_hash=notice_hash, actor=_clip(actor, 80), reason=_clip(reason),
                     detail=_clip(detail, 300))
        h = entry_hash(prev, entry)
        conn.execute("INSERT INTO ledger(seq,ts,event,user_pid,purpose,notice_hash,actor,reason,detail,"
                     "prev_hash,entry_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                     (seq, entry["ts"], event, entry["user_pid"], entry["purpose"], notice_hash,
                      entry["actor"], entry["reason"], entry["detail"], prev, h))
        return {**entry, "prev_hash": prev, "entry_hash": h}

    def insert_notice(self, conn, purpose, version, text, h):
        """D2 write (notices are immutable afterwards: triggers block UPDATE/DELETE)."""
        conn.execute("INSERT INTO notices VALUES(?,?,?,?,?)", (purpose, version, text, h, now()))

    def record_ack(self, conn, requester_id, withdraw_seq):
        """Operational state (not consent evidence): an organization acknowledged a withdrawal notice."""
        conn.execute("INSERT OR IGNORE INTO revocation_acks VALUES(?,?,?)", (requester_id, withdraw_seq, now()))

    # ------------------------------------------------------------------ reads
    @staticmethod
    def current_notice(conn, purpose):
        return conn.execute("SELECT * FROM notices WHERE purpose=? ORDER BY version DESC LIMIT 1",
                            (purpose,)).fetchone()

    @staticmethod
    def latest_consent_event(conn, user_pid, purpose):
        """Latest GRANT/WITHDRAW only. ALLOW, DENY, GRANT_REJECTED never change consent state."""
        return conn.execute(
            "SELECT * FROM ledger WHERE user_pid=? AND purpose=? AND event IN ('GRANT','WITHDRAW') "
            "ORDER BY seq DESC LIMIT 1", (user_pid, purpose)).fetchone()

    @staticmethod
    def requester_by_key(conn, api_key):
        if not isinstance(api_key, str) or not api_key:
            return None
        h = sha256_hex(api_key)
        row = conn.execute("SELECT * FROM requesters WHERE key_hash=?", (h,)).fetchone()
        return row if row and hmac.compare_digest(row["key_hash"], h) else None
