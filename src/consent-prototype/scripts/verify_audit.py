#!/usr/bin/env python3
"""Standalone audit verifier: checks an exported ledger (JSON) WITHOUT the server or app code.
Usage: python scripts/verify_audit.py export.json [--expected-head HASH]
Exit code 0 = chain valid (and anchored if --expected-head given), 1 = problem found."""
import hashlib
import json
import sys

FIELDS = ("seq", "ts", "event", "user_pid", "purpose", "notice_hash", "actor", "reason", "detail")
GENESIS = "0" * 64


def sha(t): return hashlib.sha256(t.encode("utf-8")).hexdigest()


def canon(o): return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def verify(entries, expected_head=None):
    prev, want, anchored = GENESIS, 1, expected_head is None
    for e in entries:
        if e["seq"] != want:
            return False, f"entry {want} missing or re-ordered (found seq {e['seq']})"
        if e["prev_hash"] != prev or e["entry_hash"] != sha(prev + canon({k: e.get(k) for k in FIELDS})):
            return False, f"hash mismatch at seq {e['seq']}"
        prev, want = e["entry_hash"], want + 1
        anchored = anchored or e["entry_hash"] == expected_head
    if not anchored:
        return False, "expected head hash not found: log truncated or rewritten after export"
    return True, f"valid: {len(entries)} entries, head {prev}"


def main(argv):
    if not argv:
        print(__doc__); return 2
    data = json.load(open(argv[0], encoding="utf-8"))
    entries = data["entries"] if isinstance(data, dict) else data
    head = argv[argv.index("--expected-head") + 1] if "--expected-head" in argv else None
    ok, msg = verify(entries, head)
    print(("OK  " if ok else "FAIL ") + msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
