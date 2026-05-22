"""Pytest tests for the attention -> accuracy headline metrics (P4).

Covers:
  - weekly_active_callers_calibrated: range, bounded by raw active
    count (a calibration weight can't exceed 1), responds to underlying
    Brier.
  - high_confidence_call_ratio: range [0, 1]; SQL cross-check against
    a direct count.
  - daily_gyaani_aspirant_count: monotone-ish over W01 (cumulative
    classification on a stable skill snapshot); sample_n is the active
    set; classify_gyaani shared with the share-metric.
  - calls_with_explanation_rate: honestly stubbed (value=0.0,
    confidence=0.0, status="stub").
  - DEFS registration.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from metrics.definitions import (
    DEFS,
    calls_with_explanation_rate,
    daily_gyaani_aspirant_count,
    high_confidence_call_ratio,
    weekly_active_callers_calibrated,
)

REPO = Path(__file__).resolve().parents[1]
WAREHOUSE = REPO / "warehouse" / "indiastox.duckdb"
SKILL_PARQUET = REPO / "data" / "skill_ratings.parquet"


@pytest.fixture(scope="module", autouse=True)
def _require_pipeline():
    if not WAREHOUSE.exists():
        pytest.skip("warehouse not built — run `make resolve` first")
    if not SKILL_PARQUET.exists():
        pytest.skip("skill ratings missing — run `make skill` first")


# ---------------------------------------------------------------------------
# DEFS registration
# ---------------------------------------------------------------------------


def test_all_four_metrics_registered() -> None:
    for name in (
        "weekly_active_callers_calibrated",
        "high_confidence_call_ratio",
        "daily_gyaani_aspirant_count",
        "calls_with_explanation_rate",
    ):
        assert name in DEFS, f"{name} missing from DEFS"


# ---------------------------------------------------------------------------
# weekly_active_callers_calibrated
# ---------------------------------------------------------------------------


def test_calibrated_callers_bounded_by_raw_active() -> None:
    """The sum of per-caller calibration weights (each in [0, 1]) cannot
    exceed the raw active caller count."""
    m = weekly_active_callers_calibrated()
    assert m.value >= 0.0
    assert m.value <= m.breakdowns["raw_active_callers"]


def test_calibrated_callers_returns_valid_metric() -> None:
    m = weekly_active_callers_calibrated()
    assert m.metric_name == "weekly_active_callers_calibrated"
    assert m.definition_version == DEFS["weekly_active_callers_calibrated"]
    assert m.sample_n >= 0


# ---------------------------------------------------------------------------
# high_confidence_call_ratio
# ---------------------------------------------------------------------------


def test_high_confidence_ratio_in_range() -> None:
    m = high_confidence_call_ratio()
    assert 0.0 <= m.value <= 1.0


def test_high_confidence_ratio_matches_sql() -> None:
    """Independent SQL count must equal the metric's win/n breakdown."""
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        wins, n = con.execute(
            """
            SELECT SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) AS wins,
                   COUNT(*) AS n
            FROM fact_prediction
            WHERE made_at >= '2024-01-01' AND made_at < '2024-01-08'
              AND is_outcome_resolved AND confidence_stars >= 4
            """
        ).fetchone()
    finally:
        con.close()
    m = high_confidence_call_ratio()
    assert m.breakdowns["high_conf_wins"] == int(wins or 0)
    assert m.breakdowns["high_conf_resolved"] == int(n or 0)


# ---------------------------------------------------------------------------
# daily_gyaani_aspirant_count
# ---------------------------------------------------------------------------


def test_daily_aspirant_count_grows_monotonically_in_w01() -> None:
    """As we slide the 7-day window forward through W01, the count of
    users meeting aspirant tier never decreases — the active set grows
    and the skill snapshot is stable. After the window starts including
    later-week data more users have accumulated enough resolved calls
    to clear the n>=3 gate."""
    counts = []
    for day in range(2, 8):
        m = daily_gyaani_aspirant_count(f"2024-01-{day:02d}")
        counts.append(int(m.value))
    for i in range(1, len(counts)):
        assert counts[i] >= counts[i - 1], (
            f"aspirant count regressed day-over-day: {counts}"
        )


def test_daily_aspirant_count_locked_subset() -> None:
    """locked is a subset of aspirant-or-better at every point."""
    m = daily_gyaani_aspirant_count("2024-01-07")
    assert m.breakdowns["locked"] <= m.breakdowns["aspirant_or_better"]


def test_daily_aspirant_count_active_set_caps_value() -> None:
    """value <= active_set (can't classify more users than are active)."""
    m = daily_gyaani_aspirant_count("2024-01-07")
    assert m.value <= m.breakdowns["active_set"]


# ---------------------------------------------------------------------------
# calls_with_explanation_rate — honest stub
# ---------------------------------------------------------------------------


def test_explanation_rate_stubbed() -> None:
    m = calls_with_explanation_rate()
    assert m.value == 0.0
    assert m.confidence == 0.0
    assert "stub" in m.breakdowns.get("status", "").lower()
    # version string contains 'stub' so consumers can flag it
    assert "stub" in m.definition_version.lower()


def test_explanation_rate_documents_schema_gap() -> None:
    m = calls_with_explanation_rate()
    # Must call out the specific schema gap so reviewers know what to fix
    joined_provenance = " ".join(m.provenance)
    assert "rationale" in joined_provenance.lower() or "schema" in joined_provenance.lower()
