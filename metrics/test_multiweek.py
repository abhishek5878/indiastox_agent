"""Pytest tests for P0.5b multi-week verification metrics:
recovery_arc_evidence + activation_cohort_lift.

Both require multi-week data (run `make multiweek` first). Tests gate
themselves on a multi-week-detection probe so single-week-only checkouts
skip cleanly rather than fail.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from metrics.definitions import (
    DEFS,
    activation_cohort_lift,
    recovery_arc_evidence,
)

REPO = Path(__file__).resolve().parents[1]
WAREHOUSE = REPO / "warehouse" / "indiastox.duckdb"


def _has_multiweek_data() -> bool:
    if not WAREHOUSE.exists():
        return False
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM fact_prediction WHERE made_at >= '2024-01-08'"
        ).fetchone()[0]
    finally:
        con.close()
    return n > 100


@pytest.fixture(scope="module", autouse=True)
def _require_multiweek():
    if not _has_multiweek_data():
        pytest.skip("multi-week data missing — run `make multiweek` to enable P0.5b tests")


# ---------------------------------------------------------------------------
# recovery_arc_evidence
# ---------------------------------------------------------------------------


def test_recovery_arc_returns_valid_metric_result() -> None:
    m = recovery_arc_evidence("2024-W01", "2024-W02")
    assert m.metric_name == "recovery_arc_evidence"
    assert m.definition_version == DEFS["recovery_arc_evidence"]
    assert 0.0 <= m.value <= 1.0
    assert m.sample_n >= 0
    for k in ("recovery_cohort_size", "tier_ups", "aspirant_after",
              "locked_after", "examples"):
        assert k in m.breakdowns


def test_recovery_arc_cohort_size_matches_breakdown() -> None:
    m = recovery_arc_evidence("2024-W01", "2024-W02")
    assert m.sample_n == m.breakdowns["recovery_cohort_size"]


def test_recovery_arc_fires_on_w01_w02() -> None:
    """On the substrate's multi-week data, at least SOME users should
    show the bad→strong → tier-up pattern. Zero would mean the rule
    is broken or the data has no recovery-streaker variance."""
    m = recovery_arc_evidence("2024-W01", "2024-W02")
    assert m.sample_n > 0, "no users had a bad→strong streak across W01→W02 — substrate variance check"
    assert m.breakdowns["tier_ups"] > 0, "no recovery-streakers tier'd up — the Gyaani rule may be broken"


def test_recovery_arc_tier_ups_le_cohort() -> None:
    m = recovery_arc_evidence("2024-W01", "2024-W02")
    assert m.breakdowns["tier_ups"] <= m.breakdowns["recovery_cohort_size"]


def test_recovery_arc_registered_in_tool_layer() -> None:
    from mcp.tools import TOOLS
    assert "recovery_arc_evidence" in TOOLS


# ---------------------------------------------------------------------------
# activation_cohort_lift
# ---------------------------------------------------------------------------


def test_activation_lift_returns_valid_metric_result() -> None:
    m = activation_cohort_lift("2024-W01", "2024-W02")
    assert m.metric_name == "activation_cohort_lift"
    assert m.definition_version == DEFS["activation_cohort_lift"]
    assert m.value >= 0.0
    for k in ("features", "cohort_size", "baseline_retention", "top_feature"):
        assert k in m.breakdowns


def test_activation_lift_features_sorted_desc() -> None:
    m = activation_cohort_lift("2024-W01", "2024-W02")
    lifts = [f["lift"] for f in m.breakdowns["features"]]
    assert lifts == sorted(lifts, reverse=True), "features not sorted by lift desc"


def test_activation_lift_top_feature_lift_ge_one() -> None:
    """The top feature must show non-negative lift (≥1.0× baseline).
    A feature with lift <1 is anti-predictive — surfacing it would be
    misleading, so the sort + top extraction should never put one first
    if any feature has lift ≥1."""
    m = activation_cohort_lift("2024-W01", "2024-W02")
    if m.breakdowns["features"]:
        assert m.breakdowns["features"][0]["lift"] >= 1.0, (
            "top activation feature is anti-predictive — bug in feature set"
        )


def test_activation_lift_registered_in_tool_layer() -> None:
    from mcp.tools import TOOLS
    assert "activation_cohort_lift" in TOOLS
