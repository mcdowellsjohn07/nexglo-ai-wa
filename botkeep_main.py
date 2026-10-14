"""BotKeep production entrypoint for NexgloTV WhatsApp AI Agent.

Loads environment variables from .env, binds to 0.0.0.0 on the assigned
SERVER_PORT (or PORT fallback), ensures the runtime_data SQLite directory
exists, and serves app.main:app via Uvicorn.
"""

from start import run

if __name__ == "__main__":
    run()
