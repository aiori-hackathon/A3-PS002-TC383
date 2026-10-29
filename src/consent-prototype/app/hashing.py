"""One canonical-JSON + SHA-256 implementation used for notice hashes and the audit chain."""
import hashlib
import json

GENESIS = "0" * 64
ENTRY_FIELDS = ("seq", "ts", "event", "user_pid", "purpose", "notice_hash", "actor", "reason", "detail")


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def notice_hash(purpose: str, version: int, text: str) -> str:
    """SHA-256(canonical_json({purpose, version, text})) - one hash per purpose notice."""
    return sha256_hex(canonical_json({"purpose": purpose, "version": version, "text": text}))


def entry_hash(prev_hash: str, entry: dict) -> str:
    """entry_hash = SHA-256(prev_hash || canonical_json(entry))."""
    return sha256_hex(prev_hash + canonical_json({k: entry.get(k) for k in ENTRY_FIELDS}))
