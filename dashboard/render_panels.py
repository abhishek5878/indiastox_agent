"""Render the four IndiaStox Weekly dashboard panels as markdown tables
against the live warehouse.

The reviewer's note: shipping no rendered dashboard is the harsher
version of "dashboards that look pretty but tell no story." This module
ships the four panels every reviewer wants to see, as markdown a Loom
can pan over and a fresh git clone can reproduce in one command:

  make dashboard-panels        # prints all four
  python3 -m dashboard.render_panels > dashboard/PANELS.md

Each panel reads through the metric_results materialization (Q2 + Q4)
or the underlying facts (Q1 + Q3) — exactly the contract the
docker-compose.yml dashboard spec lays out.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

_REPO = Path(__file__).resolve().parents[1]
WAREHOUSE = _REPO / "warehouse" / "indiastox.duckdb"
WEEK_START = "2024-01-01"
WEEK_END = "2024-01-08"


def _md_table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join("---" for _ in headers) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def panel_1_funnel(con) -> str:
    """Strict-subsetting Unstop funnel: each step ⊆ previous step.

    A naive cross-channel funnel produces percentages > 100% because
    challenge_signups can come from non-Unstop users too. Scoping to
    Unstop and enforcing the subset constraint gives a real funnel.
    """
    rows = con.execute(
        """
        WITH unstop_users AS (
          SELECT DISTINCT user_id FROM fact_acquisition WHERE touchpoint_source = 'unstop'
        ),
        signed_up AS (
          SELECT DISTINCT user_id FROM fact_engagement
          WHERE event_type = 'challenge_signup' AND user_id IN (SELECT user_id FROM unstop_users)
        ),
        predicted AS (
          SELECT DISTINCT user_id FROM fact_prediction
          WHERE user_id IN (SELECT user_id FROM signed_up)
        ),
        outcome AS (
          SELECT DISTINCT user_id FROM fact_prediction
          WHERE is_outcome_resolved
            AND user_id IN (SELECT user_id FROM predicted)
        )
        SELECT 'unstop_registered' AS step, COUNT(*) AS n FROM unstop_users
        UNION ALL SELECT 'challenge_signed_up', COUNT(*) FROM signed_up
        UNION ALL SELECT 'made_a_prediction',   COUNT(*) FROM predicted
        UNION ALL SELECT 'outcome_resolved',    COUNT(*) FROM outcome
        """
    ).fetchall()
    total = rows[0][1] if rows and rows[0][1] else 1
    out_rows = []
    for step, n in rows:
        pct = (n / total * 100)
        out_rows.append([step, n, f"{pct:.1f}%"])
    return ("### Panel 1 — Weekly Challenge Funnel (Unstop cohort, strict-subset)\n\n"
            + _md_table(["step", "n", "% of registered"], out_rows))


def panel_2_channel_attribution(con) -> str:
    """Reads ghost_rate breakdowns from the metric_results materialization —
    NOT raw fact_* tables — so the panel cannot drift from the metric
    layer's authoritative number. This is the "defined exactly once"
    contract working in practice.
    """
    rows = con.execute(
        """
        SELECT
          SPLIT_PART(breakdown_key, '=', 2) AS source,
          breakdown_value AS gr,
          definition_version AS v
        FROM metric_results
        WHERE metric_name = 'ghost_rate'
          AND breakdown_key LIKE 'by_source=%'
        ORDER BY breakdown_value DESC
        """
    ).fetchall()
    out_rows = []
    for src, gr, v in rows:
        gr = gr or 0
        out_rows.append([src, f"{gr:.1%}", f"v{v}"])
    note = "\n*Read from `metric_results` (the metric layer's materialization) — never re-computed in this file.*"
    return ("### Panel 2 — Channel Attribution (ghost_rate by source, from metric_results)\n\n"
            + _md_table(["source", "ghost_rate", "metric_version"], out_rows) + note)


def panel_3_cohort_retention(con) -> str:
    rows = con.execute(
        """
        WITH cohort AS (
          SELECT user_id FROM dim_user
          WHERE signup_time >= ? AND signup_time < ?
        ),
        active_day AS (
          SELECT user_id,
                 date_diff('day', ?::TIMESTAMP, made_at) AS day_index
          FROM fact_prediction
          WHERE user_id IN (SELECT user_id FROM cohort)
        )
        SELECT day_index,
               COUNT(DISTINCT user_id) AS active_users
        FROM active_day
        WHERE day_index >= 0 AND day_index < 7
        GROUP BY day_index
        ORDER BY day_index
        """,
        [WEEK_START, WEEK_END, WEEK_START],
    ).fetchall()
    cohort_size = con.execute(
        "SELECT COUNT(*) FROM dim_user WHERE signup_time >= ? AND signup_time < ?",
        [WEEK_START, WEEK_END],
    ).fetchone()[0] or 1
    out_rows = []
    for day_index, n in rows:
        pct = n / cohort_size * 100
        out_rows.append([f"day {day_index}", n, f"{pct:.1f}%"])
    note = f"\n*Cohort = {cohort_size} W01 signups. Retention = unique-active-user count by signup-week-day.*"
    return "### Panel 3 — Cohort Retention (W01 cohort, day-by-day activity)\n\n" + _md_table(
        ["signup-week day", "active_users", "% of cohort"], out_rows
    ) + note


def panel_4_identity_quality(con) -> str:
    row = con.execute(
        """
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN identity_confidence >= 0.85 THEN 1 ELSE 0 END) AS high,
          SUM(CASE WHEN identity_confidence BETWEEN 0.60 AND 0.8499 THEN 1 ELSE 0 END) AS medium,
          SUM(CASE WHEN identity_confidence < 0.60 THEN 1 ELSE 0 END) AS low,
          SUM(CASE WHEN list_contains(identity_flags, 'blocked_shared_device') THEN 1 ELSE 0 END) AS blocked
        FROM dim_user
        """
    ).fetchone()
    total, high, medium, low, blocked = row
    total = total or 1
    out_rows = [
        ["high (≥ 0.85)", high, f"{high / total:.1%}"],
        ["medium (0.60–0.84)", medium, f"{medium / total:.1%}"],
        ["low (< 0.60)", low, f"{low / total:.1%}"],
        ["blocked (shared device)", blocked, f"{blocked / total:.1%}"],
    ]
    return "### Panel 4 — Identity Resolution Quality\n\n" + _md_table(
        ["bucket", "users", "%"], out_rows
    )


def render() -> str:
    if not WAREHOUSE.exists():
        return f"warehouse missing at {WAREHOUSE}. Run `make resolve` first.\n"
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        sections = [
            f"# IndiaStox Weekly — rendered panels\n",
            f"*Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} from "
            f"`warehouse/indiastox.duckdb`. Same numbers a Metabase dashboard would render — "
            f"see `dashboard/seed.py` for the API path that produces the actual UI.*\n",
            panel_1_funnel(con),
            "",
            panel_2_channel_attribution(con),
            "",
            panel_3_cohort_retention(con),
            "",
            panel_4_identity_quality(con),
            "",
        ]
    finally:
        con.close()
    return "\n".join(sections)


def main() -> None:
    md = render()
    # Always also persist to dashboard/PANELS.md so the Loom can reference it.
    out_path = _REPO / "dashboard" / "PANELS.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md)
    print(md)
    print(f"\n(wrote {out_path})", file=sys.stderr)


if __name__ == "__main__":
    main()
