"""Production startup entrypoint for BotKeep, Heroku, and container runners.

Ensures environment loading, checks PORT and SERVER_PORT, prepares runtime data
directories, and starts the FastAPI Uvicorn server on 0.0.0.0.
"""

from pathlib import Path
import os
import sys

from dotenv import load_dotenv
import uvicorn

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=False)


def run() -> None:
    # Handle port from BotKeep (SERVER_PORT) or standard cloud (PORT)
    raw_port = os.getenv("PORT") or os.getenv("SERVER_PORT") or "8000"
    try:
        port = int(raw_port)
    except (ValueError, TypeError):
        port = 8000

    if not 1 <= port <= 65535:
        port = 8000

    # Ensure runtime data directory exists for SQLite
    db_path = Path(os.getenv("DB_PATH") or "runtime_data/nexglotv.sqlite")
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    os.environ["DB_PATH"] = str(db_path)

    # Launch server
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, workers=1)


if __name__ == "__main__":
    run()
