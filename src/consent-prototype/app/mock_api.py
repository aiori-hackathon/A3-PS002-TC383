"""Mock Data-Sharing API (D4 access). INTERNAL ONLY: no HTTP route exists for it. The PEP calls
it in-process with a service token, and only after an ALLOW decision."""
import hmac
import json


class MockDataAPI:
    def __init__(self, internal_token: str):
        self._token = internal_token

    def get_records(self, conn, user_pid: str, purpose: str, token: str) -> dict:
        if not hmac.compare_digest(str(token).encode(), self._token.encode()):
            raise PermissionError("internal service token required")
        p = conn.execute("SELECT fields FROM purposes WHERE purpose=?", (purpose,)).fetchone()
        u = conn.execute("SELECT * FROM users WHERE user_pid=?", (user_pid,)).fetchone()
        if p is None or u is None:
            raise LookupError("no such user or purpose")
        return {f: u[f] for f in json.loads(p["fields"]) if f in u.keys()}  # data minimisation
