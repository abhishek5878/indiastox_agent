"""Pytest tests for the two-tier Gyaani definition (P1).

Covers:
  - classify_gyaani: pure function correctness at every threshold boundary.
  - locked ⊂ aspirant: structural invariant. Any locked user is also
    aspirant by construction.
  - gyaani_aspirant_share + gyaani_locked_share: end-to-end on the live
    warehouse. Returns valid MetricResults; population sizes line up
    against direct SQL; no overlap pathology.
  - gyaani_status: per-user gaps math is correct; tier matches
    classify_gyaani on the same inputs; unknown user returns tier="none".
  - DEFS registration: both metrics carry an entry; rule version exposed.

Like the rest of `metrics/test_metrics.py`, these tests hit a real
DuckDB warehouse (`make resolve && make skill` must have run first).
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from metrics.definitions import (
    DEFS,
    GYAANI_RULE_VERSION,
    GYAANI_THRESHOLDS,
    classify_gyaani,
    gyaani_aspirant_share,
    gyaani_locked_share,
    gyaani_status,
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
# Pure-function tests
# ---------------------------------------------------------------------------


def test_classify_aspirant_at_each_boundary() -> None:
    t = GYAANI_THRESHOLDS["aspirant"]
    # Exact floor passes
    assert classify_gyaani(t["mu_min"], t["phi_max"] - 0.001, t["n_resolved_min"]) == "aspirant"
    # mu just under fails
    assert classify_gyaani(t["mu_min"] - 0.001, t["phi_max"] - 1, t["n_resolved_min"]) == "none"
    # phi at the ceiling fails (strict <)
    assert classify_gyaani(t["mu_min"], t["phi_max"], t["n_resolved_min"]) == "none"
    # n short fails
    assert classify_gyaani(t["mu_min"], t["phi_max"] - 1, t["n_resolved_min"] - 1) == "none"


def test_classify_locked_at_each_boundary() -> None:
    t = GYAANI_THRESHOLDS["locked"]
    assert classify_gyaani(t["mu_min"], t["phi_max"] - 0.001, t["n_resolved_min"]) == "locked"
    # Just under any single locked threshold falls back to aspirant (if aspirant gate passes)
    assert classify_gyaani(t["mu_min"], t["phi_max"] - 0.001, t["n_resolved_min"] - 1) == "aspirant"
    assert classify_gyaani(t["mu_min"] - 0.001, t["phi_max"] - 0.001, t["n_resolved_min"]) == "aspirant"


def test_locked_is_subset_of_aspirant() -> None:
    """Structural invariant: any input that classifies as 'locked' would
    also classify as 'aspirant' if the locked thresholds were ignored.

    This guards against a future refactor accidentally tightening
    aspirant beyond locked.
    """
    locked_t = GYAANI_THRESHOLDS["locked"]
    asp_t = GYAANI_THRESHOLDS["aspirant"]
    assert locked_t["mu_min"] >= asp_t["mu_min"]
    assert locked_t["phi_max"] <= asp_t["phi_max"]
    assert locked_t["n_resolved_min"] >= asp_t["n_resolved_min"]


def test_classify_returns_one_of_three() -> None:
    """Sanity: the classifier never returns anything unexpected. Walk
    a grid of mu/phi/n values."""
    for mu in (1000, 1500, 1700, 1900):
        for phi in (100, 150, 200, 250):
            for n in (0, 3, 10, 20):
                assert classify_gyaani(mu, phi, n) in ("locked", "aspirant", "none")


# ---------------------------------------------------------------------------
# Warehouse-backed metric tests
# ---------------------------------------------------------------------------


def test_aspirant_share_returns_valid_metric_result() -> None:
    m = gyaani_aspirant_share()
    assert 0.0 <= m.value <= 1.0
    assert m.metric_name == "gyaani_aspirant_share"
    assert m.definition_version == DEFS["gyaani_aspirant_share"]
    assert m.sample_n > 0
    assert "aspirant_or_locked" in m.breakdowns
    assert m.breakdowns["aspirant_or_locked"] <= m.breakdowns["cohort_size"]


def test_locked_share_returns_valid_metric_result() -> None:
    m = gyaani_locked_share()
    assert 0.0 <= m.value <= 1.0
    assert m.metric_name == "gyaani_locked_share"
    assert m.definition_version == DEFS["gyaani_locked_share"]
    assert m.sample_n > 0
    assert m.breakdowns["locked"] <= m.breakdowns["cohort_size"]


def test_locked_share_le_aspirant_share() -> None:
    """Population-level invariant: locked-tier population is a subset of
    aspirant-tier population. The shares cannot disagree.
    """
    asp = gyaani_aspirant_share()
    lkd = gyaani_locked_share()
    assert asp.sample_n == lkd.sample_n, "cohort sizes drifted between metrics"
    assert lkd.breakdowns["locked"] <= asp.breakdowns["aspirant_or_locked"]
    assert lkd.value <= asp.value


def test_aspirant_metric_independent_count_matches_sql() -> None:
    """Cross-check: count users meeting the aspirant rule via raw SQL on
    the warehouse + parquet. Must equal the metric's breakdown.
    """
    t = GYAANI_THRESHOLDS["aspirant"]
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        n = con.execute(
            f"""
            WITH active AS (
              SELECT user_id,
                     SUM(CASE WHEN is_outcome_resolved THEN 1 ELSE 0 END) AS n_resolved
              FROM fact_prediction
              WHERE made_at >= '2024-01-01' AND made_at < '2024-01-08'
              GROUP BY user_id
            )
            SELECT COUNT(*)
            FROM active a
            JOIN read_parquet('{SKILL_PARQUET}') s ON s.user_id = a.user_id
            WHERE s.mu >= ? AND s.phi < ? AND a.n_resolved >= ?
            """,
            [t["mu_min"], t["phi_max"], t["n_resolved_min"]],
        ).fetchone()[0]
    finally:
        con.close()

    m = gyaani_aspirant_share()
    assert m.breakdowns["aspirant_or_locked"] == n, (
        f"SQL count {n} != metric breakdown {m.breakdowns['aspirant_or_locked']}"
    )


# ---------------------------------------------------------------------------
# gyaani_status tool tests
# ---------------------------------------------------------------------------


def test_status_unknown_user_returns_none_tier() -> None:
    st = gyaani_status("nonexistent-user-id-xxxxxxxxxxxxxxxxxxx")
    assert st["tier"] == "none"
    assert st["mu"] is None
    assert st["phi"] is None
    assert st["n_resolved"] == 0
    assert st["rule_version"] == GYAANI_RULE_VERSION


def test_status_tier_matches_classify_on_same_inputs() -> None:
    """For each user in dim_user with skill ratings, gyaani_status() must
    return the same tier as classify_gyaani(mu, phi, n) directly.
    """
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        rows = con.execute(
            f"""
            WITH active AS (
              SELECT user_id,
                     SUM(CASE WHEN is_outcome_resolved THEN 1 ELSE 0 END) AS n_resolved
              FROM fact_prediction
              WHERE made_at >= '2024-01-01' AND made_at < '2024-01-08'
              GROUP BY user_id
            )
            SELECT a.user_id, s.mu, s.phi, a.n_resolved
            FROM active a
            JOIN read_parquet('{SKILL_PARQUET}') s ON s.user_id = a.user_id
            ORDER BY a.user_id
            LIMIT 25
            """
        ).fetchall()
    finally:
        con.close()
    assert len(rows) > 0
    for uid, mu, phi, n in rows:
        expected = classify_gyaani(float(mu), float(phi), int(n))
        st = gyaani_status(uid)
        assert st["tier"] == expected, (
            f"status tier {st['tier']} != classify {expected} for {uid} "
            f"(mu={mu}, phi={phi}, n={n})"
        )


def test_status_gaps_correct() -> None:
    """gaps_to_locked components must reflect mu_min - mu, phi - phi_max,
    n_min - n_resolved (each clipped at zero).
    """
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        row = con.execute(
            f"""
            WITH active AS (
              SELECT user_id,
                     SUM(CASE WHEN is_outcome_resolved THEN 1 ELSE 0 END) AS n_resolved
              FROM fact_prediction
              WHERE made_at >= '2024-01-01' AND made_at < '2024-01-08'
              GROUP BY user_id
            )
            SELECT a.user_id, s.mu, s.phi, a.n_resolved
            FROM active a
            JOIN read_parquet('{SKILL_PARQUET}') s ON s.user_id = a.user_id
            WHERE s.mu < 1686 AND s.phi >= 150 AND a.n_resolved < 10
            LIMIT 1
            """
        ).fetchone()
    finally:
        con.close()
    if row is None:
        pytest.skip("no warehouse user simultaneously short of all three locked thresholds")
    uid, mu, phi, n = row
    t = GYAANI_THRESHOLDS["locked"]
    st = gyaani_status(uid)
    gaps = st["gaps_to_locked"]
    assert gaps["mu_short_by"] == pytest.approx(t["mu_min"] - float(mu), abs=1e-6)
    assert gaps["phi_excess"] == pytest.approx(float(phi) - t["phi_max"], abs=1e-6)
    assert gaps["calls_short_by"] == t["n_resolved_min"] - int(n)


# ---------------------------------------------------------------------------
# Registration / metadata
# ---------------------------------------------------------------------------


def test_metrics_registered_in_defs() -> None:
    assert "gyaani_aspirant_share" in DEFS
    assert "gyaani_locked_share" in DEFS


def test_rule_version_exposed() -> None:
    assert isinstance(GYAANI_RULE_VERSION, str)
    assert GYAANI_RULE_VERSION  # non-empty
