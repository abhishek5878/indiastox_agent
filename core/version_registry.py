"""Register metric versions in the DuckDB ledger on startup.

Call `register_all()` after the warehouse has been created. It walks
`core.confidence.VERSION_REGISTRY` (populated by `@versioned` at import
time), and for each (metric_name, definition_hash) pair:

  - if the row already exists in `metric_versions`: no-op
  - if the metric exists with a DIFFERENT hash: mark the prior active row
    deprecated_at = now(), insert the new one, print a WARN line.
    breaking_change is False by default (override via change_note=).
  - if the metric is new: insert.

Idempotent. Safe to call on every pipeline run.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import duckdb

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

WAREHOUSE_DB = _REPO / "warehouse" / "indiastox.duckdb"


def register_all(breaking_changes: Optional[dict[str, bool]] = None) -> None:
    """Snapshot the current VERSION_REGISTRY into metric_versions.

    breaking_changes maps metric_name → True if the hash drift this run is
    known-breaking. Defaults to False everywhere (informational only).
    """
    if not WAREHOUSE_DB.exists():
        return

    # Late import — VERSION_REGISTRY populates as metrics are imported.
    from core.confidence import VERSION_REGISTRY
    from metrics import definitions as _  # noqa: F401  — ensure decorators run
    from metrics import skill as _s  # noqa: F401

    breaking_changes = breaking_changes or {}
    now = datetime.now(timezone.utc)

    con = duckdb.connect(str(WAREHOUSE_DB), read_only=False)
    try:
        for metric_name, (version, definition_hash) in sorted(VERSION_REGISTRY.items()):
            # Existing row with same hash?
            existing = con.execute(
                """SELECT version, deprecated_at FROM metric_versions
                   WHERE metric_name = ? AND definition_hash = ?""",
                [metric_name, definition_hash],
            ).fetchone()
            if existing:
                # If it was deprecated previously, un-deprecate (re-deployment).
                if existing[1] is not None:
                    con.execute(
                        """UPDATE metric_versions SET deprecated_at = NULL
                           WHERE metric_name = ? AND definition_hash = ?""",
                        [metric_name, definition_hash],
                    )
                continue

            # Different hash for this metric? Deprecate any active row.
            prior_active = con.execute(
                """SELECT version, definition_hash FROM metric_versions
                   WHERE metric_name = ? AND deprecated_at IS NULL""",
                [metric_name],
            ).fetchall()
            for old_version, old_hash in prior_active:
                con.execute(
                    """UPDATE metric_versions SET deprecated_at = ?
                       WHERE metric_name = ? AND definition_hash = ?""",
                    [now, metric_name, old_hash],
                )
                breaking = breaking_changes.get(metric_name, False)
                kind = "BREAKING" if breaking else "non-breaking"
                print(
                    f"WARN: metric '{metric_name}' definition changed "
                    f"({old_hash[:8]} → {definition_hash[:8]}, {kind}). "
                    f"Prior MetricResults citing {old_hash[:8]} may not be comparable.",
                    file=sys.stderr,
                )

            con.execute(
                """INSERT INTO metric_versions
                   (metric_name, version, definition_hash, deployed_at,
                    deprecated_at, breaking_change, change_note, _source_system)
                   VALUES (?, ?, ?, ?, NULL, ?, NULL, ?)""",
                [
                    metric_name, version, definition_hash, now,
                    bool(breaking_changes.get(metric_name, False)),
                    "version_registry",
                ],
            )
    finally:
        con.close()


def get_recorded_hash(metric_name: str) -> Optional[str]:
    """Look up the currently-active hash for a metric. None if unknown."""
    if not WAREHOUSE_DB.exists():
        return None
    con = duckdb.connect(str(WAREHOUSE_DB), read_only=False)
    try:
        row = con.execute(
            """SELECT definition_hash FROM metric_versions
               WHERE metric_name = ? AND deprecated_at IS NULL
               ORDER BY deployed_at DESC LIMIT 1""",
            [metric_name],
        ).fetchone()
    finally:
        con.close()
    return row[0] if row else None


if __name__ == "__main__":
    register_all()
    con = duckdb.connect(str(WAREHOUSE_DB), read_only=False)
    try:
        rows = con.execute(
            """SELECT metric_name, version, SUBSTR(definition_hash, 1, 8) AS hash8,
                      deployed_at, deprecated_at
               FROM metric_versions ORDER BY metric_name, deployed_at"""
        ).fetchall()
    finally:
        con.close()
    print("\nmetric_versions ledger:")
    for r in rows:
        active = "active" if r[4] is None else "deprecated"
        print(f"  {r[0]:32s}  v{r[1]}  {r[2]}  {r[3]}  ({active})")
