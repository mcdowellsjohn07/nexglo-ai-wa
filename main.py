"""Root application entrypoint for direct GitHub repository deployments (BotKeep, Railway, Render, etc.)."""

from pathlib import Path
import os
from dotenv import load_dotenv
import uvicorn

from app.main import app, create_app  # noqa: F401

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=False)

if __name__ == "__main__":
    raw_port = os.getenv("PORT") or os.getenv("SERVER_PORT") or "8000"
    port = int(raw_port)
    db_path = Path(os.getenv("DB_PATH") or "runtime_data/nexglotv.sqlite")
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    os.environ["DB_PATH"] = str(db_path)

    uvicorn.run("app.main:app", host="0.0.0.0", port=port, workers=1)
