"""Pytest tests for the insights extractor (P7).

Covers:
  - Insight dataclass shape: required fields, score range, types.
  - Scanner independence: each scanner returns valid list (or empty)
    on the live W01 substrate.
  - Ranking invariant: generate_insights returns surprise_score-desc
    sorted list.
  - Metric wrapper: insights_generate returns valid MetricResult;
    `value` matches top insight's surprise_score; breakdowns carry
    the full list.
  - Registration: insights_generate is in DEFS and TOOLS.
  - Substrate sanity: at least one near_miss_aspirant insight should
    exist on W01 (the substrate has known near-miss day_traders).

Requires `make resolve && make skill` first (warehouse + parquet).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.insights import (
    INSIGHTS_VERSION,
    Insight,
    _SCANNERS,
    _load_population,
    generate_insights,
    scan_archetype_design_surprise,
    scan_axis_outliers,
    scan_funnel_gate_clog,
    scan_near_miss_aspirants,
)
from metrics.definitions import DEFS, insights_generate

REPO = Path(__file__).resolve().parents[1]
WAREHOUSE = REPO / "warehouse" / "indiastox.duckdb"
SKILL_PARQUET = REPO / "data" / "skill_ratings.parquet"


@pytest.fixture(scope="module", autouse=True)
def _require_pipeline():
    if not WAREHOUSE.exists():
        pytest.skip("warehouse not built — run `make resolve` first")
    if not SKILL_PARQUET.exists():
        pytest.skip("skill ratings missing — run `make skill` first")


@pytest.fixture(scope="module")
def rows():
    return _load_population("2024-W01")


@pytest.fixture(scope="module")
def insights():
    return generate_insights("2024-W01")


# ---------------------------------------------------------------------------
# Insight dataclass invariants
# ---------------------------------------------------------------------------


def test_insights_are_insight_instances(insights) -> None:
    assert len(insights) > 0
    for ins in insights:
        assert isinstance(ins, Insight)


def test_all_surprise_scores_in_unit_range(insights) -> None:
    for ins in insights:
        assert 0.0 <= ins.surprise_score <= 1.0, (
            f"surprise_score out of range: {ins.surprise_score} for {ins.kind}"
        )


def test_all_summaries_non_empty(insights) -> None:
    for ins in insights:
        assert ins.summary, f"empty summary on {ins.kind}/{ins.subject}"
        assert ins.suggested_experiment, f"empty experiment on {ins.kind}/{ins.subject}"


def test_insights_sorted_descending_by_surprise(insights) -> None:
    scores = [i.surprise_score for i in insights]
    assert scores == sorted(scores, reverse=True), "insights not sorted by surprise desc"


# ---------------------------------------------------------------------------
# Scanner independence — each returns a list (possibly empty) without throwing
# ---------------------------------------------------------------------------


def test_scanner_dispatch_table_consistent() -> None:
    """Dispatch table is the single source of truth — every scanner
    function should be reachable by exactly one canonical name."""
    assert "near_miss_aspirant" in _SCANNERS
    assert "archetype_design_surprise" in _SCANNERS
    assert "funnel_gate_clog" in _SCANNERS
    assert "axis_outlier_mu" in _SCANNERS


def test_near_miss_aspirant_returns_list(rows) -> None:
    out = scan_near_miss_aspirants(rows, "2024-W01")
    assert isinstance(out, list)
    for ins in out:
        assert ins.kind == "near_miss_aspirant"


def test_archetype_design_surprise_returns_list(rows) -> None:
    out = scan_archetype_design_surprise(rows, "2024-W01")
    assert isinstance(out, list)
    for ins in out:
        assert ins.kind == "archetype_design_surprise"


def test_funnel_gate_clog_returns_list(rows) -> None:
    out = scan_funnel_gate_clog(rows, "2024-W01")
    assert isinstance(out, list)
    for ins in out:
        assert ins.kind == "funnel_gate_clog"


def test_axis_outliers_returns_list(rows) -> None:
    out = scan_axis_outliers(rows, "2024-W01")
    assert isinstance(out, list)
    for ins in out:
        assert ins.kind == "axis_outlier_mu"


# ---------------------------------------------------------------------------
# Substrate sanity — the W01 data has known signal each scanner should hit
# ---------------------------------------------------------------------------


def test_w01_has_near_miss_aspirants(rows) -> None:
    """Smoke-test that the substrate produces at least one near-miss
    aspirant — day_traders mu-short of locked is a known pattern."""
    out = scan_near_miss_aspirants(rows, "2024-W01")
    assert len(out) > 0, "no near-miss aspirants on W01 — substrate may have regressed"


def test_w01_has_archetype_design_surprises(rows) -> None:
    """Smoke-test: at least one archetype should diverge from design
    expectation. P2 audit already documented 5 zero-aspirant cohorts."""
    out = scan_archetype_design_surprise(rows, "2024-W01")
    assert len(out) > 0
    # And at least one of the known underperformers should appear.
    known_underperformers = {"anchored_conservative", "diversifier_index_investor",
                             "weekend_casual", "lurker_turned_caller", "pharma_doctor",
                             "skeptic"}
    surfaced = {i.subject for i in out}
    assert surfaced & known_underperformers, (
        f"none of the known underperformers surfaced: got {surfaced}"
    )


# ---------------------------------------------------------------------------
# Metric wrapper
# ---------------------------------------------------------------------------


def test_metric_wrapper_returns_valid_result() -> None:
    m = insights_generate(top_n=10)
    assert m.metric_name == "insights_generate"
    assert m.definition_version == DEFS["insights_generate"]
    assert 0.0 <= m.value <= 1.0
    assert m.sample_n >= 0
    assert "insights" in m.breakdowns
    assert "by_kind" in m.breakdowns
    assert m.breakdowns["insights_version"] == INSIGHTS_VERSION


def test_metric_value_equals_top_insight_score() -> None:
    m = insights_generate(top_n=10)
    if m.sample_n == 0:
        assert m.value == 0.0
    else:
        top_score = m.breakdowns["insights"][0]["surprise_score"]
        assert m.value == pytest.approx(top_score, rel=1e-9)


def test_metric_top_n_caps_breakdown_size() -> None:
    m = insights_generate(top_n=3)
    assert len(m.breakdowns["insights"]) <= 3


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_metric_in_defs() -> None:
    assert "insights_generate" in DEFS


def test_metric_registered_in_tool_layer() -> None:
    from mcp.tools import TOOLS
    assert "insights_generate" in TOOLS
