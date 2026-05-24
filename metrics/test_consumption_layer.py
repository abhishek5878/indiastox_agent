"""Pytest tests for the consumption-layer metrics: nudge_targets and
user_fingerprint. These are the two metrics the consumption-layer pages
(/cs-nudges, /fingerprint) call directly.

Both must satisfy the MetricResult contract + carry the rich
breakdowns the frontends expect; broken contracts here surface as
silent page-render bugs.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from metrics.definitions import (
    DEFS,
    GYAANI_THRESHOLDS,
    nudge_targets,
    user_fingerprint,
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
# nudge_targets
# ---------------------------------------------------------------------------


def test_nudge_targets_returns_valid_metric_result() -> None:
    m = nudge_targets(top_n=5)
    assert m.metric_name == "nudge_targets"
    assert m.definition_version == DEFS["nudge_targets"]
    assert m.sample_n >= 0
    assert "targets" in m.breakdowns
    assert m.value == float(len(m.breakdowns["targets"]))


def test_nudge_targets_respects_top_n() -> None:
    m = nudge_targets(top_n=3)
    assert len(m.breakdowns["targets"]) <= 3


def test_nudge_targets_sorted_by_gap_score_ascending() -> None:
    """Closer-to-locked users surface first."""
    m = nudge_targets(top_n=20)
    scores = [t["gap_score"] for t in m.breakdowns["targets"]]
    assert scores == sorted(scores), "nudge targets not sorted by gap_score asc"


def test_nudge_targets_only_aspirant_tier() -> None:
    """Only aspirant users should be candidates — locked are already there;
    none-tier users are too far."""
    m = nudge_targets(top_n=50)
    for t in m.breakdowns["targets"]:
        assert t["tier"] == "aspirant", f"non-aspirant in nudge targets: {t['tier']}"


def test_nudge_targets_biggest_gap_axis_is_valid() -> None:
    m = nudge_targets(top_n=30)
    for t in m.breakdowns["targets"]:
        assert t["biggest_gap_axis"] in ("calls", "mu", "phi")


def test_nudge_targets_registered_in_tool_layer() -> None:
    from mcp.tools import TOOLS
    assert "nudge_targets" in TOOLS


# ---------------------------------------------------------------------------
# user_fingerprint
# ---------------------------------------------------------------------------


def _pick_a_real_user() -> str:
    """Pick any user_id that the warehouse knows about, for fingerprint
    tests. Uses nudge_targets so the result is non-trivial (an aspirant
    user — they have Gyaani status, axes, segment all populated)."""
    m = nudge_targets(top_n=1)
    targets = m.breakdowns["targets"]
    if not targets:
        pytest.skip("no nudge targets in warehouse to fingerprint")
    return targets[0]["user_id"]


def test_user_fingerprint_returns_valid_metric_result() -> None:
    uid = _pick_a_real_user()
    m = user_fingerprint(uid)
    assert m.metric_name == "user_fingerprint"
    assert m.definition_version == DEFS["user_fingerprint"]
    assert m.sample_n == 1
    for k in ("gyaani", "reward_axes", "behavior_segment", "identity", "tier_rank"):
        assert k in m.breakdowns


def test_user_fingerprint_value_matches_tier_rank() -> None:
    uid = _pick_a_real_user()
    m = user_fingerprint(uid)
    tier = m.breakdowns["gyaani"]["tier"]
    expected = {"none": 0, "aspirant": 1, "locked": 2}[tier]
    assert m.value == float(expected)


def test_user_fingerprint_aspirant_has_valid_gaps() -> None:
    uid = _pick_a_real_user()
    m = user_fingerprint(uid)
    g = m.breakdowns["gyaani"]
    if g["tier"] != "aspirant":
        pytest.skip("picked user is not aspirant")
    gaps = g["gaps_to_locked"]
    # An aspirant must be short on at least one locked threshold by definition.
    short = (
        (gaps["calls_short_by"] or 0) > 0
        or (gaps["mu_short_by"] or 0) > 0
        or (gaps["phi_excess"] or 0) > 0
    )
    assert short, "aspirant user reports no gap to locked"


def test_user_fingerprint_unknown_user_returns_none_tier() -> None:
    m = user_fingerprint("not-a-real-user-uuid-xxxxxxxxxxxxxxxx")
    assert m.breakdowns["gyaani"]["tier"] == "none"
    assert m.value == 0.0


def test_user_fingerprint_registered_in_tool_layer() -> None:
    from mcp.tools import TOOLS
    assert "user_fingerprint" in TOOLS
