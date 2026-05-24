"""Pytest tests for funnel_stages (P5).

Covers:
  - Stage structure: 4 ordered stages with required keys.
  - Strict-subset invariant: each stage n <= prior stage n.
  - Drop-off accounting: drop-off n at each gate equals
    (prior stage n - this stage n).
  - locked sub-count <= gyaani_aspirant stage n.
  - Headline value equals gyaani_aspirant n / signed_up n.
  - Cross-check against gyaani_aspirant_share: aspirant counts match.

Requires `make resolve && make skill` first (warehouse + parquet).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from metrics.definitions import (
    DEFS,
    GYAANI_RULE_VERSION,
    funnel_stages,
    gyaani_aspirant_share,
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


@pytest.fixture(scope="module")
def funnel():
    return funnel_stages()


def test_returns_four_stages(funnel) -> None:
    stages = funnel.breakdowns["stages"]
    assert len(stages) == 4
    names = [s["name"] for s in stages]
    assert names == [
        "signed_up", "made_first_call", "resolved_three_plus", "gyaani_aspirant",
    ]


def test_each_stage_has_required_keys(funnel) -> None:
    for s in funnel.breakdowns["stages"]:
        for k in ("name", "label", "n", "conversion_from_prior", "share_of_signup"):
            assert k in s, f"stage {s.get('name')} missing key {k}"


def test_stages_are_strictly_non_increasing(funnel) -> None:
    """Each stage is a strict subset of the prior — counts must monotonically
    decrease (or stay equal in pathological zero-cohort cases)."""
    ns = [s["n"] for s in funnel.breakdowns["stages"]]
    for i in range(1, len(ns)):
        assert ns[i] <= ns[i - 1], f"stage {i} n={ns[i]} > prior n={ns[i-1]}"


def test_drop_off_counts_account_for_attrition(funnel) -> None:
    """drop_off.after_X.n must equal (stage_before_X.n - stage_after_X.n)."""
    stages = funnel.breakdowns["stages"]
    drop = funnel.breakdowns["drop_off"]
    # signed_up (0) -> made_first_call (1)
    assert drop["after_signup"]["n"] == stages[0]["n"] - stages[1]["n"]
    # made_first_call (1) -> resolved_three_plus (2)
    assert drop["after_first_call"]["n"] == stages[1]["n"] - stages[2]["n"]
    # resolved_three_plus (2) -> gyaani_aspirant (3)
    assert drop["after_three_resolved"]["n"] == stages[2]["n"] - stages[3]["n"]


def test_locked_subcount_le_aspirant(funnel) -> None:
    locked = funnel.breakdowns["locked"]
    aspirant_n = funnel.breakdowns["stages"][3]["n"]
    assert locked <= aspirant_n, f"locked {locked} > aspirant {aspirant_n}"


def test_headline_matches_signup_to_aspirant_conversion(funnel) -> None:
    stages = funnel.breakdowns["stages"]
    signed = stages[0]["n"]
    aspirant = stages[3]["n"]
    expected = aspirant / signed if signed else 0.0
    assert funnel.value == pytest.approx(expected, rel=1e-9)


def test_conversion_from_prior_correct(funnel) -> None:
    stages = funnel.breakdowns["stages"]
    for i, s in enumerate(stages):
        prior = stages[i - 1]["n"] if i > 0 else s["n"]
        expected = (s["n"] / prior) if prior else 0.0
        assert s["conversion_from_prior"] == pytest.approx(expected, rel=1e-9)


def test_aspirant_count_consistent_with_gyaani_aspirant_share() -> None:
    """The funnel's aspirant stage count should equal what the standalone
    gyaani_aspirant_share metric reports, since both consult
    classify_gyaani on the same active cohort. They scope cohorts
    slightly differently (funnel uses acquisition_source='unstop' on
    dim_user; gyaani_aspirant_share uses 'active in week' on
    fact_prediction); the funnel's aspirant count should be <= the
    share metric's aspirant_or_locked count (acquisition narrowing).
    """
    funnel = funnel_stages()
    gas = gyaani_aspirant_share()
    funnel_aspirant = funnel.breakdowns["stages"][3]["n"]
    share_aspirant = gas.breakdowns["aspirant_or_locked"]
    assert funnel_aspirant <= share_aspirant, (
        f"funnel aspirant {funnel_aspirant} > share aspirant {share_aspirant}"
    )


def test_definition_version_matches_defs(funnel) -> None:
    assert funnel.definition_version == DEFS["funnel_stages"]


def test_funnel_registered_in_tool_layer() -> None:
    from mcp.tools import TOOLS
    assert "funnel_stages" in TOOLS
