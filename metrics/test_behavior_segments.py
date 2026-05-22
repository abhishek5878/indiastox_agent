"""Pytest tests for the 8-segment behavior classifier (P3).

Covers:
  - Registry: 8 segments; SEGMENTS ↔ _SCORERS in sync.
  - Pure scorer correctness on synthetic call lists (each segment).
  - Range invariant: every scorer returns [0, 1].
  - Stub: shadows returns status='stub_pending_p05b'.
  - classify_user_segment against the live warehouse: valid structure;
    primary_segment excludes stubs.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from metrics.behavior_segments import (
    SEGMENTS,
    SEGMENTS_VERSION,
    _SCORERS,
    classify_user_segment,
    score_alphas,
    score_anchored,
    score_concentrators,
    score_cooled_off,
    score_diversifiers,
    score_ghosted,
    score_shadows,
    score_tilted,
)

REPO = Path(__file__).resolve().parents[1]
WAREHOUSE = REPO / "warehouse" / "indiastox.duckdb"


@pytest.fixture(scope="module", autouse=True)
def _require_warehouse():
    if not WAREHOUSE.exists():
        pytest.skip("warehouse not built — run `make resolve` first")


def _call(ts: datetime, stock: str, outcome: str | None, stars: int = 3) -> tuple:
    """Synthetic call row matching the SQL tuple shape used internally."""
    return (ts, stock, "BULL", stars, outcome, outcome is not None)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_eight_segments() -> None:
    assert len(SEGMENTS) == 8
    assert set(SEGMENTS) == set(_SCORERS.keys())


def test_rule_version_exposed() -> None:
    assert isinstance(SEGMENTS_VERSION, str) and SEGMENTS_VERSION


# ---------------------------------------------------------------------------
# ghosted
# ---------------------------------------------------------------------------


def test_ghosted_empty_calls() -> None:
    assert score_ghosted([])["score"] == 1.0


def test_ghosted_any_calls() -> None:
    out = score_ghosted([_call(datetime(2024, 1, 1, 10), "TCS", "WIN")])
    assert out["score"] == 0.0


# ---------------------------------------------------------------------------
# cooled_off
# ---------------------------------------------------------------------------


def test_cooled_off_all_early() -> None:
    """All 5 calls Monday morning, nothing after — strong cooled-off."""
    base = datetime(2024, 1, 1, 10)
    calls = [_call(base + timedelta(minutes=i * 5), "TCS", "WIN") for i in range(5)]
    # last call only 20m after first => no "second half" calls
    # extend the window by adding a late silent marker via fake-no-call
    # which the function doesn't see — use real spread to reflect intent
    base2 = datetime(2024, 1, 1, 9)
    calls2 = (
        [_call(base2 + timedelta(minutes=i * 5), "TCS", "WIN") for i in range(5)]
        + [_call(base2 + timedelta(days=5), "TCS", "WIN")]   # one straggler late
    )
    out = score_cooled_off(calls2)
    assert out["score"] > 0.5


def test_cooled_off_balanced() -> None:
    """Even cadence across week — should NOT register as cooled off."""
    base = datetime(2024, 1, 1, 10)
    calls = [_call(base + timedelta(days=i), "TCS", "WIN") for i in range(7)]
    out = score_cooled_off(calls)
    assert out["score"] < 0.5


def test_cooled_off_too_few_calls() -> None:
    out = score_cooled_off([_call(datetime(2024, 1, 1, 10), "TCS", "WIN")])
    assert out["confidence_low"] is True


# ---------------------------------------------------------------------------
# tilted
# ---------------------------------------------------------------------------


def test_tilted_revenge_spike() -> None:
    """Each LOSS is followed within 1 hour by another call — full tilt."""
    base = datetime(2024, 1, 1, 10)
    calls = [
        _call(base + timedelta(hours=0), "TCS", "LOSS"),
        _call(base + timedelta(hours=0, minutes=30), "INFY", "LOSS"),  # within 4h of prior LOSS
        _call(base + timedelta(hours=1), "HDFC", "LOSS"),
        _call(base + timedelta(hours=1, minutes=30), "SBIN", "WIN"),
        _call(base + timedelta(hours=2), "ITC", "WIN"),
    ]
    out = score_tilted(calls)
    assert out["score"] > 0.5


def test_tilted_no_losses_returns_zero() -> None:
    base = datetime(2024, 1, 1, 10)
    calls = [_call(base + timedelta(hours=i), "TCS", "WIN") for i in range(5)]
    out = score_tilted(calls)
    assert out["score"] == 0.0


def test_tilted_too_few_resolved() -> None:
    out = score_tilted([_call(datetime(2024, 1, 1, 10), "TCS", "LOSS")])
    assert out["confidence_low"] is True


# ---------------------------------------------------------------------------
# alphas
# ---------------------------------------------------------------------------


def test_alphas_high_mu_qualifies() -> None:
    base = datetime(2024, 1, 1, 10)
    calls = [_call(base + timedelta(hours=i), "TCS", "WIN") for i in range(5)]
    out = score_alphas(calls, mu=1800.0)
    assert out["score"] >= 0.6


def test_alphas_low_mu_zero() -> None:
    base = datetime(2024, 1, 1, 10)
    calls = [_call(base + timedelta(hours=i), "TCS", "WIN") for i in range(5)]
    out = score_alphas(calls, mu=1500.0)
    assert out["score"] == 0.0


def test_alphas_no_mu_zero() -> None:
    out = score_alphas([_call(datetime(2024, 1, 1, 10), "TCS", "WIN")] * 5, mu=None)
    assert out["score"] == 0.0


# ---------------------------------------------------------------------------
# anchored
# ---------------------------------------------------------------------------


def test_anchored_single_sector_dominant() -> None:
    base = datetime(2024, 1, 1, 10)
    calls = [_call(base + timedelta(hours=i), "TCS", "WIN") for i in range(8)]  # all IT
    out = score_anchored(calls)
    assert out["score"] == 1.0


def test_anchored_below_threshold() -> None:
    base = datetime(2024, 1, 1, 10)
    calls = [
        _call(base, "TCS", "WIN"),         # IT
        _call(base + timedelta(hours=1), "HDFC", "WIN"),       # banking
        _call(base + timedelta(hours=2), "ITC", "WIN"),        # FMCG
    ]
    out = score_anchored(calls)
    assert out["score"] == 0.0  # top sector share = 1/3 ≈ 0.33; below 0.75 gate


# ---------------------------------------------------------------------------
# concentrators
# ---------------------------------------------------------------------------


def test_concentrators_narrow_voluminous() -> None:
    """8 calls across 2 sectors → strong concentrator."""
    base = datetime(2024, 1, 1, 10)
    calls = [
        _call(base + timedelta(hours=i), "TCS" if i < 4 else "HDFC", "WIN")
        for i in range(8)
    ]
    out = score_concentrators(calls)
    assert out["score"] > 0.5


def test_concentrators_too_few_calls() -> None:
    base = datetime(2024, 1, 1, 10)
    out = score_concentrators([_call(base, "TCS", "WIN")] * 4)
    assert out["confidence_low"] is True


def test_concentrators_high_coverage_disqualifies() -> None:
    """8 calls across all 4 sectors — coverage=1.0 → not a concentrator."""
    base = datetime(2024, 1, 1, 10)
    tickers = ["TCS", "HDFC", "ITC", "RELIANCE"] * 2
    calls = [_call(base + timedelta(hours=i), t, "WIN") for i, t in enumerate(tickers)]
    out = score_concentrators(calls)
    assert out["score"] == 0.0


# ---------------------------------------------------------------------------
# diversifiers
# ---------------------------------------------------------------------------


def test_diversifiers_full_coverage() -> None:
    base = datetime(2024, 1, 1, 10)
    calls = [
        _call(base, "RELIANCE", "WIN"),  # energy
        _call(base + timedelta(hours=1), "TCS", "WIN"),    # IT
        _call(base + timedelta(hours=2), "HDFC", "WIN"),   # banking
        _call(base + timedelta(hours=3), "ITC", "WIN"),    # FMCG
    ]
    out = score_diversifiers(calls)
    assert out["score"] == 1.0


def test_diversifiers_partial_coverage() -> None:
    base = datetime(2024, 1, 1, 10)
    calls = [
        _call(base, "TCS", "WIN"),
        _call(base + timedelta(hours=1), "HDFC", "WIN"),
        _call(base + timedelta(hours=2), "TCS", "WIN"),
    ]
    out = score_diversifiers(calls)
    assert out["score"] == 0.0  # only 2/4 sectors = 0.5 = at floor → 0


# ---------------------------------------------------------------------------
# shadows (stub)
# ---------------------------------------------------------------------------


def test_shadows_stubbed() -> None:
    out = score_shadows([])
    assert out["score"] == 0.0
    assert out.get("status") == "stub_pending_p05b"


# ---------------------------------------------------------------------------
# Range invariant
# ---------------------------------------------------------------------------


def test_all_scorers_return_unit_interval() -> None:
    base = datetime(2024, 1, 1, 10)
    patterns = [
        [],
        [_call(base, "TCS", "WIN")],
        [_call(base + timedelta(hours=i), "TCS", "WIN") for i in range(10)],
        [_call(base + timedelta(hours=i), "TCS", "LOSS") for i in range(10)],
        [_call(base + timedelta(days=i), "TCS", None) for i in range(5)],
    ]
    mus = [None, 1400.0, 1500.0, 1700.0, 1900.0]
    for name, fn in _SCORERS.items():
        for pattern in patterns:
            for mu in mus:
                out = fn(pattern, mu)
                assert 0.0 <= out["score"] <= 1.0, (
                    f"{name}: out-of-range {out['score']} on n={len(pattern)} mu={mu}"
                )


# ---------------------------------------------------------------------------
# classify_user_segment — live warehouse aggregator
# ---------------------------------------------------------------------------


def test_classify_user_segment_structure() -> None:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        uid = con.execute("""
            SELECT user_id FROM fact_prediction
            WHERE is_outcome_resolved = TRUE
            GROUP BY user_id HAVING COUNT(*) >= 5
            ORDER BY user_id LIMIT 1
        """).fetchone()
    finally:
        con.close()
    if uid is None:
        pytest.skip("no warehouse user with >=5 resolved calls")
    out = classify_user_segment(uid[0])

    assert out["user_id"] == uid[0]
    assert out["rule_version"] == SEGMENTS_VERSION
    assert set(out["segments"].keys()) == set(SEGMENTS)
    for name, seg_out in out["segments"].items():
        assert 0.0 <= seg_out["score"] <= 1.0


def test_classify_primary_excludes_stubs() -> None:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        uid = con.execute("""
            SELECT user_id FROM fact_prediction
            GROUP BY user_id HAVING COUNT(*) >= 3
            ORDER BY user_id LIMIT 1
        """).fetchone()
    finally:
        con.close()
    if uid is None:
        pytest.skip("no warehouse user with >=3 calls")
    out = classify_user_segment(uid[0])
    assert out["primary_segment"] != "shadows"


def test_classify_ghosted_user_primary_is_ghosted() -> None:
    """A user with zero calls in W01 should classify as ghosted."""
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        uid = con.execute("""
            SELECT du.user_id FROM dim_user du
            LEFT JOIN fact_prediction fp ON fp.user_id = du.user_id
              AND fp.made_at >= '2024-01-01' AND fp.made_at < '2024-01-08'
            WHERE fp.prediction_id IS NULL
            ORDER BY du.user_id LIMIT 1
        """).fetchone()
    finally:
        con.close()
    if uid is None:
        pytest.skip("no fully-ghosted warehouse user in W01")
    out = classify_user_segment(uid[0])
    assert out["primary_segment"] == "ghosted"
    assert out["primary_score"] == 1.0
