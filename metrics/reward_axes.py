"""Seven-axis reward architecture (P2).

Gyaani is a single status badge (P1). The reward architecture is the
seven *measurement* dimensions that let non-Gyaani users still earn
rewards along *some* axis — exactly the design the strategy meeting
called for ("we don't just need Gyaani; everyone is needed, even
after they're wrong, we need them to re-engage"). A pharma_doctor with
low call volume earns calibration; an anchored_conservative earns
consistency; a diversifier earns coverage — each cohort gets a
signal that says "you're being seen."

Per-axis design:
  - Each axis is a pure function `score_<axis>(user_id, week_of)`
    returning a float in [0, 1] plus a count of inputs used. Inputs
    used <= 2 produces score=0.0 with confidence_low=True to avoid
    rewarding noise.
  - Scores are designed so a non-trivial fraction of every archetype
    lands above 0.3 on at least one axis. If the scale needed
    re-tuning, the meta-pattern (see __main__ block) would show it.
  - `user_reward_axes(user_id)` aggregates all 7 into a fingerprint
    dict, which agents call to answer "what is X strong at?".

Honest scope (W01):
  - accuracy / calibration / coverage / consistency / recovery are
    backed by real fact_prediction data.
  - influence + discovery need event types the current substrate
    doesn't emit (copy_call edges for influence; ticker-popularity
    time series for discovery — both unlocked when P0.5b ships
    multi-week + cross-agent layers).
  - Both are stubbed transparently — they return 0.0 with a
    notes["status"] = "stub_pending_p05b" so agents and dashboards
    can flag the gap honestly.
"""
from __future__ import annotations

import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

import duckdb

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

WAREHOUSE_DB = _REPO / "warehouse" / "indiastox.duckdb"

REWARD_AXES_VERSION = "1.0.0"

# All eight axes named here so a consumer can iterate without typo risk.
# Order is by semantic family: quality (accuracy/calibration), breadth
# (coverage), behavior (consistency/recovery/presence), social (influence),
# market (discovery). The first six are real on W01; the last two are stubs.
AXES: Tuple[str, ...] = (
    "accuracy",       # real on W01: win-rate over resolved calls
    "calibration",    # real on W01: agreement between stars and outcome
    "coverage",       # real on W01: sector breadth
    "consistency",    # real on W01: temporal regularity of calls
    "recovery",       # real on W01: win-rate of post-loss calls
    "presence",       # real on W01: rewards just showing up (covers low-volume cohorts)
    "influence",      # stub: needs copy_call edges from P0.5b
    "discovery",      # stub: needs ticker-popularity over time
)

# Minimum sample sizes before an axis returns a non-zero score. Below
# this, the score is 0.0 with confidence_low=True — we don't reward
# noise.
MIN_RESOLVED_FOR_ACCURACY = 3
MIN_CALLS_FOR_CALIBRATION = 3
MIN_CALLS_FOR_COVERAGE = 3
MIN_CALLS_FOR_CONSISTENCY = 4   # need >=3 inter-call gaps -> >=4 calls
MIN_POST_LOSS_CALLS_FOR_RECOVERY = 2

# Live sectors in the warehouse (per sim/world.py SECTOR_OF). Coverage
# is computed against this set.
LIVE_SECTORS: Tuple[str, ...] = ("energy", "IT", "banking", "FMCG")


def _connect():
    return duckdb.connect(str(WAREHOUSE_DB), read_only=False)


def _user_calls(user_id: str, week_of: str) -> list[tuple]:
    """Return per-call rows for the user in the week: (made_at, stock,
    direction, stars, outcome, is_resolved). Used by every axis so the
    SQL pull happens once per `user_reward_axes` call.
    """
    year, week = week_of.split("-W")
    monday = datetime.strptime(f"{int(year)}-W{int(week):02d}-1", "%G-W%V-%u")
    end = monday + timedelta(days=7)
    con = _connect()
    try:
        rows = con.execute(
            """
            SELECT made_at, stock_symbol, direction, confidence_stars,
                   outcome, is_outcome_resolved
            FROM fact_prediction
            WHERE user_id = ? AND made_at >= ? AND made_at < ?
            ORDER BY made_at ASC
            """,
            [user_id, monday, end],
        ).fetchall()
    finally:
        con.close()
    return rows


# ---------------------------------------------------------------------------
# Per-axis scoring — pure functions over the call list. Single source of
# truth for each axis.
# ---------------------------------------------------------------------------


def score_accuracy(calls: list[tuple]) -> dict:
    """Win-rate over resolved calls in [0, 1]. 0.5 = random; >0.5 = better.

    Rescaled: a user at 0.5 win-rate scores 0.0 (no signal above market),
    a user at 1.0 wins scores 1.0. Negative half-line clipped at 0
    because losing systematically is its own metric (anti-skill) — for
    rewards we only surface positive signal.
    """
    resolved = [r for r in calls if r[5]]  # is_outcome_resolved
    n = len(resolved)
    if n < MIN_RESOLVED_FOR_ACCURACY:
        return dict(score=0.0, n=n, confidence_low=True)
    wins = sum(1 for r in resolved if r[4] == "WIN")
    win_rate = wins / n
    score = max(0.0, (win_rate - 0.5) * 2.0)
    return dict(score=min(1.0, score), n=n, confidence_low=False)


def score_calibration(calls: list[tuple]) -> dict:
    """Brier-like agreement between expressed confidence and realized
    outcome, mapped to [0, 1].

    For each resolved call, treat (stars/5) as the user's stated P(win).
    Brier = mean((stated_p - actual{0,1})^2). Brier of 0 = perfect
    calibration, 0.25 = market-random (50/50 with 3-star calls); we
    flip and rescale so 1.0 = perfectly calibrated, 0.0 = anti-calibrated.
    """
    resolved = [r for r in calls if r[5]]
    if len(resolved) < MIN_CALLS_FOR_CALIBRATION:
        return dict(score=0.0, n=len(resolved), confidence_low=True)
    brier_sum = 0.0
    for _ts, _stk, _dir, stars, outcome, _r in resolved:
        stated_p = (int(stars) - 1) / 4.0   # 1-star -> 0; 5-star -> 1
        actual = 1.0 if outcome == "WIN" else (0.5 if outcome == "DRAW" else 0.0)
        brier_sum += (stated_p - actual) ** 2
    brier = brier_sum / len(resolved)
    score = max(0.0, 1.0 - brier * 4.0)  # brier=0 -> 1.0, brier=0.25 -> 0.0
    return dict(score=min(1.0, score), n=len(resolved), confidence_low=False)


def score_coverage(calls: list[tuple]) -> dict:
    """Sector breadth — distinct LIVE_SECTORS touched / total LIVE_SECTORS.

    A diversifier touching all 4 sectors scores 1.0; an anchored
    conservative on one sector scores 0.25. Coverage rewards the breadth
    axis the meeting called for (different cohorts win on different
    axes; this is where index-investor-style behavior earns).
    """
    if len(calls) < MIN_CALLS_FOR_COVERAGE:
        return dict(score=0.0, n=len(calls), confidence_low=True)
    from sim.world import SECTOR_OF  # local import to avoid cycle at module load
    sectors_touched = {
        SECTOR_OF.get(c[1], None) for c in calls
    }
    sectors_touched.discard(None)
    score = len(sectors_touched & set(LIVE_SECTORS)) / len(LIVE_SECTORS)
    return dict(score=min(1.0, score), n=len(calls), confidence_low=False)


def score_consistency(calls: list[tuple]) -> dict:
    """Temporal regularity — inverse of normalized inter-call-gap stdev.

    For a user whose calls are spread evenly across the week the gap
    stdev is small relative to the mean; consistency -> 1. For a user
    who makes 5 calls Monday morning and nothing else, stdev is huge
    relative to mean; consistency -> 0. Rewards the
    anchored_conservative cohort that doesn't graduate Gyaani by mu but
    is structurally regular.
    """
    if len(calls) < MIN_CALLS_FOR_CONSISTENCY:
        return dict(score=0.0, n=len(calls), confidence_low=True)
    gaps = []
    for i in range(1, len(calls)):
        delta = (calls[i][0] - calls[i - 1][0]).total_seconds()
        gaps.append(max(0.0, delta))
    if not gaps:
        return dict(score=0.0, n=len(calls), confidence_low=True)
    mean = statistics.fmean(gaps)
    if mean <= 0:
        return dict(score=0.0, n=len(calls), confidence_low=True)
    stdev = statistics.pstdev(gaps)
    cv = stdev / mean   # coefficient of variation; 0 = perfectly regular
    score = max(0.0, 1.0 - min(cv, 2.0) / 2.0)
    return dict(score=score, n=len(calls), confidence_low=False)


def score_recovery(calls: list[tuple]) -> dict:
    """Comeback signal — win-rate of calls made AFTER the user's first
    LOSS outcome. Captures the 0/4-then-4/4 pattern the user named in
    the strategy meeting.

    Only resolved post-loss calls count. A user who never lost has
    nothing to recover from; score = 0 with confidence_low=True (not
    a recovery story, just an undefeated story). A user with many
    losses and many post-loss wins scores high.
    """
    resolved = [r for r in calls if r[5]]
    first_loss_idx: Optional[int] = None
    for i, r in enumerate(resolved):
        if r[4] == "LOSS":
            first_loss_idx = i
            break
    if first_loss_idx is None:
        return dict(score=0.0, n=0, confidence_low=True)
    post_loss = resolved[first_loss_idx + 1:]
    if len(post_loss) < MIN_POST_LOSS_CALLS_FOR_RECOVERY:
        return dict(score=0.0, n=len(post_loss), confidence_low=True)
    wins = sum(1 for r in post_loss if r[4] == "WIN")
    win_rate = wins / len(post_loss)
    score = max(0.0, (win_rate - 0.5) * 2.0)
    return dict(score=min(1.0, score), n=len(post_loss), confidence_low=False)


def score_presence(calls: list[tuple]) -> dict:
    """Rewards showing up — the Facebook "you made your first call" axis.

    This exists to close the gap surfaced by the P2 baseline meta-pattern:
    the five zero-aspirant Gyaani cohorts (pharma_doctor, skeptic,
    anchored_conservative, diversifier_index_investor, lurker_turned_caller)
    score zero on every other axis because their W01 call counts fall
    below the sample-size gates. Without a presence axis, the reward
    layer leaves these cohorts unmeasurable.

    Scoring: log(1 + n_calls) / log(1 + N_CALLS_FOR_FULL_PRESENCE), so
    the first few calls produce a steep payoff (the Facebook activation
    curve) and the function saturates at the 10-calls/week ceiling.

    No sample-size gate: even one call earns a non-trivial reward
    (~0.30). That's the load-bearing semantic — presence is the one
    axis that ought to nonzero on the very first action.
    """
    import math
    n = len(calls)
    if n <= 0:
        return dict(score=0.0, n=0, confidence_low=True)
    N_FULL = 10
    score = math.log1p(n) / math.log1p(N_FULL)
    return dict(score=min(1.0, score), n=n, confidence_low=False)


def score_influence(calls: list[tuple]) -> dict:
    """STUB. Influence requires copy_call edges from the cross-agent
    layers (P0.5b). Today the substrate does not emit copy events, so
    this axis cannot be measured honestly. Returns 0.0 with
    notes['status']='stub_pending_p05b'."""
    return dict(score=0.0, n=0, confidence_low=True, status="stub_pending_p05b")


def score_discovery(calls: list[tuple]) -> dict:
    """STUB. Discovery requires a ticker-popularity time series so we
    can ask "did this user call ticker X before it became popular?".
    The current substrate does not maintain ticker-popularity windows
    across multiple weeks. Returns 0.0 with notes['status']=
    'stub_pending_p05b'."""
    return dict(score=0.0, n=0, confidence_low=True, status="stub_pending_p05b")


# Dispatch table. The single place that knows which scorer handles each
# axis. `user_reward_axes` consults this to keep `if/elif` ladders out
# of consumer code.
_SCORERS = {
    "accuracy": score_accuracy,
    "calibration": score_calibration,
    "coverage": score_coverage,
    "consistency": score_consistency,
    "recovery": score_recovery,
    "presence": score_presence,
    "influence": score_influence,
    "discovery": score_discovery,
}


def user_reward_axes(user_id: str, week_of: str = "2024-W01") -> dict:
    """Per-user reward fingerprint across all 7 axes.

    Returns:
      {
        "user_id": str,
        "rule_version": "1.0.0",
        "axes": {
            "accuracy":   {"score": float, "n": int, "confidence_low": bool, ...},
            ...
        },
        "top_axis": str | None,    # highest-scoring real axis, or None
        "top_score": float,
      }

    Agents call this to answer "what is X strong at?" Used by the
    Gyaani-aspirant nudge path: a user at 0% aspirant who scores 0.7
    on calibration gets a "you're a calibrated caller" reward even if
    they don't graduate Gyaani.
    """
    calls = _user_calls(user_id, week_of)
    axes_out: dict[str, dict] = {}
    for axis in AXES:
        axes_out[axis] = _SCORERS[axis](calls)

    real_axes = {
        a: v for a, v in axes_out.items()
        if not v.get("status", "").startswith("stub")
    }
    if real_axes:
        top = max(real_axes.items(), key=lambda kv: kv[1]["score"])
        top_axis, top_score = top[0], float(top[1]["score"])
    else:
        top_axis, top_score = None, 0.0

    return dict(
        user_id=user_id,
        rule_version=REWARD_AXES_VERSION,
        axes=axes_out,
        top_axis=top_axis,
        top_score=top_score,
    )
