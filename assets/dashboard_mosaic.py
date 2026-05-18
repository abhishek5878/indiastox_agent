"""Render the four IndiaStox Weekly dashboard panels as a single 2x2 PNG.

Same SQL as `dashboard/render_panels.py` (which itself reads from
`metric_results` for the metric-layer panels). Both this script and
that one share the source-of-truth contract: dashboards are degraded
reads of the metric layer, never re-computations.

  make dashboard-mosaic
  open assets/dashboard_mosaic.png
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

WAREHOUSE = _REPO / "warehouse" / "indiastox.duckdb"
OUT = _REPO / "assets" / "dashboard_mosaic.png"

WEEK_START = datetime(2024, 1, 1, tzinfo=timezone.utc)
WEEK_END = WEEK_START + timedelta(days=7)


def _funnel(con) -> tuple[list[str], list[int]]:
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
          WHERE is_outcome_resolved AND user_id IN (SELECT user_id FROM predicted)
        )
        SELECT 'unstop_registered' AS step, (SELECT COUNT(*) FROM unstop_users) AS n
        UNION ALL SELECT 'challenge_signed_up', (SELECT COUNT(*) FROM signed_up)
        UNION ALL SELECT 'made_a_prediction',  (SELECT COUNT(*) FROM predicted)
        UNION ALL SELECT 'outcome_resolved',   (SELECT COUNT(*) FROM outcome)
        """
    ).fetchall()
    return [r[0] for r in rows], [int(r[1]) for r in rows]


def _channel_attribution(con) -> tuple[list[str], list[float]]:
    """Reads ghost_rate by source from metric_results (the materialization)."""
    rows = con.execute(
        """
        SELECT SPLIT_PART(breakdown_key, '=', 2), breakdown_value
        FROM metric_results
        WHERE metric_name = 'ghost_rate' AND breakdown_key LIKE 'by_source=%'
        ORDER BY breakdown_value DESC
        """
    ).fetchall()
    return [r[0] for r in rows], [float(r[1]) for r in rows]


def _cohort_retention(con) -> tuple[list[int], list[int], int]:
    rows = con.execute(
        """
        WITH cohort AS (
          SELECT DISTINCT user_id FROM dim_user
          WHERE signup_time >= ? AND signup_time < ?
        ),
        active_day AS (
          SELECT user_id, date_diff('day', ?, made_at) AS d
          FROM fact_prediction
          WHERE user_id IN (SELECT user_id FROM cohort)
        )
        SELECT d, COUNT(DISTINCT user_id) FROM active_day
        WHERE d BETWEEN 0 AND 6
        GROUP BY d ORDER BY d
        """,
        [WEEK_START, WEEK_END, WEEK_START],
    ).fetchall()
    cohort_n = con.execute(
        "SELECT COUNT(*) FROM dim_user WHERE signup_time >= ? AND signup_time < ?",
        [WEEK_START, WEEK_END],
    ).fetchone()[0]
    return [int(r[0]) for r in rows], [int(r[1]) for r in rows], int(cohort_n)


def _identity_quality(con) -> dict[str, float]:
    row = con.execute(
        """
        SELECT
          SUM(CASE WHEN identity_confidence >= 0.85 THEN 1 ELSE 0 END) AS high,
          SUM(CASE WHEN identity_confidence BETWEEN 0.60 AND 0.8499 THEN 1 ELSE 0 END) AS medium,
          SUM(CASE WHEN identity_confidence < 0.60 THEN 1 ELSE 0 END) AS low,
          SUM(CASE WHEN list_contains(identity_flags, 'blocked_shared_device') THEN 1 ELSE 0 END) AS blocked,
          COUNT(*) AS total
        FROM dim_user
        """
    ).fetchone()
    high, medium, low, blocked, total = [int(x) for x in row]
    return dict(high=high, medium=medium, low=low, blocked=blocked, total=total)


def render() -> None:
    if not WAREHOUSE.exists():
        print(f"ERROR: {WAREHOUSE} missing. Run `make resolve && make load`.", file=sys.stderr)
        sys.exit(2)

    con = duckdb.connect(str(WAREHOUSE), read_only=False)
    try:
        funnel_steps, funnel_n = _funnel(con)
        attr_sources, attr_rates = _channel_attribution(con)
        ret_days, ret_active, cohort_n = _cohort_retention(con)
        ident = _identity_quality(con)
    finally:
        con.close()

    fig, axes = plt.subplots(2, 2, figsize=(13, 10))
    fig.suptitle(
        "IndiaStox Weekly — four panels, live data\n"
        f"warehouse: {WAREHOUSE.name}   week_of: 2024-W01",
        fontsize=12, y=0.99, weight="bold",
    )

    # -- Panel 1: Funnel (top-left) --
    ax = axes[0, 0]
    colors = ["#1f77b4", "#3a8fb7", "#5fa8d3", "#86c5d8"]
    bars = ax.barh(funnel_steps[::-1], funnel_n[::-1], color=colors[::-1])
    total = funnel_n[0] or 1
    for bar, n in zip(bars, funnel_n[::-1]):
        ax.text(bar.get_width() + max(funnel_n) * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{n:,}  ({n / total:.0%})", va="center", fontsize=10)
    ax.set_xlim(0, max(funnel_n) * 1.25)
    ax.set_title("Panel 1 — Weekly Challenge Funnel (Unstop, strict-subset)", fontsize=11)
    ax.grid(axis="x", alpha=0.3)
    ax.spines["right"].set_visible(False)
    ax.spines["top"].set_visible(False)

    # -- Panel 2: Channel Attribution (top-right) — from metric_results --
    ax = axes[0, 1]
    if attr_sources:
        colors2 = ["#d62728" if r > 0.30 else "#2ca02c" if r < 0.20 else "#ff7f0e" for r in attr_rates]
        bars = ax.barh(attr_sources, attr_rates, color=colors2)
        for bar, r in zip(bars, attr_rates):
            ax.text(bar.get_width() + 0.005, bar.get_y() + bar.get_height() / 2,
                    f"{r:.1%}", va="center", fontsize=11, weight="bold")
        ax.set_xlim(0, max(attr_rates) * 1.25)
        ax.axvline(0.30, ls="--", lw=1, color="grey", alpha=0.6)
        ax.text(0.302, len(attr_sources) - 0.5, "concern\nthreshold 30%", fontsize=8, color="grey")
    ax.set_title("Panel 2 — Channel Attribution: ghost_rate by source\n(read from metric_results materialization)",
                 fontsize=11)
    ax.set_xlabel("ghost_rate (lower is better)")
    ax.grid(axis="x", alpha=0.3)
    ax.spines["right"].set_visible(False)
    ax.spines["top"].set_visible(False)

    # -- Panel 3: Cohort Retention (bottom-left) --
    ax = axes[1, 0]
    if ret_days:
        ax.bar(ret_days, ret_active, color="#9467bd", alpha=0.85, label="active users")
        ax2 = ax.twinx()
        pct = [a / cohort_n * 100 for a in ret_active]
        ax2.plot(ret_days, pct, marker="o", color="#2c2c2c", lw=2, label="% of cohort")
        ax2.set_ylabel("% of cohort", fontsize=10)
        ax2.set_ylim(0, max(pct) * 1.3)
        for d, n, p in zip(ret_days, ret_active, pct):
            ax2.text(d, p + max(pct) * 0.03, f"{p:.1f}%", ha="center", fontsize=8, color="#2c2c2c")
    ax.set_title(f"Panel 3 — Cohort Retention (W01 cohort, n={cohort_n})", fontsize=11)
    ax.set_xlabel("days since signup-week start")
    ax.set_ylabel("active users")
    ax.grid(axis="y", alpha=0.3)
    ax.spines["right"].set_visible(False)
    ax.spines["top"].set_visible(False)

    # -- Panel 4: Identity Resolution Quality donut (bottom-right) --
    ax = axes[1, 1]
    sizes = [ident["high"], ident["medium"], ident["low"]]
    labels = [
        f"high (≥0.85)\n{ident['high']:,} ({ident['high']/ident['total']:.1%})",
        f"medium (0.60–0.84)\n{ident['medium']:,} ({ident['medium']/ident['total']:.1%})",
        f"low (<0.60)\n{ident['low']:,} ({ident['low']/ident['total']:.1%})",
    ]
    colors4 = ["#2ca02c", "#ff7f0e", "#d62728"]
    wedges, _texts = ax.pie(sizes, labels=labels, colors=colors4, startangle=90,
                            wedgeprops=dict(width=0.45, edgecolor="white"), textprops=dict(fontsize=9))
    ax.text(0, 0, f"{ident['total']:,}\nusers\nresolved\n\n{ident['blocked']:,} blocked\n(shared device)",
            ha="center", va="center", fontsize=11, weight="bold")
    ax.set_title("Panel 4 — Identity Resolution Quality", fontsize=11)

    fig.text(
        0.01, 0.005,
        "Same SQL as dashboard/render_panels.py — Panel 2 reads metric_results; "
        "the others read fact_* directly. Numbers reproduce against `make resolve && make load`.",
        fontsize=8, color="#666",
    )

    plt.tight_layout(rect=(0, 0.02, 1, 0.96))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUT, dpi=140, bbox_inches="tight")
    print(f"wrote {OUT}  (4 panels: funnel={funnel_n}, attr_sources={attr_sources}, retention_days={len(ret_days)}, identity={ident})")


if __name__ == "__main__":
    render()
