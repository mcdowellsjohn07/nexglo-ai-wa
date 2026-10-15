"""CLI script to generate an automated backup snapshot of NexgloTV database.

Supports both Turso Cloud and local SQLite database backends.
Usage:
    python scripts/backup_db.py
    python scripts/backup_db.py --output custom_backup.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure root package is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.config import Settings
from app.db import Database
from app.nexglo_state import Store


def run_backup(output_path: str = "") -> str:
    settings = Settings()
    print("=" * 60)
    print("NexgloTV WhatsApp AI Agent — Database Backup")
    print("=" * 60)

    if settings.turso_configured:
        print(f"Connecting to Turso Cloud DB: {settings.turso_database_url}")
    else:
        print(f"Using local SQLite storage: {settings.db_path}")

    store = Store(
        settings.db_path,
        settings.schema_path,
        turso_url=settings.turso_database_url,
        turso_token=settings.turso_auth_token,
    )

    print("Exporting table snapshots...")
    snapshot = store.export_backup()

    print("\nTable Summary:")
    for tbl, count in snapshot.get("table_counts", {}).items():
        print(f"  - {tbl:20s}: {count} records")

    now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if not output_path:
        backup_dir = root_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        target_file = backup_dir / f"nexglotv_backup_{now_str}.json"
    else:
        target_file = Path(output_path)
        target_file.parent.mkdir(parents=True, exist_ok=True)

    with open(target_file, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)

    file_size_kb = target_file.stat().st_size / 1024
    print(f"\n[OK] Backup successfully saved to:\n     {target_file} ({file_size_kb:.2f} KB)")
    print("=" * 60)
    return str(target_file)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backup NexgloTV database")
    parser.add_argument("--output", "-o", default="", help="Custom output JSON path")
    args = parser.parse_args()
    run_backup(args.output)
