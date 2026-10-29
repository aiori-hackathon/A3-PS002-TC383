"""Reset the demo: deletes the SQLite file (ledger included). Re-seeds on next start.
Local:  python -m scripts.reset_db        Docker:  docker compose down -v"""
import os

from app.config import load_settings

path = load_settings().db_path
for suffix in ("", "-wal", "-shm"):
    if os.path.exists(path + suffix):
        os.remove(path + suffix)
        print("removed", path + suffix)
print("done - the database is re-seeded on next start")
