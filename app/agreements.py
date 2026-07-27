"""Agreement persistence.

SQLite, standard library only. The brief does not evaluate the destination
system, so the goal here is an auditable record with no operational overhead:
one file, no server, readable with any SQLite client.

What matters is the shape of the record, not the engine behind it. Every field
needed to reconstruct why this agreement was approved is stored, so an audit
never depends on the transcript being available.
"""

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Overridable so a container can point at a mounted volume; the default keeps
# local runs and tests writing to the repo root as before.
DB_PATH = Path(
    os.getenv("DB_PATH", str(Path(__file__).resolve().parent.parent / "agreements.db"))
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS agreements (
    id                  TEXT PRIMARY KEY,
    call_id             TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    tier_id             TEXT NOT NULL,
    total               TEXT NOT NULL,
    currency            TEXT NOT NULL,
    num_payments        INTEGER NOT NULL,
    cadence             TEXT NOT NULL,
    schedule_json       TEXT NOT NULL,
    consumer_confirmed  INTEGER NOT NULL,
    compliance_events   TEXT NOT NULL,
    offer_history       TEXT NOT NULL
);
"""


def _connect(path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute(SCHEMA)
    return conn


def save(
    call_id: str,
    accepted: dict,
    currency: str,
    consumer_confirmed: bool,
    compliance_events: list[str],
    offer_history: list[dict],
    path: Path = DB_PATH,
) -> str:
    """Persist an approved agreement. Returns the agreement reference."""
    agreement_id = f"AG-{uuid.uuid4().hex[:10].upper()}"

    with _connect(path) as conn:
        conn.execute(
            """
            INSERT INTO agreements (
                id, call_id, created_at, tier_id, total, currency,
                num_payments, cadence, schedule_json, consumer_confirmed,
                compliance_events, offer_history
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agreement_id,
                call_id,
                datetime.now(timezone.utc).isoformat(),
                accepted["tier_id"],
                accepted["total"],
                currency,
                accepted["num_payments"],
                accepted["cadence"],
                json.dumps(accepted["schedule"]),
                int(consumer_confirmed),
                json.dumps(compliance_events),
                # Stored as text: the audit question is "what was offered and
                # in what order", not a queryable structure.
                json.dumps([str(h) for h in offer_history]),
            ),
        )

    return agreement_id


def get(agreement_id: str, path: Path = DB_PATH) -> dict | None:
    with _connect(path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM agreements WHERE id = ?", (agreement_id,)
        ).fetchone()
    return dict(row) if row else None


def count(path: Path = DB_PATH) -> int:
    with _connect(path) as conn:
        return conn.execute("SELECT COUNT(*) FROM agreements").fetchone()[0]