#!/usr/bin/env python3
"""Packaging script for NexgloTV deployment archives.

Creates clean deployment zip files without virtual environments, caches,
temporary databases, or secrets.
"""

from pathlib import Path
import zipfile

REPO_ROOT = Path(__file__).resolve().parent.parent
DOWNLOADS_DIR = Path("C:/Users/PROF/Downloads")

EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "runtime_data",
    "receipts",
    "models",
    "logs",
    ".vscode",
    ".idea",
}

EXCLUDE_EXTS = {
    ".sqlite",
    ".sqlite-wal",
    ".sqlite-shm",
    ".db",
    ".pyc",
    ".pyo",
    ".log",
    ".zip",
}

EXCLUDE_FILES = {
    ".env",
    ".env.local",
    "lark_receipt_qr.png",
}


def should_include(rel_path: Path) -> bool:
    # Check parts
    parts = rel_path.parts
    for part in parts:
        if part in EXCLUDE_DIRS:
            return False
    if rel_path.suffix.lower() in EXCLUDE_EXTS:
        return False
    if rel_path.name in EXCLUDE_FILES:
        return False
    return True


def create_deployment_zip(target_path: Path):
    target_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(target_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(REPO_ROOT.rglob("*")):
            if not file_path.is_file():
                continue
            rel_path = file_path.relative_to(REPO_ROOT)
            if should_include(rel_path):
                zf.write(file_path, str(rel_path).replace("\\", "/"))
                count += 1
    print(f"Created {target_path} with {count} files ({target_path.stat().st_size:,} bytes).")


def main():
    heroku_zip = DOWNLOADS_DIR / "NexgloTV_Heroku_Deployment.zip"
    botkeep_zip = DOWNLOADS_DIR / "NexgloTV_BotKeep_Deployment.zip"

    create_deployment_zip(heroku_zip)
    create_deployment_zip(botkeep_zip)


if __name__ == "__main__":
    main()
