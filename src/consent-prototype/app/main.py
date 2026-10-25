import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from .store import ConsentError, ConsentStore

STATIC = Path(__file__).parent / "static"


class ConsentIn(BaseModel):
    user_id: str
    purpose: str
    notice_hash: Optional[str] = None  # hash of the notice the user was shown


class NoticeIn(BaseModel):
    purpose: str
    text: str


class ShareIn(BaseModel):
    consumer_id: str
    user_id: str
    purpose: str


def create_app(db_path: Optional[str] = None) -> FastAPI:
    app = FastAPI(title="FitLife Consent Prototype")
    store = ConsentStore(db_path or os.environ.get("CONSENT_DB", "consent.db"))
    app.state.store = store

    @app.exception_handler(ConsentError)
    async def consent_error(_, exc: ConsentError):
        return JSONResponse(status_code=exc.status, content={"error": exc.code, "message": exc.message})

    # ---------------------------------------------------------------- UI
    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    # ------------------------------------------------- consent management
    @app.get("/api/state")
    def state():
        return store.state()

    @app.get("/api/consent/{user_id}")
    def consents(user_id: str):
        return store.user_consents(user_id)

    @app.post("/api/consent/grant")
    def grant(body: ConsentIn):
        return store.grant(body.user_id, body.purpose, body.notice_hash)

    @app.post("/api/consent/withdraw")
    def withdraw(body: ConsentIn):
        return store.withdraw(body.user_id, body.purpose)

    @app.post("/api/notices")
    def publish(body: NoticeIn):
        return store.publish_notice(body.purpose, body.text)

    # ----------------------------------------------- mock data-sharing API
    @app.post("/api/share/request")
    def share(body: ShareIn, x_api_key: Optional[str] = Header(default=None)):
        result = store.share(body.consumer_id, x_api_key, body.user_id, body.purpose)
        return JSONResponse(status_code=result["status"], content=result)

    # ------------------------------------------------------------- audit
    @app.get("/api/audit")
    def audit():
        return store.audit_entries()

    @app.get("/api/audit/verify")
    def verify():
        return store.verify_audit()

    @app.get("/api/audit/export")
    def export(format: str = Query("json", pattern="^(json|csv)$")):
        body = store.export_audit(format)
        media = "text/csv" if format == "csv" else "application/json"
        return Response(body, media_type=media,
                        headers={"Content-Disposition": f"attachment; filename=audit_export.{format}"})

    @app.post("/api/reset")
    def reset():
        store.reset()
        return {"status": "reset"}

    return app