"""Tests for agent.auto_proposal (P7b: insight -> Proposal adapter)."""
from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from agent.auto_proposal import (
    AUTO_PROPOSAL_VERSION,
    SURPRISE_FLOOR,
    _heuristic_lift_pct,
    _kind_to_metric,
    file_top_insight,
)
from agent.insights import Insight

REPO = Path(__file__).resolve().parents[1]
WAREHOUSE = REPO / "warehouse" / "indiastox.duckdb"


@pytest.fixture(scope="module", autouse=True)
def _require_pipeline():
    if not WAREHOUSE.exists():
        pytest.skip("warehouse not built — run `make resolve` first")


def test_heuristic_lift_pct_caps_to_kind() -> None:
    near = Insight(kind="near_miss_aspirant", subject="x", observed=0.0,
                   expected=1.0, surprise_score=0.5, summary="", suggested_experiment="")
    surprise = Insight(kind="archetype_design_surprise", subject="x", observed=0.0,
                       expected=1.0, surprise_score=0.5, summary="", suggested_experiment="")
    clog = Insight(kind="funnel_gate_clog", subject="x", observed=0.0,
                   expected=1.0, surprise_score=0.5, summary="", suggested_experiment="")
    assert _heuristic_lift_pct(near) == pytest.approx(5.0, abs=0.01)
    assert _heuristic_lift_pct(surprise) == pytest.approx(25.0, abs=0.01)
    assert _heuristic_lift_pct(clog) == pytest.approx(10.0, abs=0.01)


def test_kind_to_metric_mapping_covers_all_scanners() -> None:
    for kind in ("near_miss_aspirant", "archetype_design_surprise",
                 "funnel_gate_clog", "axis_outlier_mu"):
        assert _kind_to_metric(Insight(kind=kind, subject="x", observed=0,
                                        expected=0, surprise_score=0,
                                        summary="", suggested_experiment="")) != ""


def test_file_top_insight_skips_below_floor() -> None:
    """High floor -> no proposal filed."""
    result = file_top_insight(surprise_floor=0.99)
    assert result["filed"] is False
    assert "below floor" in result["reason"]
    assert result["proposal_id"] is None


def test_file_top_insight_files_above_floor() -> None:
    """Default floor -> proposal filed; new row visible in warehouse."""
    result = file_top_insight()
    assert result["filed"] is True
    pid = result["proposal_id"]
    assert pid and pid.startswith("PROP-")

    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        row = con.execute(
            "SELECT proposal_id, status, affected_metric FROM proposals WHERE proposal_id = ?",
            [pid],
        ).fetchone()
    finally:
        con.close()
    assert row is not None
    assert row[1] == "pending"
    # affected_metric must be one of the mapped targets
    assert row[2] in {"gyaani_locked_share", "gyaani_aspirant_share", "funnel_stages"}


def test_version_exposed() -> None:
    assert AUTO_PROPOSAL_VERSION
    assert SURPRISE_FLOOR > 0
