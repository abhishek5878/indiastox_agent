"""Behavioral segmentation — eight observable user segments (P3).

The strategy meeting framed segmentation as a replacement for the legacy
demographic-style slicing on the dashboard. Eight behavioral segments
were named: Concentrators, Diversifiers, Tilted, Shadows, Alphas,
Anchored, Cooled-off, Ghosted. Each maps to an observable trace in
fact_prediction (and Glicko-2's skill_ratings).

Design choice (mirroring P2 reward axes):
  - Each segment has a pure scoring function returning a [0, 1] score.
  - A user has a score on every segment; `classify_user_segment()`
    returns the dominant one plus the full score vector. Segments are
    NOT mutually exclusive — a user can be both Tilted and Anchored;
    the classifier surfaces the dominant signal.
  - `SEGMENTS_VERSION = "1.0.0"` for the version invariant.

Honest scope (W01):
  - 7 segments real on current substrate (ghosted, cooled_off, anchored,
    concentrators, diversifiers, tilted, alphas).
  - `shadows` is stubbed — it needs copy_call events from the
    cross-agent layers shipped in P0.5b. Returns score=0.0 with
    status='stub_pending_p05b' so consumers can flag the gap.

The dispatch table `_SCORERS` is the single source of truth that maps
segment name → function. No segment logic lives outside this module.
"""
from __future__ import annotations

import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

import duckdb

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from metrics.definitions import GYAANI_THRESHOLDS
from metrics.reward_axes import _user_calls

WAREHOUSE_DB = _REPO / "warehouse" / "indiastox.duckdb"
SKILL_PARQUET = _REPO / "data" / "skill_ratings.parquet"

SEGMENTS_VERSION = "1.0.0"

# Order is chosen so that the "obvious" terminal states come first
# (ghosted, cooled_off) — useful for human-readable dashboards even
# though the classifier picks the max-score segment regardless of order.
SEGMENTS: Tuple[str, ...] = (
    "ghosted",         # 0 calls in window
    "cooled_off",      # active early-week, silent late-week
    "tilted",          # post-loss revenge spike
    "alphas",          # top-of-skill mu + meaningful sample
    "anchored",        # one sector dominates (>=75%)
    "concentrators",   # narrow but voluminous
    "diversifiers",    # touch >=3 of 4 live sectors
    "shadows",         # stub — needs copy_call events from P0.5b
)

LIVE_SECTORS: Tuple[str, ...] = ("energy", "IT", "banking", "FMCG")


def _connect():
    return duckdb.connect(str(WAREHOUSE_DB), read_only=False)


def _ts_of(call: tuple) -> datetime:
    return call[0]


def _sector_of(stock: str) -> Optional[str]:
    """Local sector map — duplicated from sim/world.py to avoid pulling
    duckdb at import time. Tickers not in the map return None (callers
    drop the call from sector-based metrics)."""
    mapping = {
        "RELIANCE": "energy",
        "TCS": "IT", "INFY": "IT", "WIPRO": "IT", "HCLTECH": "IT",
        "HDFC": "banking", "ICICIBANK": "banking", "SBIN": "banking", "BAJFINANCE": "banking",
        "ITC": "FMCG",
    }
    return mapping.get(stock)


# ---------------------------------------------------------------------------
# Per-segment scoring — pure functions. Single source of truth.
# ---------------------------------------------------------------------------


def score_ghosted(calls: list[tuple], mu: Optional[float] = None) -> dict:
    """1.0 iff the user made zero calls in the window. Binary.

    The terminal disengagement state. Other segments are mutually
    incompatible with this one (the score will be 1 here and 0 on the
    others), so the classifier's max-score logic surfaces ghosted
    cleanly when it applies.
    """
    return dict(score=1.0 if not calls else 0.0, n=len(calls), confidence_low=False)


def score_cooled_off(calls: list[tuple], mu: Optional[float] = None) -> dict:
    """1.0 when activity in the first half of the window outpaces the
    second half by 3x or more. 0.0 when the second half matches or
    exceeds the first.

    Captures users who started the week engaged then ghosted —
    distinct from Ghosted (who never started) and from steady
    callers (who maintain rate).
    """
    if len(calls) < 3:
        return dict(score=0.0, n=len(calls), confidence_low=True)
    ts_first = _ts_of(calls[0])
    ts_last = _ts_of(calls[-1])
    if ts_last == ts_first:
        return dict(score=0.0, n=len(calls), confidence_low=True)
    mid = ts_first + (ts_last - ts_first) / 2
    early = sum(1 for c in calls if _ts_of(c) <= mid)
    late = len(calls) - early
    if early == 0:
        return dict(score=0.0, n=len(calls), confidence_low=False)
    ratio = early / max(late, 0.5)  # avoid div-by-zero when late==0
    score = max(0.0, min(1.0, (ratio - 1.0) / 4.0))
    return dict(score=score, n=len(calls), confidence_low=False)


def score_tilted(calls: list[tuple], mu: Optional[float] = None) -> dict:
    """Post-loss revenge spike: number of calls within 4 sim-hours of a
    LOSS outcome resolution, divided by what you'd expect uniformly.

    Real W01 data: outcomes resolve 5 days post-call so in-week LOSS
    reactions can't actually fire. We approximate by treating an
    *adjacent prior LOSS in the user's call sequence* as a tilt
    trigger — i.e., if user made call C and C-1 had outcome LOSS,
    that's a tilt event. Crude on a single week but captures the
    archetype's pattern when present.
    """
    resolved = [c for c in calls if c[5]]
    if len(resolved) < 4:
        return dict(score=0.0, n=len(resolved), confidence_low=True)
    tilt_events = 0
    for i in range(1, len(resolved)):
        if resolved[i - 1][4] == "LOSS":
            # Did the next call follow quickly (<4 sim-hours)?
            gap = (resolved[i][0] - resolved[i - 1][0]).total_seconds() / 3600.0
            if gap < 4.0:
                tilt_events += 1
    losses = sum(1 for r in resolved if r[4] == "LOSS")
    if losses == 0:
        return dict(score=0.0, n=len(resolved), confidence_low=True)
    score = min(1.0, tilt_events / losses)
    return dict(score=score, n=len(resolved), confidence_low=False)


def score_alphas(calls: list[tuple], mu: Optional[float] = None) -> dict:
    """Top-of-skill segment: mu at or above the Gyaani-locked floor with
    a non-trivial sample.

    Reuses the Gyaani-locked mu threshold so the segments are coherent
    with P1: every alpha is at least a Gyaani candidate by mu (their
    phi may still be too high to graduate, but the skill signal is
    locked-tier).
    """
    if mu is None or len(calls) < 3:
        return dict(score=0.0, n=len(calls), confidence_low=True)
    alpha_floor = GYAANI_THRESHOLDS["locked"]["mu_min"]
    if mu < alpha_floor:
        return dict(score=0.0, n=len(calls), confidence_low=False)
    headroom = max(0.0, mu - alpha_floor)
    score = min(1.0, 0.6 + headroom / 200.0)
    return dict(score=score, n=len(calls), confidence_low=False)


def score_anchored(calls: list[tuple], mu: Optional[float] = None) -> dict:
    """Anchored when one sector accounts for >=75% of calls. The
    archetype design says "first call's sector becomes 80% of future
    calls"; this is the observable analog.

    Score scales smoothly: 0.5 share → 0; 0.75 share → 0.0 (gate);
    0.9 share → 0.6; 1.0 share → 1.0.
    """
    if len(calls) < 3:
        return dict(score=0.0, n=len(calls), confidence_low=True)
    sectors = [_sector_of(c[1]) for c in calls]
    sectors = [s for s in sectors if s is not None]
    if not sectors:
        return dict(score=0.0, n=len(calls), confidence_low=True)
    top_sector_share = Counter(sectors).most_common(1)[0][1] / len(sectors)
    if top_sector_share < 0.75:
        return dict(score=0.0, n=len(calls), confidence_low=False)
    score = (top_sector_share - 0.75) / 0.25
    return dict(score=min(1.0, score), n=len(calls), confidence_low=False)


def score_concentrators(calls: list[tuple], mu: Optional[float] = None) -> dict:
    """Narrow but voluminous: few sectors touched (coverage <= 0.5)
    with at least 5 calls. Distinct from Anchored (which is single-
    sector dominance) — a Concentrator might be banking + IT only.

    Score peaks at the boundary: max signal for users with exactly 2
    sectors and 8+ calls.
    """
    if len(calls) < 5:
        return dict(score=0.0, n=len(calls), confidence_low=True)
    sectors_touched = {s for s in (_sector_of(c[1]) for c in calls) if s is not None}
    coverage = len(sectors_touched & set(LIVE_SECTORS)) / len(LIVE_SECTORS)
    if coverage > 0.5:
        return dict(score=0.0, n=len(calls), confidence_low=False)
    # coverage in [0, 0.5], n_calls in [5, ∞)
    # narrowness=1 at coverage=0, narrowness=0.5 at coverage=0.5 (the gate)
    # — keeps 2-sector users (Concentrator's natural shape) earning, while
    # 1-sector dominance is resolved by Anchored via the max-score classifier.
    narrowness = 1.0 - coverage
    volume = min(1.0, len(calls) / 8.0)
    score = (narrowness + volume) / 2.0
    return dict(score=min(1.0, score), n=len(calls), confidence_low=False)


def score_diversifiers(calls: list[tuple], mu: Optional[float] = None) -> dict:
    """Broad sector touch: >=3 of 4 LIVE_SECTORS at least once. The
    inverse of Anchored in spirit — index-investor-style behavior.

    Score is the coverage fraction above 0.5 ceiling-normalized to 1.0
    at full 4-sector coverage. coverage 0.5 → 0; 0.75 → 0.5; 1.0 → 1.0.
    """
    if len(calls) < 3:
        return dict(score=0.0, n=len(calls), confidence_low=True)
    sectors_touched = {s for s in (_sector_of(c[1]) for c in calls) if s is not None}
    coverage = len(sectors_touched & set(LIVE_SECTORS)) / len(LIVE_SECTORS)
    if coverage < 0.5:
        return dict(score=0.0, n=len(calls), confidence_low=False)
    score = (coverage - 0.5) / 0.5
    return dict(score=min(1.0, score), n=len(calls), confidence_low=False)


def score_shadows(calls: list[tuple], mu: Optional[float] = None) -> dict:
    """STUB. Shadows are users who copy specific peer calls — needs
    `copy_call` edges emitted by the cross-agent peer_copy layer
    (P0.5b). Returns 0.0 with status='stub_pending_p05b'."""
    return dict(score=0.0, n=len(calls), confidence_low=True, status="stub_pending_p05b")


_SCORERS = {
    "ghosted": score_ghosted,
    "cooled_off": score_cooled_off,
    "tilted": score_tilted,
    "alphas": score_alphas,
    "anchored": score_anchored,
    "concentrators": score_concentrators,
    "diversifiers": score_diversifiers,
    "shadows": score_shadows,
}


def _mu_for_user(user_id: str) -> Optional[float]:
    """Look up a user's Glicko-2 mu from skill_ratings.parquet. Returns
    None if no rating exists (most often: user has no resolved calls
    yet)."""
    if not SKILL_PARQUET.exists():
        return None
    con = _connect()
    try:
        row = con.execute(
            "SELECT mu FROM read_parquet(?) WHERE user_id = ?",
            [str(SKILL_PARQUET), user_id],
        ).fetchone()
    finally:
        con.close()
    return float(row[0]) if row and row[0] is not None else None


def classify_user_segment(user_id: str, week_of: str = "2024-W01") -> dict:
    """Per-user segmentation — score on every segment + dominant pick.

    Returns:
      {
        "user_id": str,
        "rule_version": "1.0.0",
        "segments": {
            "ghosted":       {"score": float, "n": int, ...},
            ...
        },
        "primary_segment": str | None,    # highest-scoring real segment
        "primary_score": float,
      }

    primary_segment is None when every real segment scores 0.0 (an
    edge case — usually a user with 1-2 calls that don't trip any
    gate). Stubbed segments are excluded from primary selection.
    """
    calls = _user_calls(user_id, week_of)
    mu = _mu_for_user(user_id)
    segments_out: dict[str, dict] = {}
    for name in SEGMENTS:
        segments_out[name] = _SCORERS[name](calls, mu)

    real = {
        n: v for n, v in segments_out.items()
        if not v.get("status", "").startswith("stub")
    }
    if real:
        top_name, top_v = max(real.items(), key=lambda kv: kv[1]["score"])
        if top_v["score"] > 0:
            primary, score = top_name, float(top_v["score"])
        else:
            primary, score = None, 0.0
    else:
        primary, score = None, 0.0

    return dict(
        user_id=user_id,
        rule_version=SEGMENTS_VERSION,
        segments=segments_out,
        primary_segment=primary,
        primary_score=score,
    )
