"""Root application entrypoint for direct GitHub repository deployments (BotKeep, Railway, Render, etc.)."""

from app.main import app, create_app  # noqa: F401
from start import run

if __name__ == "__main__":
    run()
