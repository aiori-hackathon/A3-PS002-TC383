"""Policy Enforcement Point (badges 2 and 6). One transaction per request:
authenticate -> purpose allowed -> notice published -> consent event exists -> latest is GRANT
-> hash equals current -> fetch data -> append ALLOW -> COMMIT. Any failure appends DENY(reason).
Anything unexpected rolls back, discards fetched data and returns 403 ERROR (fail closed)."""
import json
import os
from datetime import datetime, timezone

DENY_STATUS = 403


class PolicyEnforcementPoint:
    def __init__(self, gateway, mock_api, settings):
        self.gw, self.mock, self.settings = gateway, mock_api, settings
        self.fault_hook = None  # tests inject a fault here to prove fail-closed behaviour

    def share(self, api_key, body) -> dict:
        """Public entry point. `body` is whatever JSON the client sent (may be malformed)."""
        if (not isinstance(body, dict) or not isinstance(body.get("user_pid"), str)
                or not isinstance(body.get("purpose"), str) or not body["user_pid"] or not body["purpose"]):
            return self._fail_closed(ValueError("malformed request"), None, None)
        user_pid, purpose = body["user_pid"], body["purpose"]
        try:
            with self.gw.transaction() as conn:
                return self._evaluate(conn, api_key, user_pid, purpose)
        except Exception as exc:  # DB fault, timeout, bug: never allow
            return self._fail_closed(exc, user_pid, purpose)

    def _evaluate(self, conn, api_key, user_pid, purpose) -> dict:
        req = self.gw.requester_by_key(conn, api_key)
        actor = f"requester:{req['requester_id']}" if req else "requester:unknown"

        def deny(reason, nhash=None):
            if reason == "REQ_AUTH":  # unauthenticated: never write attacker-chosen text into someone's log
                e = self.gw.append(conn, "DENY", None, None, None, actor, reason, "unauthenticated request")
            else:
                e = self.gw.append(conn, "DENY", user_pid, purpose, nhash, actor, reason)
            return {"allowed": False, "status": DENY_STATUS, "reason": reason, "seq": e["seq"]}

        if req is None:
            return deny("REQ_AUTH")
        if purpose not in json.loads(req["allowed_purposes"]):
            return deny("REQ_PURPOSE")
        notice = self.gw.current_notice(conn, purpose)
        if notice is None:
            return deny("NO_NOTICE")
        ev = self.gw.latest_consent_event(conn, user_pid, purpose)
        if ev is None:                       # never consented, or unknown user: identical answer
            return deny("NO_CONSENT", notice["hash"])
        if ev["event"] == "WITHDRAW":
            return deny("CONSENT_WITHDRAWN", notice["hash"])
        if ev["notice_hash"] != notice["hash"]:
            return deny("NOTICE_STALE", notice["hash"])
        if self.fault_hook:
            self.fault_hook(conn)
        data = self.mock.get_records(conn, user_pid, purpose, self.settings.internal_token)
        e = self.gw.append(conn, "ALLOW", user_pid, purpose, notice["hash"], actor, "CONSENT_VALID",
                           "fields=" + ",".join(data))
        return {"allowed": True, "status": 200, "reason": "CONSENT_VALID", "seq": e["seq"],
                "purpose": purpose, "notice_version": notice["version"],
                "notice_hash": notice["hash"], "data": data}

    def _fail_closed(self, exc, user_pid, purpose) -> dict:
        try:  # best-effort DENY entry in a fresh transaction
            with self.gw.transaction() as conn:
                self.gw.append(conn, "DENY", user_pid, purpose, None, "system", "ERROR",
                               type(exc).__name__)
        except Exception as exc2:  # ledger itself unavailable: local error log
            self._error_log(exc, exc2)
        return {"allowed": False, "status": DENY_STATUS, "reason": "ERROR"}

    def _error_log(self, exc, exc2):
        try:
            os.makedirs(self.settings.log_dir, exist_ok=True)
            with open(os.path.join(self.settings.log_dir, "errors.log"), "a", encoding="utf-8") as f:
                f.write(f"{datetime.now(timezone.utc).isoformat()} ERROR {type(exc).__name__}; "
                        f"ledger unavailable: {type(exc2).__name__}\n")
        except OSError:
            pass
