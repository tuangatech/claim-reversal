# shared/db.py
"""Creates and seeds the SQLite database for appeals and events."""

import json
import sqlite3
from pathlib import Path


def init_db(db_path: str = "data/claims.db") -> None:
    """Creates data/ directory and both tables if they don't already exist."""

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS appeals (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            denial_record TEXT,
            evidence_bundle TEXT,
            appeal_letter TEXT,
            submission TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS appeal_events (
            id TEXT PRIMARY KEY,
            claim_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            agent_name TEXT,
            payload TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.close()


def seed_db(db_path: str = "data/claims.db") -> None:
    """Inserts test claims from mock_eobs if they don't already exist."""

    conn = sqlite3.connect(db_path)
    mock_eobs_dir = Path("data/mock_eobs")

    for eob_file in mock_eobs_dir.glob("*.json"):
        eob_data = json.loads(eob_file.read_text(encoding="utf-8"))
        claim_id = eob_data["claim_id"]
        conn.execute(
            "INSERT OR IGNORE INTO appeals (id, status, denial_record) VALUES (?, ?, ?)",
            (claim_id, "pending", json.dumps(eob_data)),
        )

    conn.commit()
    conn.close()


def get_connection(db_path: str = "data/claims.db") -> sqlite3.Connection:
    """Returns an open connection with row_factory set. Caller must close."""

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

