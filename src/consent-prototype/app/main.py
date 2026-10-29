"""HTTP layer.

Two kinds of callers:
  * the web console (this service's own interface): /api/console/* and /api/purposes. No credentials are
    sent by the browser; the server acts for the chosen person or organization. Real user sign-in is out
    of scope. Optionally protect the whole console with CONSOLE_PASSWORD (HTTP Basic).
  * partner systems: POST /api/share and /api/requester/*, authenticated with an organization API key.
Every data request goes through the same Policy Enforcement Point either way.
"""
import base64
import hmac
import json
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .audit_service import AuditService
from .config import Settings, check_deployment, load_settings
from .consent_service import ConsentService
from .errors import ConsentError
from .gateway import StorageGateway
from .mock_api import MockDataAPI
from .pep import PolicyEnforcementPoint
from .ratelimit import FailureLimiter
from .seed import seed_if_empty, sync_requester_keys


class GrantIn(BaseModel):
    purpose: str
    notice_hash: Optional[str] = None  # hash of the notice the person was shown (mandatory in effect)


class WithdrawIn(BaseModel):
    purpose: str
    notice_hash: Optional[str] = None  # ignored: withdrawal is never blocked


class NoticeIn(BaseModel):
    purpose: str
    text: str


class ConsoleRequestIn(BaseModel):
    requester_id: str
    user_pid: str
    purpose: str


class AckOut(BaseModel):
    withdraw_seq: int
    acknowledged: bool


# Paths that are always reachable without the console password (health checks and the partner API,
# which has its own API-key authentication).
OPEN_PREFIXES = ("/api/share", "/api/requester", "/api/health")
MAX_BODY = 64 * 1024  # no request in this API needs more
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


def _basic_password_ok(header: Optional[str], password: str) -> bool:
    try:
        scheme, _, b64 = (header or "").partition(" ")
        if scheme.lower() != "basic":
            return False
        supplied = base64.b64decode(b64).decode("utf-8").partition(":")[2]
        return hmac.compare_digest(supplied.encode(), password.encode())
    except Exception:
        return False


def create_app(db_path: Optional[str] = None, settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or load_settings(db_path)
    check_deployment(settings)
    gw = StorageGateway(settings.db_path)
    seed_if_empty(gw, settings)
    sync_requester_keys(gw, settings)
    key_failures = FailureLimiter(max_failures=20, window_seconds=60)      # wrong API keys
    password_failures = FailureLimiter(max_failures=10, window_seconds=300)  # wrong console passwords
    mock = MockDataAPI(settings.internal_token)
    pep = PolicyEnforcementPoint(gw, mock, settings)
    consent, audit = ConsentService(gw), AuditService(gw)

    docs = {} if settings.enable_docs else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    app = FastAPI(title="Consent Prototype", version="1.0", **docs)
    app.state.gateway, app.state.pep, app.state.settings = gw, pep, settings
    app.state.consent, app.state.audit, app.state.mock = consent, audit, mock

    # ------------------------------------------------ console password + HTTPS-ready headers
    @app.middleware("http")
    async def guard_and_harden(request: Request, call_next):
        path = request.url.path
        if int(request.headers.get("content-length") or 0) > MAX_BODY:
            return JSONResponse(status_code=413, content={"error": "TOO_LARGE", "message": "request body too large"})
        if settings.console_password and not path.startswith(OPEN_PREFIXES):
            if password_failures.blocked():
                return Response("Too many failed attempts. Try again in a few minutes.", status_code=429,
                                headers={"Retry-After": "300"})
            if not _basic_password_ok(request.headers.get("authorization"), settings.console_password):
                password_failures.record()
                return Response("Authentication required", status_code=401,
                                headers={"WWW-Authenticate": 'Basic realm="Consent console"'})
        # CSRF defence in depth: a state-changing console call must come from this site
        if path.startswith("/api/console/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if (origin and urlparse(origin).netloc != request.headers.get("host")) or \
                    request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse(status_code=403, content={"error": "CROSS_SITE", "message": "cross-site request refused"})
        response = await call_next(request)
        h = response.headers
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "no-referrer"
        h["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        if path.startswith("/api/"):
            h["Cache-Control"] = "no-store"
        if not path.startswith(("/docs", "/redoc", "/openapi.json")):  # Swagger UI needs its CDN assets
            h["Content-Security-Policy"] = CSP
        # TLS is terminated by the host's proxy (e.g. Render): trust X-Forwarded-Proto
        if request.headers.get("x-forwarded-proto") == "https" or request.url.scheme == "https":
            h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.exception_handler(ConsentError)
    async def consent_error(_, exc: ConsentError):
        return JSONResponse(status_code=exc.status, content={"error": exc.code, "message": exc.message})

    def requester_dep(x_api_key: Optional[str] = Header(default=None)) -> dict:
        with gw.read() as conn:
            r = gw.requester_by_key(conn, x_api_key)
        if not r:
            raise ConsentError("UNAUTHENTICATED", "a valid API key is required", 401)
        return dict(r)

    def _person(user_pid: str):
        with gw.read() as conn:
            if not conn.execute("SELECT 1 FROM users WHERE user_pid=?", (user_pid,)).fetchone():
                raise ConsentError("USER_NOT_FOUND", "unknown user", 404)

    def _acknowledge(requester_id: str, withdraw_seq: int):
        if not any(x["withdraw_seq"] == withdraw_seq for x in audit.revocations_for(requester_id)):
            raise ConsentError("NOT_FOUND", "no such withdrawal notice for this organization", 404)
        return consent.acknowledge(requester_id, withdraw_seq)

    # --------------------------------------------------------------------- public
    @app.get("/api/health", operation_id="health")
    def health():
        return {"status": "ok"}

    @app.get("/api/purposes", operation_id="purposes")
    def purposes():
        """Purposes and their CURRENT notices (notices are public information)."""
        with gw.read() as conn:
            out = []
            for p in conn.execute("SELECT * FROM purposes ORDER BY purpose").fetchall():
                n = gw.current_notice(conn, p["purpose"])
                out.append({"purpose": p["purpose"], "description": p["description"],
                            "legal_basis": p["legal_basis"], "fields": json.loads(p["fields"]),
                            "notice": {"version": n["version"], "hash": n["hash"], "text": n["text"]} if n else None})
            return out

    # ------------------------------------------------- partner API (organization API key)
    @app.post("/api/share", operation_id="share_request")
    async def share(request: Request):
        """Downstream data request: header X-API-Key, JSON body {user_pid, purpose}.
        Malformed input is refused (403 ERROR), never a 4xx validation error."""
        try:
            body = await request.json()
        except Exception:
            body = None
        key = request.headers.get("x-api-key")
        if key_failures.blocked():  # under attack: refuse bad keys WITHOUT writing to the ledger; good keys still work
            with gw.read() as conn:
                known = gw.requester_by_key(conn, key) is not None
            if not known:
                return JSONResponse(status_code=429, content={"allowed": False, "reason": "RATE_LIMITED"},
                                    headers={"Retry-After": "60"})
        result = await run_in_threadpool(pep.share, key, body)
        if result.get("reason") == "REQ_AUTH":
            key_failures.record()
        status = result.pop("status")
        return JSONResponse(status_code=status, content=result)

    @app.get("/api/requester/me", operation_id="requester_me")
    def requester_me(r: dict = Depends(requester_dep)):
        return {"requester_id": r["requester_id"], "name": r["name"],
                "allowed_purposes": json.loads(r["allowed_purposes"])}

    @app.get("/api/requester/feed", operation_id="requester_feed")
    def requester_feed(r: dict = Depends(requester_dep)):
        return audit.requester_view(r["requester_id"])

    @app.get("/api/requester/revocations", operation_id="requester_revocations")
    def requester_revocations(r: dict = Depends(requester_dep)):
        return audit.revocations_for(r["requester_id"])

    @app.post("/api/requester/revocations/{withdraw_seq}/ack", operation_id="requester_ack", response_model=AckOut)
    def requester_ack(withdraw_seq: int, r: dict = Depends(requester_dep)):
        return _acknowledge(r["requester_id"], withdraw_seq)

    # ---------------------------------------------------------------- web console
    @app.get("/api/console/state", operation_id="console_state")
    def console_state():
        with gw.read() as conn:
            people = [dict(r) for r in conn.execute("SELECT user_pid, name FROM users ORDER BY user_pid")]
            reqs = [{"requester_id": r["requester_id"], "name": r["name"],
                     "allowed_purposes": json.loads(r["allowed_purposes"])}
                    for r in conn.execute("SELECT * FROM requesters ORDER BY requester_id")]
        return {"people": people, "requesters": reqs}

    @app.get("/api/console/people/{user_pid}/consents", operation_id="console_consents")
    def console_consents(user_pid: str):
        return consent.status_for(user_pid)

    @app.get("/api/console/people/{user_pid}/timeline", operation_id="console_timeline")
    def console_timeline(user_pid: str):
        _person(user_pid)
        return audit.user_view(user_pid)

    @app.post("/api/console/people/{user_pid}/grant", operation_id="console_grant")
    def console_grant(user_pid: str, body: GrantIn):
        return consent.grant(user_pid, body.purpose, body.notice_hash)

    @app.post("/api/console/people/{user_pid}/withdraw", operation_id="console_withdraw")
    def console_withdraw(user_pid: str, body: WithdrawIn):
        return consent.withdraw(user_pid, body.purpose)

    @app.post("/api/console/requests", operation_id="console_request")
    def console_request(body: ConsoleRequestIn):
        """Sends a request AS the chosen organization, through the same PEP and API-key check as /api/share."""
        key = settings.requester_keys.get(body.requester_id)
        if not key:
            raise ConsentError("NOT_FOUND", "unknown organization", 404)
        res = pep.share(key, {"user_pid": body.user_pid, "purpose": body.purpose})
        return {"http_status": res.pop("status"), **res}

    @app.get("/api/console/requesters/{requester_id}/revocations", operation_id="console_revocations")
    def console_revocations(requester_id: str):
        if requester_id not in settings.requester_keys:
            raise ConsentError("NOT_FOUND", "unknown organization", 404)
        return audit.revocations_for(requester_id)

    @app.post("/api/console/requesters/{requester_id}/revocations/{withdraw_seq}/ack",
              operation_id="console_ack", response_model=AckOut)
    def console_ack(requester_id: str, withdraw_seq: int):
        if requester_id not in settings.requester_keys:
            raise ConsentError("NOT_FOUND", "unknown organization", 404)
        return _acknowledge(requester_id, withdraw_seq)

    @app.post("/api/console/notices", operation_id="console_publish")
    def console_publish(body: NoticeIn):
        return consent.publish_notice(body.purpose, body.text)

    @app.get("/api/console/ledger", operation_id="console_ledger")
    def console_ledger(limit: int = Query(300, ge=1, le=2000), user_pid: Optional[str] = None,
                       event: Optional[str] = None):
        return audit.entries(limit, user_pid, event)

    @app.get("/api/console/verify", operation_id="console_verify")
    def console_verify(expected_head: Optional[str] = None):
        return audit.verify(expected_head or None)

    @app.get("/api/console/export", operation_id="console_export")
    def console_export(format: str = Query("json", pattern="^(json|csv)$")):
        body, head = audit.export(format)
        media = "text/csv" if format == "csv" else "application/json"
        return Response(body, media_type=media, headers={
            "Content-Disposition": f"attachment; filename=audit_export.{format}", "X-Ledger-Head-Hash": head})

    # ----------------------------------------------------------------- web UI (React build)
    static = Path(settings.static_dir)
    if (static / "index.html").exists():
        app.mount("/", StaticFiles(directory=static, html=True), name="ui")
    else:
        @app.get("/", include_in_schema=False)
        def no_ui():
            return Response("API running. Build the React UI (see README) or use /docs.", media_type="text/plain")

    return app
