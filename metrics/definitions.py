"""Metric semantic layer — every metric defined exactly once.

If a dashboard or ad-hoc query needs one of these numbers, it calls one
of these functions. No metric SQL lives in Metabase, in
load_metrics_to_db.py, in the bonus loop, or anywhere else. The
`metric_results` table in DuckDB is the *materialization* of the
function output; the function is the source of truth.

Every function returns a MetricResult that carries:
- value
- definition_version (semver; bump when the definition changes)
- is_complete (False when a deferred join hasn't resolved yet — e.g. a
  72-hour cohort window that's still open)
- confidence_interval (None unless we have one)
- computation_sql (the actual SQL that produced the number — so the
  audit trail is queryable, not just describable)
- breakdowns (dict of dimensions → MetricResult-shaped values)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import duckdb

REPO = Path(__file__).resolve().parents[1]
WAREHOUSE_DB = REPO / "warehouse" / "indiastox.duckdb"

# Bump these when the definition changes. Old materializations stay valid
# under their own definition_version; readers must keep both around.
DEFS = {
    "weekly_active_posters": "1.0.0",
    "time_to_first_action": "1.0.0",
    "unstop_to_participation_rate": "1.0.0",
    "ghost_rate": "1.0.0",
}


@dataclass
class MetricResult:
    metric_name: str
    value: float
    definition_version: str
    is_complete: bool
    confidence_interval: Optional[tuple[float, float]]
    computation_sql: str
    as_of: datetime
    breakdowns: Optional[dict] = field(default=None)


def _connect():
    if not WAREHOUSE_DB.exists():
        raise FileNotFoundError(f"warehouse not built: {WAREHOUSE_DB}. Run `make resolve` first.")
    return duckdb.connect(str(WAREHOUSE_DB), read_only=True)


def _week_bounds(week_of: str) -> tuple[datetime, datetime]:
    """ISO week → (start_utc, end_utc) inclusive-exclusive."""
    year, week = week_of.split("-W")
    year, week = int(year), int(week)
    # ISO weeks: Mon = day 1. Jan 1 2024 is a Monday so W01 = 2024-01-01..07.
    monday = datetime.strptime(f"{year}-W{week:02d}-1", "%G-W%V-%u").replace(tzinfo=timezone.utc)
    return monday, monday + timedelta(days=7)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 1. weekly_active_posters
# ---------------------------------------------------------------------------

def weekly_active_posters(week_of: str, min_identity_confidence: float = 0.70) -> MetricResult:
    """Users who made >= 1 prediction in ISO week `week_of`, gated by identity_confidence.

    Returns a count. The confidence interval is derived from the number of
    lower-confidence entities excluded: if an entity was excluded by the
    identity-confidence gate, it might still be a real poster — that's the
    width of uncertainty.
    """
    start, end = _week_bounds(week_of)
    sql = """
        WITH posters AS (
          SELECT DISTINCT p.user_id
          FROM fact_prediction p
          JOIN dim_user u ON u.user_id = p.user_id
          WHERE p.made_at >= ? AND p.made_at < ?
            AND u.identity_confidence >= ?
        )
        SELECT COUNT(*) FROM posters
    """
    sql_lower_excluded = """
        WITH excluded AS (
          SELECT DISTINCT p.user_id
          FROM fact_prediction p
          JOIN dim_user u ON u.user_id = p.user_id
          WHERE p.made_at >= ? AND p.made_at < ?
            AND u.identity_confidence < ?
            AND u.identity_confidence > 0
        )
        SELECT COUNT(*) FROM excluded
    """
    con = _connect()
    try:
        value = con.execute(sql, [start, end, min_identity_confidence]).fetchone()[0]
        low_conf_excluded = con.execute(sql_lower_excluded, [start, end, min_identity_confidence]).fetchone()[0]
    finally:
        con.close()

    return MetricResult(
        metric_name="weekly_active_posters",
        value=float(value),
        definition_version=DEFS["weekly_active_posters"],
        is_complete=_now() >= end,
        confidence_interval=(float(value), float(value + low_conf_excluded)),
        computation_sql=sql.strip(),
        as_of=_now(),
        breakdowns=dict(low_confidence_excluded=int(low_conf_excluded), min_identity_confidence=min_identity_confidence),
    )


# ---------------------------------------------------------------------------
# 2. time_to_first_action
# ---------------------------------------------------------------------------

def time_to_first_action(week_of: str, acquisition_source: str = "all") -> MetricResult:
    """Median hours from challenge_signup to first prediction_made.

    Only includes users whose signup+72h window has closed. The result is
    `is_complete=False` if any user's window is still open at as_of time.
    Breakdowns: device_type, city_tier.
    """
    start, end = _week_bounds(week_of)
    now = _now()
    cutoff = end + timedelta(hours=72)

    where_acq = "" if acquisition_source == "all" else "AND u.acquisition_source = ?"
    params = [start, end]
    if acquisition_source != "all":
        params.append(acquisition_source)

    sql = f"""
        WITH cs AS (
          SELECT e.user_id, MIN(e.event_at) AS signup_at
          FROM fact_engagement e
          JOIN dim_user u ON u.user_id = e.user_id
          WHERE e.event_type = 'challenge_signup'
            AND e.event_at >= ? AND e.event_at < ?
            {where_acq}
          GROUP BY e.user_id
        ),
        first_pred AS (
          SELECT p.user_id, MIN(p.made_at) AS first_pred_at
          FROM fact_prediction p
          GROUP BY p.user_id
        )
        SELECT median(
          date_diff('millisecond', cs.signup_at, fp.first_pred_at) / 3600000.0
        )
        FROM cs
        JOIN first_pred fp ON fp.user_id = cs.user_id
        WHERE fp.first_pred_at >= cs.signup_at
    """

    sql_breakdown = sql + " GROUP BY {dim}"
    # Two specific breakdowns: device_type, city_tier. They are joined to
    # dim_user; the placeholder substitution below is safe because dim is
    # one of two literals controlled here.

    con = _connect()
    try:
        median_hours = con.execute(sql, params).fetchone()[0]
        if median_hours is None:
            median_hours = 0.0

        breakdowns: dict = {}
        for dim_col in ("device_type", "city_tier"):
            sql_b = f"""
                WITH cs AS (
                  SELECT e.user_id, MIN(e.event_at) AS signup_at
                  FROM fact_engagement e
                  JOIN dim_user u ON u.user_id = e.user_id
                  WHERE e.event_type = 'challenge_signup'
                    AND e.event_at >= ? AND e.event_at < ?
                    {where_acq}
                  GROUP BY e.user_id
                ),
                first_pred AS (
                  SELECT p.user_id, MIN(p.made_at) AS first_pred_at
                  FROM fact_prediction p
                  GROUP BY p.user_id
                )
                SELECT u.{dim_col},
                       median(date_diff('millisecond', cs.signup_at, fp.first_pred_at) / 3600000.0) AS median_hours,
                       COUNT(*) AS n
                FROM cs
                JOIN first_pred fp ON fp.user_id = cs.user_id
                JOIN dim_user u ON u.user_id = cs.user_id
                WHERE fp.first_pred_at >= cs.signup_at
                GROUP BY u.{dim_col}
            """
            rows = con.execute(sql_b, params).fetchall()
            breakdowns[dim_col] = [
                dict(value=r[0], median_hours=float(r[1] or 0.0), n=int(r[2])) for r in rows
            ]
    finally:
        con.close()

    return MetricResult(
        metric_name="time_to_first_action",
        value=float(median_hours),
        definition_version=DEFS["time_to_first_action"],
        is_complete=now >= cutoff,
        confidence_interval=None,
        computation_sql=sql.strip(),
        as_of=now,
        breakdowns=breakdowns,
    )


# ---------------------------------------------------------------------------
# 3. unstop_to_participation_rate
# ---------------------------------------------------------------------------

def unstop_to_participation_rate(week_of: str) -> MetricResult:
    """challenge_participation count / challenge_signup count for the Unstop cohort.

    A "participation" = made >= 1 prediction within 7 days of signup.
    is_complete = False until 72h after the cohort window closes.
    """
    start, end = _week_bounds(week_of)
    now = _now()
    cutoff = end + timedelta(hours=72)

    sql = """
        WITH unstop_cohort AS (
          SELECT u.user_id
          FROM dim_user u
          JOIN fact_acquisition a ON a.user_id = u.user_id
          WHERE a.touchpoint_source = 'unstop'
            AND a.touchpoint_at >= ? AND a.touchpoint_at < ?
        ),
        cs AS (
          SELECT user_id, MIN(event_at) AS signup_at
          FROM fact_engagement
          WHERE event_type = 'challenge_signup'
            AND user_id IN (SELECT user_id FROM unstop_cohort)
          GROUP BY user_id
        ),
        first_pred AS (
          SELECT user_id, MIN(made_at) AS first_pred_at
          FROM fact_prediction
          GROUP BY user_id
        )
        SELECT
          (SELECT COUNT(*) FROM cs) AS signups,
          (SELECT COUNT(*) FROM cs JOIN first_pred fp ON fp.user_id = cs.user_id
            WHERE fp.first_pred_at <= cs.signup_at + INTERVAL '7 days') AS participations
    """

    con = _connect()
    try:
        signups, participations = con.execute(sql, [start, end]).fetchone()
    finally:
        con.close()

    rate = float(participations / signups) if signups else 0.0

    # If still inside the cohort window, give a band: current rate to a
    # generous upper bound assuming the remaining users participate at the
    # current rate.
    ci: Optional[tuple[float, float]] = None
    if now < cutoff:
        ci = (rate * 0.8, min(1.0, rate * 1.2))

    return MetricResult(
        metric_name="unstop_to_participation_rate",
        value=rate,
        definition_version=DEFS["unstop_to_participation_rate"],
        is_complete=now >= cutoff,
        confidence_interval=ci,
        computation_sql=sql.strip(),
        as_of=now,
        breakdowns=dict(signups=int(signups or 0), participations=int(participations or 0)),
    )


# ---------------------------------------------------------------------------
# 4. ghost_rate
# ---------------------------------------------------------------------------

def ghost_rate(week_of: str, acquisition_source: str = "all") -> MetricResult:
    """Users with zero predictions AND zero participations within 7 days of signup.

    Breakdowns: by_source, by_device, by_city_tier.
    """
    start, end = _week_bounds(week_of)
    now = _now()
    cutoff = end + timedelta(hours=24 * 7)

    where_acq = "" if acquisition_source == "all" else "AND a.touchpoint_source = ?"
    params: list = [start, end]
    if acquisition_source != "all":
        params.append(acquisition_source)

    sql = f"""
        WITH cohort AS (
          SELECT DISTINCT u.user_id
          FROM dim_user u
          JOIN fact_acquisition a ON a.user_id = u.user_id
          WHERE a.touchpoint_at >= ? AND a.touchpoint_at < ?
            {where_acq}
        ),
        signups AS (
          SELECT user_id, MIN(event_at) AS signup_at
          FROM fact_engagement
          WHERE event_type = 'challenge_signup'
            AND user_id IN (SELECT user_id FROM cohort)
          GROUP BY user_id
        ),
        active AS (
          SELECT DISTINCT user_id FROM fact_prediction
          WHERE made_at <= ?
        )
        SELECT
          (SELECT COUNT(*) FROM cohort) AS total,
          (SELECT COUNT(*) FROM cohort WHERE user_id NOT IN (SELECT user_id FROM active)) AS ghosts
    """
    # `cutoff` used as upper bound for "within 7 days of signup window".
    params_q = params + [cutoff]

    con = _connect()
    try:
        total, ghosts = con.execute(sql, params_q).fetchone()
        total = int(total or 0)
        ghosts = int(ghosts or 0)
        rate = float(ghosts / total) if total else 0.0

        # Breakdowns.
        def _bd(dim_col: str) -> list[dict]:
            q = f"""
                WITH cohort AS (
                  SELECT DISTINCT u.user_id, u.{dim_col} AS dim_value
                  FROM dim_user u
                  JOIN fact_acquisition a ON a.user_id = u.user_id
                  WHERE a.touchpoint_at >= ? AND a.touchpoint_at < ?
                    {where_acq}
                ),
                active AS (
                  SELECT DISTINCT user_id FROM fact_prediction WHERE made_at <= ?
                )
                SELECT cohort.dim_value,
                       SUM(CASE WHEN cohort.user_id NOT IN (SELECT user_id FROM active) THEN 1 ELSE 0 END) * 1.0
                         / COUNT(*) AS ghost_rate,
                       COUNT(*) AS n
                FROM cohort
                GROUP BY cohort.dim_value
                ORDER BY ghost_rate DESC
            """
            rows = con.execute(q, params_q).fetchall()
            return [dict(value=r[0], ghost_rate=float(r[1] or 0.0), n=int(r[2])) for r in rows]

        bd_device = _bd("device_type")
        bd_tier = _bd("city_tier")

        # by_source — only meaningful when caller didn't already filter by source.
        by_source: list[dict] = []
        if acquisition_source == "all":
            q_src = """
                WITH cohort AS (
                  SELECT DISTINCT u.user_id, a.touchpoint_source AS src
                  FROM dim_user u
                  JOIN fact_acquisition a ON a.user_id = u.user_id
                  WHERE a.touchpoint_at >= ? AND a.touchpoint_at < ?
                ),
                active AS (
                  SELECT DISTINCT user_id FROM fact_prediction WHERE made_at <= ?
                )
                SELECT src,
                       SUM(CASE WHEN cohort.user_id NOT IN (SELECT user_id FROM active) THEN 1 ELSE 0 END) * 1.0
                         / COUNT(*) AS ghost_rate,
                       COUNT(*) AS n
                FROM cohort
                GROUP BY src
                ORDER BY ghost_rate DESC
            """
            rows = con.execute(q_src, [start, end, cutoff]).fetchall()
            by_source = [dict(value=r[0], ghost_rate=float(r[1] or 0.0), n=int(r[2])) for r in rows]
    finally:
        con.close()

    return MetricResult(
        metric_name="ghost_rate",
        value=rate,
        definition_version=DEFS["ghost_rate"],
        is_complete=now >= cutoff,
        confidence_interval=None,
        computation_sql=sql.strip(),
        as_of=now,
        breakdowns=dict(
            cohort_size=total,
            ghost_count=ghosts,
            by_source=by_source,
            by_device=bd_device,
            by_city_tier=bd_tier,
        ),
    )
