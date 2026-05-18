"""Snapshot source-table DDL hashes — supports N8 gameability axis 2.

Every pipeline run, we hash the column schema of each table metrics
read from. If a hash drifts without a deliberate migration, the
`metric_gameability_index` watchdog fires on the `source_table_drift`
axis: a metric's definition can stay constant while its source gets
silently reshaped — Goodhart's law in its quietest form.

Idempotent: when the current hash for a table matches the active row,
no-op. When it changes, mark the old row deprecated and insert the new.
"""
from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import duckdb

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

WAREHOUSE_DB = _REPO / "warehouse" / "indiastox.duckdb"

# Source tables that metrics read from. Order matters for hashing.
TRACKED_SOURCES = [
    "dim_user",
    "dim_challenge",
    "fact_acquisition",
    "fact_engagement",
    "fact_prediction",
]


def _ddl_signature(con, table_name: str) -> tuple[str, int]:
    """Returns (sha256_hash, column_count) over the table's columns + types."""
    rows = con.execute(
        """SELECT column_name, data_type FROM information_schema.columns
           WHERE table_name = ? ORDER BY ordinal_position""",
        [table_name],
    ).fetchall()
    payload = "\n".join(f"{name}:{dtype}" for name, dtype in rows)
    return hashlib.sha256(payload.encode()).hexdigest(), len(rows)


def register_all(notes: Optional[str] = None) -> dict[str, str]:
    """Snapshot every TRACKED_SOURCES table; return name → current hash."""
    if not WAREHOUSE_DB.exists():
        return {}

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    out: dict[str, str] = {}

    con = duckdb.connect(str(WAREHOUSE_DB), read_only=False)
    try:
        for table in TRACKED_SOURCES:
            try:
                h, n_cols = _ddl_signature(con, table)
            except Exception as e:
                print(f"WARN: source-table-registry skipped {table}: {e}", file=sys.stderr)
                continue
            existing = con.execute(
                """SELECT ddl_hash, deprecated_at FROM source_table_versions
                   WHERE source_table_name = ? AND ddl_hash = ?""",
                [table, h],
            ).fetchone()
            if existing:
                if existing[1] is not None:
                    con.execute(
                        """UPDATE source_table_versions SET deprecated_at = NULL
                           WHERE table_name = ? AND ddl_hash = ?""",
                        [table, h],
                    )
                out[table] = h
                continue

            # Hash changed (or first time we've seen this table).
            con.execute(
                """UPDATE source_table_versions SET deprecated_at = ?
                   WHERE source_table_name = ? AND deprecated_at IS NULL""",
                [now, table],
            )
            con.execute(
                """INSERT INTO source_table_versions
                   (source_table_name, ddl_hash, deployed_at, deprecated_at, column_count, notes, _source_system)
                   VALUES (?, ?, ?, NULL, ?, ?, 'source_table_registry')""",
                [table, h, now, n_cols, notes],
            )
            print(f"WARN: source-table DDL changed for {table} → {h[:8]} ({n_cols} cols)", file=sys.stderr)
            out[table] = h
    finally:
        con.close()
    return out


def count_active() -> dict[str, int]:
    """Per-table count of active (non-deprecated) DDL versions. >1 anywhere = drift."""
    if not WAREHOUSE_DB.exists():
        return {}
    con = duckdb.connect(str(WAREHOUSE_DB), read_only=True)
    try:
        rows = con.execute(
            """SELECT source_table_name, COUNT(*) FROM source_table_versions
               WHERE deprecated_at IS NULL
               GROUP BY source_table_name"""
        ).fetchall()
    finally:
        con.close()
    return {r[0]: int(r[1]) for r in rows}


def historical_count() -> dict[str, int]:
    """Total DDL hashes ever recorded per table. >1 = drift in history."""
    if not WAREHOUSE_DB.exists():
        return {}
    con = duckdb.connect(str(WAREHOUSE_DB), read_only=True)
    try:
        rows = con.execute(
            """SELECT source_table_name, COUNT(DISTINCT ddl_hash) FROM source_table_versions
               GROUP BY source_table_name"""
        ).fetchall()
    finally:
        con.close()
    return {r[0]: int(r[1]) for r in rows}


if __name__ == "__main__":
    snapshot = register_all()
    print("source_table_registry snapshot:")
    for name, h in snapshot.items():
        print(f"  {name:24s}  {h[:16]}")
    print()
    print("active per table:", count_active())
    print("historical per table:", historical_count())
