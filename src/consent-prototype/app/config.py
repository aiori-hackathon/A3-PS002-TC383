"""Runtime settings, read from environment variables."""
import os
from dataclasses import dataclass, field
from pathlib import Path

SEED_REQUESTERS = {
    # requester_id: (display name, env var holding its API key, default key for local use, allowed purposes)
    "analytics-co": ("Analytics Co", "KEY_ANALYTICS_CO", "key-analytics-001", ["analytics"]),
    "mailer-co": ("Mailer Co", "KEY_MAILER_CO", "key-mailer-002", ["marketing"]),
    "research-lab": ("Research Lab", "KEY_RESEARCH_LAB", "key-research-003",
                     ["research_sharing", "analytics"]),
}


@dataclass
class Settings:
    db_path: str = "consent.db"
    internal_token: str = "internal-service-token"   # PEP -> Mock Data-Sharing API (in-process)
    console_password: str = ""                       # optional: protects the web console (HTTP Basic)
    enable_docs: bool = True                         # Swagger UI / OpenAPI; switched off on Render
    log_dir: str = "logs"
    static_dir: str = str(Path(__file__).parent / "static")
    # The console sends requests on behalf of the seeded organizations, so the server holds their keys
    # (from the environment). The database stores only hashes of them.
    requester_keys: dict = field(default_factory=dict)


def load_settings(db_path: str | None = None) -> Settings:
    return Settings(
        db_path=db_path or os.environ.get("CONSENT_DB", "consent.db"),
        internal_token=os.environ.get("INTERNAL_SERVICE_TOKEN", "internal-service-token"),
        console_password=os.environ.get("CONSOLE_PASSWORD", ""),
        enable_docs=os.environ.get("ENABLE_DOCS", "1") == "1",
        log_dir=os.environ.get("LOG_DIR", "logs"),
        requester_keys={rid: os.environ.get(env, default)
                        for rid, (_, env, default, _) in SEED_REQUESTERS.items()},
    )


def check_deployment(settings: Settings) -> None:
    """Fail closed: never run on Render (a public URL) with the well-known local-development API keys."""
    if not os.environ.get("RENDER"):
        return
    weak = [rid for rid, (_, _, default, _) in SEED_REQUESTERS.items() if settings.requester_keys.get(rid) == default]
    if weak:
        raise RuntimeError("Refusing to start on Render with the built-in local API keys for: " + ", ".join(weak)
                           + ". Set the KEY_* environment variables (render.yaml generates them).")
