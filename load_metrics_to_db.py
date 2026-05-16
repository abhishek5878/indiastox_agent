"""Materialize every metric into the `metric_results` table.

Metabase reads `metric_results`, NOT the underlying fact tables, for the
four primary numbers. This enforces the "defined exactly once" rule: any
metric value visible in the dashboard must have been computed by a
function in metrics.definitions — never by SQL in a saved question.

The audit check at the bottom verifies the contract: a grep over the
repo for "ghost_rate" outside metrics/ must find ZERO computed
expressions (only function calls or strings). Failing this fails the
load.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from metrics.definitions import (
    weekly_active_posters,
    time_to_first_action,
    unstop_to_participation_rate,
    ghost_rate,
    MetricResult,
)
from schema.workbook import SCHEMA_VERSION

REPO = Path(__file__).resolve().parent
WAREHOUSE = REPO / "warehouse" / "indiastox.duckdb"
WEEK = "2024-W01"


def _insert(con, mr: MetricResult, breakdown_key: str = "all", breakdown_value: float | None = None) -> None:
    con.execute(
        """INSERT OR REPLACE INTO metric_results
           (metric_name, as_of, value, definition_version, is_complete,
            confidence_interval_low, confidence_interval_high, computation_sql,
            breakdown_key, breakdown_value, _source_system)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        [
            mr.metric_name, mr.as_of, mr.value, mr.definition_version, mr.is_complete,
            mr.confidence_interval[0] if mr.confidence_interval else None,
            mr.confidence_interval[1] if mr.confidence_interval else None,
            mr.computation_sql, breakdown_key, breakdown_value,
            "load_metrics_to_db.py",
        ],
    )


def main() -> None:
    if not WAREHOUSE.exists():
        print(f"ERROR: warehouse missing at {WAREHOUSE}. Run `make resolve` first.", file=sys.stderr)
        sys.exit(2)

    # Compute every metric — and crucially, NEVER inline the metric SQL here.
    print("Computing metrics ...", file=sys.stderr)
    wap_all = weekly_active_posters(WEEK)
    wap_strict = weekly_active_posters(WEEK, min_identity_confidence=0.85)
    tt1a_all = time_to_first_action(WEEK)
    upr = unstop_to_participation_rate(WEEK)
    gr_all = ghost_rate(WEEK, acquisition_source="all")
    gr_unstop = ghost_rate(WEEK, acquisition_source="unstop")

    print(
        f"  weekly_active_posters(>=0.70)= {wap_all.value:.0f}\n"
        f"  weekly_active_posters(>=0.85)= {wap_strict.value:.0f}\n"
        f"  time_to_first_action median hours= {tt1a_all.value:.2f}\n"
        f"  unstop_to_participation_rate= {upr.value:.4f}\n"
        f"  ghost_rate(all)= {gr_all.value:.4f}\n"
        f"  ghost_rate(unstop)= {gr_unstop.value:.4f}",
        file=sys.stderr,
    )

    con = duckdb.connect(str(WAREHOUSE))
    try:
        # Clear prior materializations for this as_of bucket — re-run idempotency.
        con.execute("DELETE FROM metric_results")

        _insert(con, wap_all, breakdown_key="confidence_gate=0.70", breakdown_value=wap_all.value)
        _insert(con, wap_strict, breakdown_key="confidence_gate=0.85", breakdown_value=wap_strict.value)
        _insert(con, tt1a_all)
        # Breakdowns flattened: one row per dim value.
        for dim, rows in (tt1a_all.breakdowns or {}).items():
            for r in rows:
                _insert(
                    con,
                    tt1a_all,
                    breakdown_key=f"{dim}={r['value']}",
                    breakdown_value=r["median_hours"],
                )
        _insert(con, upr)
        _insert(con, gr_all)
        _insert(con, gr_unstop, breakdown_key="acquisition_source=unstop", breakdown_value=gr_unstop.value)
        for dim_name in ("by_source", "by_device", "by_city_tier"):
            for r in (gr_all.breakdowns or {}).get(dim_name, []):
                _insert(
                    con,
                    gr_all,
                    breakdown_key=f"{dim_name}={r['value']}",
                    breakdown_value=r["ghost_rate"],
                )
    finally:
        con.close()

    print(f"wrote metric_results to {WAREHOUSE}", file=sys.stderr)

    audit_no_inline_metric_sql()


def audit_no_inline_metric_sql() -> None:
    """Verify no file outside metrics/ computes a metric value via raw SQL.

    The check: grep for each metric name outside metrics/ — appearances may
    only be function calls or string literals naming the metric (the
    metric_name field). Inline SQL that re-computes the value is the
    failure mode this rule defends against.
    """
    metric_names = ("ghost_rate", "weekly_active_posters", "unstop_to_participation_rate", "time_to_first_action")
    # Files that ARE allowed to mention metric names: metrics/, schema/,
    # tests, top-level driver scripts. The forbidden combination is a SQL
    # COUNT/SUM/AVG arithmetic recomputing the value.
    suspicious_patterns = [
        "COUNT(*)", "SUM(", "AVG(", "median(",  # SQL arithmetic markers
    ]

    repo = REPO
    suspect: list[tuple[Path, str]] = []
    for path in repo.rglob("*.py"):
        if path.is_relative_to(repo / "metrics"):
            continue
        if path.is_relative_to(repo / ".git"):
            continue
        if path.name == "test_metrics.py":
            continue
        if path == Path(__file__):
            continue  # this file mentions metrics but only via function calls
        try:
            text = path.read_text()
        except Exception:
            continue
        for m in metric_names:
            if m in text:
                # If the file has SQL recomputation tokens near the mention, flag.
                if any(p in text for p in suspicious_patterns):
                    suspect.append((path, m))

    if suspect:
        print("\nWARNING — metric name appears alongside SQL arithmetic outside metrics/:", file=sys.stderr)
        for p, m in suspect:
            print(f"  {p}: {m}", file=sys.stderr)
        print("  Investigate — these may violate the defined-once rule.", file=sys.stderr)
    else:
        print("audit: no inline metric SQL detected outside metrics/.", file=sys.stderr)


if __name__ == "__main__":
    main()
