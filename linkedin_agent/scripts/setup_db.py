"""
One-time initialization of the SQLite activity database.
Run this before the first use of the agent.

Usage:
    python -m linkedin_agent.scripts.setup_db
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add repo root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from linkedin_agent.config.settings import load_settings
from linkedin_agent.modules.tracker import ActivityTracker


def main() -> None:
    settings = load_settings()
    db_path = settings.data_dir / "activity_log.db"
    print(f"Inizializzazione database: {db_path}")
    tracker = ActivityTracker(db_path)
    tracker.init_db()
    print("✓ Database inizializzato con successo.")
    print(f"  Percorso: {db_path}")


if __name__ == "__main__":
    main()
