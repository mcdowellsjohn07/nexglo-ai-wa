"""Tests for Heroku deployment configuration and readiness."""

import json
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_heroku_procfile_exists_and_valid():
    procfile = REPO_ROOT / "Procfile"
    assert procfile.exists(), "Procfile is required for Heroku"
    content = procfile.read_text(encoding="utf-8").strip()
    assert "web:" in content
    assert "app.main:app" in content
    assert "--workers 1" in content


def test_heroku_runtime_txt_exists_and_valid():
    runtime = REPO_ROOT / "runtime.txt"
    assert runtime.exists(), "runtime.txt is required for Heroku Python buildpack"
    content = runtime.read_text(encoding="utf-8").strip()
    assert content.startswith("python-3.")


def test_heroku_app_json_valid():
    app_json = REPO_ROOT / "app.json"
    assert app_json.exists(), "app.json is required for Heroku manifest"
    data = json.loads(app_json.read_text(encoding="utf-8"))
    assert data["name"] == "NexgloTV WhatsApp AI Agent"
    assert "env" in data
    assert "WHATSAPP_VERIFY_TOKEN" in data["env"]
    assert "NVIDIA_API_KEY" in data["env"]
    assert "OPENROUTER_API_KEY" in data["env"]



def test_heroku_app_health():
    client = TestClient(app)
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["business"] == "NexgloTV"
