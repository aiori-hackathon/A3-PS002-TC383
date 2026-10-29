"""Seeds synthetic data (D4 users, purposes, D3 requesters with KEY HASHES only, notice v1 in D2)."""
import json

from .config import SEED_REQUESTERS
from .hashing import notice_hash, sha256_hex

USERS = [
    ("u001", "Asha Rao", "asha@example.test", "25-34", 9200, 72, 7.5),
    ("u002", "Bikram Das", "bikram@example.test", "35-44", 6100, 80, 6.2),
    ("u003", "Charu Iyer", "charu@example.test", "18-24", 11800, 68, 8.0),
    ("u004", "Dev Malhotra", "dev@example.test", "45-54", 4300, 84, 5.9),
    ("u005", "Esha Sen", "esha@example.test", "25-34", 8700, 70, 7.1),
]
LEGAL = "DPDP Act 2023, s.4(1)(a) read with s.6 - consent for a specified purpose"
PURPOSES = {
    "analytics": ("Aggregate app-usage analytics", ["age_band", "steps_per_day"]),
    "marketing": ("Promotional e-mail offers", ["name", "email"]),
    "research_sharing": ("De-identified health research", ["age_band", "avg_heart_rate", "sleep_hours"]),
}
NOTICE_V1 = {
    "analytics": "Notice v1. Data: age band, daily step count. Purpose: aggregate usage analytics, "
                 "shared with Analytics Co and Research Lab. Withdraw any time on this screen. "
                 "Contact: privacy@example.test. Complaints: Data Protection Board of India.",
    "marketing": "Notice v1. Data: name, e-mail. Purpose: promotional offers sent by Mailer Co. "
                 "Withdraw any time on this screen. Contact: privacy@example.test. "
                 "Complaints: Data Protection Board of India.",
    "research_sharing": "Notice v1. Data: age band, average heart rate, sleep hours (de-identified). "
                        "Purpose: health research by Research Lab. Withdraw any time on this screen. "
                        "Contact: privacy@example.test. Complaints: Data Protection Board of India.",
}


def seed_if_empty(gw, settings):
    with gw.transaction() as conn:
        if conn.execute("SELECT 1 FROM purposes LIMIT 1").fetchone():
            return
        conn.executemany("INSERT INTO users VALUES(?,?,?,?,?,?,?)", USERS)
        for p, (desc, fields) in PURPOSES.items():
            conn.execute("INSERT INTO purposes VALUES(?,?,?,?)", (p, desc, json.dumps(fields), LEGAL))
            text = NOTICE_V1[p]
            h = notice_hash(p, 1, text)
            gw.insert_notice(conn, p, 1, text, h)
            gw.append(conn, "NOTICE_PUBLISHED", None, p, h, "system", None, "v0 -> v1 (seed)")
        for rid, (name, _env, _default, purposes) in SEED_REQUESTERS.items():
            key = settings.requester_keys[rid]
            conn.execute("INSERT INTO requesters VALUES(?,?,?,?)",
                         (rid, name, sha256_hex(key), json.dumps(purposes)))  # only the HASH is stored


def sync_requester_keys(gw, settings):
    """The API keys in the environment are authoritative: re-hash them on every start so rotating a key takes effect."""
    with gw.transaction() as conn:
        for rid in SEED_REQUESTERS:
            conn.execute("UPDATE requesters SET key_hash=? WHERE requester_id=?",
                         (sha256_hex(settings.requester_keys[rid]), rid))
