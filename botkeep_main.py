"""BotKeep production entrypoint for NexgloTV WhatsApp AI Agent.

Loads environment variables from .env, binds to 0.0.0.0 on the assigned
SERVER_PORT (or PORT fallback), ensures the runtime_data SQLite directory
exists, and serves app.main:app via Uvicorn.

Reference: NexgloTV_BotKeep_Deployment_Guide.md Section 3.
"""

from pathlib import Path
import os

from dotenv import load_dotenv
import uvicorn

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=False)

if __name__ == "__main__":
    raw_port = os.getenv("SERVER_PORT") or os.getenv("PORT") or "8000"
    port = int(raw_port)
    if not 1 <= port <= 65535:
        raise RuntimeError("SERVER_PORT must be a valid TCP port")

    db_path = Path(os.getenv("DB_PATH") or "runtime_data/nexglotv.sqlite")
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    os.environ["DB_PATH"] = str(db_path)

    uvicorn.run("app.main:app", host="0.0.0.0", port=port, workers=1)
