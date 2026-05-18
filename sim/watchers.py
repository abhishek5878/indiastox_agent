"""Auto-firing agent watchers — the Growth + CS agents in motion.

Called from the Living World tick or from a background loop. Each
watcher:
  - reads a metric from the live substrate (via the same MetricResult
    contract everything else uses)
  - compares against a stored baseline
  - if movement exceeds threshold, fires its agent action and logs a
    sim_event row

Today: Growth watches ghost_rate(unstop) for > +3pp movement vs the last
check. CS watches the at-risk user count for new entrants.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import duckdb

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

WAREHOUSE = _REPO / "warehouse" / "indiastox.duckdb"

# Stable state — these survive within one Streamlit session via the
# WorldState dataclass; the watchers also persist to a tiny KV table
# so they can be inspected from the UI.
_KV_DDL = """
CREATE TABLE IF NOT EXISTS sim_kv (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at TIMESTAMP
);
"""


def _ensure_kv(con) -> None:
    con.execute(_KV_DDL)


def _kv_get(con, key: str) -> Optional[str]:
    row = con.execute("SELECT value FROM sim_kv WHERE key = ?", [key]).fetchone()
    return row[0] if row else None


def _kv_put(con, key: str, value: str) -> None:
    con.execute(
        """INSERT INTO sim_kv (key, value, updated_at) VALUES (?, ?, ?)
           ON CONFLICT (key) DO UPDATE SET value = excluded.value,
                                            updated_at = excluded.updated_at""",
        [key, value, datetime.now(timezone.utc).replace(tzinfo=None)],
    )


def _log_event(con, kind: str, actor: str, payload: dict, lens: str = "all", sim_ts=None) -> None:
    from sim.world import _SIM_EVENTS_DDL  # noqa: F401 — ensures table
    con.execute(_SIM_EVENTS_DDL)
    con.execute(
        """INSERT INTO sim_events (event_id, sim_ts, wall_ts, kind, actor, payload, lens)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            f"evt-{uuid.uuid4().hex[:16]}",
            sim_ts or datetime.now(timezone.utc).replace(tzinfo=None),
            datetime.now(timezone.utc).replace(tzinfo=None),
            kind,
            actor,
            json.dumps(payload, default=str),
            lens,
        ],
    )


# ---------------------------------------------------------------------------
# Growth watcher — ghost_rate movement
# ---------------------------------------------------------------------------

def growth_watcher_tick(sim_now, *, fire_threshold_pp: float = 3.0) -> dict:
    """Re-read ghost_rate(unstop); if it moved > threshold_pp since the
    last check, log a watcher_fired event and return the proposal payload.
    The actual proposal-write happens elsewhere (the UI can choose to
    invoke experiment_loop on demand).
    """
    from mcp.tools import ToolSession  # local import to avoid circular at module load
    session = ToolSession()
    try:
        r = session.call("ghost_rate", week_of="2024-W01", acquisition_source="unstop")
    except Exception as e:
        return dict(error=str(e), fired=False)

    current = float(r.value)
    con = duckdb.connect(str(WAREHOUSE), read_only=False)
    try:
        _ensure_kv(con)
        prev_str = _kv_get(con, "growth.last_ghost_rate_unstop")
        prev = float(prev_str) if prev_str else current
        delta_pp = (current - prev) * 100.0
        _kv_put(con, "growth.last_ghost_rate_unstop", f"{current:.6f}")
        fired = abs(delta_pp) >= fire_threshold_pp
        if fired:
            _log_event(con, "growth_watcher_fired", actor="growth_watcher",
                       payload=dict(ghost_rate_unstop=current, delta_pp=delta_pp,
                                    threshold_pp=fire_threshold_pp,
                                    confidence=r.confidence),
                       lens="growth", sim_ts=sim_now)
    finally:
        con.close()
    return dict(fired=fired, delta_pp=delta_pp, current=current, prev=prev,
                confidence=r.confidence)


# ---------------------------------------------------------------------------
# CS watcher — count of at-risk users
# ---------------------------------------------------------------------------

def cs_watcher_tick(sim_now) -> dict:
    """Count users at risk per CS-Agent criteria. If the count jumped
    >= 5 since last check, fire.
    """
    con = duckdb.connect(str(WAREHOUSE), read_only=False)
    try:
        _ensure_kv(con)
        # Lightweight at-risk count: users who signed up but have made no
        # prediction in the last 3 sim-days. (The full CS Agent uses
        # phi/mu thresholds; the watcher is its faster, more frequent
        # cousin.)
        cutoff = sim_now.replace(hour=0, minute=0, second=0, microsecond=0)
        from datetime import timedelta
        recent = cutoff - timedelta(days=3)
        row = con.execute(
            """SELECT COUNT(*) FROM dim_user du
               WHERE du.signup_time IS NOT NULL
                 AND du.signup_time < ?
                 AND NOT EXISTS (
                   SELECT 1 FROM fact_prediction p
                   WHERE p.user_id = du.user_id AND p.made_at >= ?
                 )""",
            [sim_now, recent],
        ).fetchone()
        current = int(row[0] or 0)
        prev_str = _kv_get(con, "cs.last_at_risk_count")
        prev = int(prev_str) if prev_str else current
        delta = current - prev
        _kv_put(con, "cs.last_at_risk_count", str(current))
        fired = delta >= 5
        if fired:
            _log_event(con, "cs_watcher_fired", actor="cs_watcher",
                       payload=dict(at_risk_count=current, delta=delta),
                       lens="cs", sim_ts=sim_now)
    finally:
        con.close()
    return dict(fired=fired, delta=delta, current=current, prev=prev)
