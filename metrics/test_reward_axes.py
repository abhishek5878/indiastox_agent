"""Pytest tests for the 7-axis reward architecture (P2).

Covers:
  - Pure-function scorers: boundary correctness on synthetic call lists,
    range invariants, sample-size-too-small handling.
  - Stub axes return status='stub_pending_p05b' so consumers can flag
    the gap honestly.
  - user_reward_axes: aggregator returns valid structure; top_axis
    excludes stubs; works against the live warehouse.
  - AXES / _SCORERS registry stays in sync.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from metrics.reward_axes import (
    AXES,
    REWARD_AXES_VERSION,
    _SCORERS,
    score_accuracy,
    score_calibration,
    score_consistency,
    score_coverage,
    score_discovery,
    score_influence,
    score_presence,
    score_recovery,
    user_reward_axes,
)

REPO = Path(__file__).resolve().parents[1]
WAREHOUSE = REPO / "warehouse" / "indiastox.duckdb"


@pytest.fixture(scope="module", autouse=True)
def _require_warehouse():
    if not WAREHOUSE.exists():
        pytest.skip("warehouse not built — run `make resolve` first")


def _make_call(ts: datetime, stock: str, stars: int, outcome: str | None) -> tuple:
    """Synthetic call row matching the SQL tuple shape: (made_at,
    stock_symbol, direction, stars, outcome, is_resolved)."""
    return (ts, stock, "BULL", stars, outcome, outcome is not None)


# ---------------------------------------------------------------------------
# Registry invariants
# ---------------------------------------------------------------------------


def test_eight_axes() -> None:
    assert len(AXES) == 8
    assert set(AXES) == set(_SCORERS.keys())
    assert "presence" in AXES


def test_rule_version_exposed() -> None:
    assert isinstance(REWARD_AXES_VERSION, str) and REWARD_AXES_VERSION


# ---------------------------------------------------------------------------
# score_accuracy
# ---------------------------------------------------------------------------


def test_accuracy_sample_size_floor() -> None:
    """<3 resolved calls => score=0 + confidence_low."""
    calls = [_make_call(datetime(2024, 1, 1, 10), "TCS", 3, "WIN")] * 2
    out = score_accuracy(calls)
    assert out["score"] == 0.0
    assert out["confidence_low"] is True


def test_accuracy_all_wins() -> None:
    base = datetime(2024, 1, 1, 10)
    calls = [_make_call(base + timedelta(hours=i), "TCS", 3, "WIN") for i in range(5)]
    out = score_accuracy(calls)
    assert out["score"] == 1.0
    assert out["confidence_low"] is False


def test_accuracy_market_random() -> None:
    base = datetime(2024, 1, 1, 10)
    calls = [_make_call(base + timedelta(hours=i), "TCS", 3,
                        "WIN" if i % 2 == 0 else "LOSS") for i in range(6)]
    out = score_accuracy(calls)
    assert out["score"] == 0.0  # 50% win rate -> rescaled to 0


def test_accuracy_clipped_at_zero() -> None:
    base = datetime(2024, 1, 1, 10)
    calls = [_make_call(base + timedelta(hours=i), "TCS", 3, "LOSS") for i in range(5)]
    out = score_accuracy(calls)
    assert out["score"] == 0.0  # negative half-line clipped


# ---------------------------------------------------------------------------
# score_calibration
# ---------------------------------------------------------------------------


def test_calibration_perfect() -> None:
    """5-star calls all win, 1-star calls all lose => Brier=0."""
    base = datetime(2024, 1, 1, 10)
    calls = [
        _make_call(base, "TCS", 5, "WIN"),
        _make_call(base + timedelta(hours=1), "INFY", 5, "WIN"),
        _make_call(base + timedelta(hours=2), "HDFC", 1, "LOSS"),
        _make_call(base + timedelta(hours=3), "SBIN", 1, "LOSS"),
    ]
    out = score_calibration(calls)
    assert out["score"] == 1.0


def test_calibration_anti_calibrated() -> None:
    """5-star calls all lose, 1-star calls all win => high Brier => 0."""
    base = datetime(2024, 1, 1, 10)
    calls = [
        _make_call(base, "TCS", 5, "LOSS"),
        _make_call(base + timedelta(hours=1), "INFY", 5, "LOSS"),
        _make_call(base + timedelta(hours=2), "HDFC", 1, "WIN"),
    ]
    out = score_calibration(calls)
    assert out["score"] == 0.0


def test_calibration_floor_sample_size() -> None:
    out = score_calibration([_make_call(datetime(2024, 1, 1, 10), "TCS", 3, "WIN")])
    assert out["score"] == 0.0 and out["confidence_low"] is True


# ---------------------------------------------------------------------------
# score_coverage
# ---------------------------------------------------------------------------


def test_coverage_single_sector() -> None:
    base = datetime(2024, 1, 1, 10)
    calls = [_make_call(base + timedelta(hours=i), "TCS", 3, "WIN") for i in range(4)]
    out = score_coverage(calls)
    assert out["score"] == pytest.approx(0.25)  # 1 / 4 sectors


def test_coverage_all_four_sectors() -> None:
    base = datetime(2024, 1, 1, 10)
    calls = [
        _make_call(base, "RELIANCE", 3, "WIN"),    # energy
        _make_call(base + timedelta(hours=1), "TCS", 3, "WIN"),       # IT
        _make_call(base + timedelta(hours=2), "HDFC", 3, "WIN"),      # banking
        _make_call(base + timedelta(hours=3), "ITC", 3, "WIN"),       # FMCG
    ]
    out = score_coverage(calls)
    assert out["score"] == 1.0


def test_coverage_floor_sample_size() -> None:
    out = score_coverage([_make_call(datetime(2024, 1, 1, 10), "TCS", 3, "WIN")])
    assert out["confidence_low"] is True


# ---------------------------------------------------------------------------
# score_consistency
# ---------------------------------------------------------------------------


def test_consistency_perfect_regularity() -> None:
    base = datetime(2024, 1, 1, 10)
    calls = [_make_call(base + timedelta(hours=i * 12), "TCS", 3, "WIN") for i in range(5)]
    out = score_consistency(calls)
    assert out["score"] == pytest.approx(1.0, abs=0.05)


def test_consistency_burst_then_silent() -> None:
    """Five calls in five minutes, then silence — high gap variance."""
    base = datetime(2024, 1, 1, 10)
    calls = (
        [_make_call(base + timedelta(minutes=i), "TCS", 3, "WIN") for i in range(4)]
        + [_make_call(base + timedelta(hours=24), "INFY", 3, "WIN")]
    )
    out = score_consistency(calls)
    assert out["score"] < 0.5


def test_consistency_floor() -> None:
    """<4 calls => no inter-call gaps reliable."""
    base = datetime(2024, 1, 1, 10)
    out = score_consistency([_make_call(base, "TCS", 3, "WIN")] * 3)
    assert out["confidence_low"] is True


# ---------------------------------------------------------------------------
# score_recovery
# ---------------------------------------------------------------------------


def test_recovery_undefeated_returns_zero_low_confidence() -> None:
    base = datetime(2024, 1, 1, 10)
    calls = [_make_call(base + timedelta(hours=i), "TCS", 3, "WIN") for i in range(5)]
    out = score_recovery(calls)
    assert out["score"] == 0.0
    assert out["confidence_low"] is True


def test_recovery_full_comeback() -> None:
    """1 loss then 4 straight wins -> perfect recovery."""
    base = datetime(2024, 1, 1, 10)
    calls = [
        _make_call(base, "TCS", 3, "LOSS"),
        _make_call(base + timedelta(hours=1), "INFY", 3, "WIN"),
        _make_call(base + timedelta(hours=2), "HDFC", 3, "WIN"),
        _make_call(base + timedelta(hours=3), "SBIN", 3, "WIN"),
        _make_call(base + timedelta(hours=4), "ITC", 3, "WIN"),
    ]
    out = score_recovery(calls)
    assert out["score"] == 1.0


def test_recovery_loss_then_loss_zero() -> None:
    base = datetime(2024, 1, 1, 10)
    calls = [
        _make_call(base, "TCS", 3, "LOSS"),
        _make_call(base + timedelta(hours=1), "INFY", 3, "LOSS"),
        _make_call(base + timedelta(hours=2), "HDFC", 3, "LOSS"),
    ]
    out = score_recovery(calls)
    assert out["score"] == 0.0


# ---------------------------------------------------------------------------
# Stub axes
# ---------------------------------------------------------------------------


def test_presence_one_call_nonzero() -> None:
    """The whole point: 1 call should produce a positive presence score."""
    out = score_presence([_make_call(datetime(2024, 1, 1, 10), "TCS", 3, None)])
    assert out["score"] > 0.0
    assert out["confidence_low"] is False


def test_presence_zero_calls_returns_zero() -> None:
    out = score_presence([])
    assert out["score"] == 0.0
    assert out["confidence_low"] is True


def test_presence_saturates_at_high_volume() -> None:
    """20 calls should saturate at 1.0; 50 calls also 1.0 (clamped)."""
    base = datetime(2024, 1, 1, 10)
    calls = [_make_call(base + timedelta(hours=i), "TCS", 3, "WIN") for i in range(50)]
    out = score_presence(calls)
    assert out["score"] == 1.0


def test_presence_monotone() -> None:
    """More calls => strictly higher (or equal at saturation) score."""
    base = datetime(2024, 1, 1, 10)
    prev = 0.0
    for n in (1, 2, 3, 5, 8, 10):
        calls = [_make_call(base + timedelta(hours=i), "TCS", 3, "WIN") for i in range(n)]
        s = score_presence(calls)["score"]
        assert s >= prev, f"presence not monotone at n={n}: {s} < {prev}"
        prev = s


def test_influence_stubbed() -> None:
    out = score_influence([])
    assert out["score"] == 0.0
    assert out.get("status") == "stub_pending_p05b"


def test_discovery_stubbed() -> None:
    out = score_discovery([])
    assert out["score"] == 0.0
    assert out.get("status") == "stub_pending_p05b"


# ---------------------------------------------------------------------------
# Range invariant — all scorers return [0, 1]
# ---------------------------------------------------------------------------


def test_all_scorers_return_unit_interval() -> None:
    """Walk a grid of synthetic call patterns; assert score in [0, 1]
    for every scorer + every input."""
    base = datetime(2024, 1, 1, 10)
    patterns = [
        [],                                                            # empty
        [_make_call(base, "TCS", 3, "WIN")],                            # 1 call
        [_make_call(base + timedelta(hours=i), "TCS", 3, "WIN") for i in range(10)],  # all-win
        [_make_call(base + timedelta(hours=i), "TCS", 3, "LOSS") for i in range(10)], # all-loss
        [_make_call(base + timedelta(hours=i), "TCS", 3, None) for i in range(5)],    # unresolved
    ]
    for axis, fn in _SCORERS.items():
        for pattern in patterns:
            out = fn(pattern)
            assert 0.0 <= out["score"] <= 1.0, (
                f"{axis} produced out-of-range score {out['score']} on {len(pattern)}-call pattern"
            )


# ---------------------------------------------------------------------------
# user_reward_axes — aggregator against the live warehouse
# ---------------------------------------------------------------------------


def test_user_reward_axes_structure() -> None:
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
    out = user_reward_axes(uid[0])

    assert out["user_id"] == uid[0]
    assert out["rule_version"] == REWARD_AXES_VERSION
    assert set(out["axes"].keys()) == set(AXES)
    for axis_name, axis_out in out["axes"].items():
        assert "score" in axis_out
        assert 0.0 <= axis_out["score"] <= 1.0


def test_user_reward_axes_top_axis_excludes_stubs() -> None:
    """top_axis must NOT be influence or discovery (both are stubs)."""
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
    out = user_reward_axes(uid[0])
    assert out["top_axis"] not in ("influence", "discovery")


def test_user_reward_axes_empty_user_returns_zero_top() -> None:
    out = user_reward_axes("nonexistent-user-id-xxxxxxxxxxxxxxxxxxx")
    assert out["top_score"] == 0.0
    # When all real axes score 0 with confidence_low, top_axis is still
    # a real axis (max of equals returns first), but its score is 0.
    assert out["top_axis"] in (None,) + tuple(a for a in AXES if a not in ("influence", "discovery"))
