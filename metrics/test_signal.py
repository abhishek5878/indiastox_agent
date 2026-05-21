"""Regression test for Layer N1 — real signal in synthetic data.

Asserts that the generator + identity resolver + Glicko-2 chain preserves
the hidden `true_skill` signal end-to-end. Three invariants:

  1. Glicko-2 mu correlates with the ground-truth true_skill (>= 0.30).
  2. Mean WIN-rate is monotonically increasing across true_skill quartiles.
  3. Top-quartile win rate exceeds bottom-quartile by >= 12 percentage points.

If any of these fails, either the generator stopped biasing outcomes, the
resolver dropped true_skill, or the Glicko-2 estimator broke.

Like the rest of `metrics/test_metrics.py`, these run against the live
warehouse — `make resolve && make skill` must have been run first.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
WAREHOUSE = REPO / "warehouse" / "indiastox.duckdb"
SKILL_PARQUET = REPO / "data" / "skill_ratings.parquet"

CORR_FLOOR = 0.30
TOP_VS_BOTTOM_PP = 0.12


@pytest.fixture(scope="module", autouse=True)
def _require_pipeline():
    if not WAREHOUSE.exists():
        pytest.skip("warehouse not built — run `make resolve` first")
    if not SKILL_PARQUET.exists():
        pytest.skip("skill_ratings not built — run `make skill` first")


@pytest.fixture(scope="module")
def true_skill_df() -> pd.DataFrame:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        return con.execute(
            "SELECT user_id, true_skill FROM dim_user WHERE true_skill IS NOT NULL"
        ).df()
    finally:
        con.close()


def test_true_skill_landed_in_dim_user(true_skill_df):
    """true_skill should be present + non-degenerate.

    Pre-P0.5 sampler was rng.gauss(0, 1); P0.5 swapped to an archetype-mix
    sampler whose theoretical population std ≈ 0.85 (computed from
    sum(weight_i * (mean_i² + std_i²)) - (sum(weight_i * mean_i))² across
    the 20 archetypes). Bounds [0.75, 1.15] cover both the legacy data
    (pre-regeneration) and the new archetype-mix data; assertion still
    catches all-zeros / broken sampling.
    """
    assert len(true_skill_df) >= 1900, f"only {len(true_skill_df)} dim_user rows carry true_skill"
    mean = true_skill_df["true_skill"].mean()
    std = true_skill_df["true_skill"].std()
    assert abs(mean) < 0.15, f"true_skill mean drifted: {mean:.3f}"
    assert 0.75 <= std <= 1.15, f"true_skill std out of band: {std:.3f}"


def test_glicko_mu_correlates_with_true_skill(true_skill_df):
    """The Glicko-2 estimator should recover at least 30% of the true_skill signal."""
    skill = pd.read_parquet(SKILL_PARQUET)
    merged = skill.merge(true_skill_df, on="user_id", how="inner")
    assert len(merged) >= 800, f"too few users in join: {len(merged)}"
    corr = float(merged["true_skill"].corr(merged["mu"]))
    assert corr >= CORR_FLOOR, (
        f"corr(true_skill, mu) = {corr:.3f}; expected >= {CORR_FLOOR}. "
        f"Either the generator stopped biasing outcomes or Glicko-2 broke."
    )


def test_win_rate_monotone_in_true_skill():
    """Walk skill quartiles; mean win rate must strictly increase."""
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        df = con.execute(
            """
            WITH per_user AS (
              SELECT du.user_id, du.true_skill,
                     SUM(CASE WHEN fp.outcome = 'WIN' THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS win_rate
              FROM dim_user du JOIN fact_prediction fp ON fp.user_id = du.user_id
              WHERE fp.is_outcome_resolved AND du.true_skill IS NOT NULL
              GROUP BY du.user_id, du.true_skill
              HAVING COUNT(*) >= 3
            ),
            q AS (
              SELECT *, NTILE(4) OVER (ORDER BY true_skill) AS quartile FROM per_user
            )
            SELECT quartile, AVG(win_rate) AS mean_win_rate
            FROM q GROUP BY quartile ORDER BY quartile
            """
        ).df()
    finally:
        con.close()

    rates = df["mean_win_rate"].tolist()
    assert len(rates) == 4, f"expected 4 quartiles, got {len(rates)}: {rates}"
    for i in range(1, 4):
        assert rates[i] > rates[i - 1], (
            f"win-rate not monotone: quartile {i + 1} ({rates[i]:.3f}) "
            f"<= quartile {i} ({rates[i - 1]:.3f})"
        )
    top_vs_bottom = rates[-1] - rates[0]
    assert top_vs_bottom >= TOP_VS_BOTTOM_PP, (
        f"top-quartile - bottom-quartile = {top_vs_bottom:.3f}; expected >= {TOP_VS_BOTTOM_PP}. "
        f"The signal is too weak to be useful."
    )
