"""Glicko-2 skill estimator over closed prediction outcomes.

Treats every prediction as a match: user vs. market. WIN = 1, LOSS = 0,
DRAW = 0.5. The market opponent has a fixed rating of 1500 with low RD
(the market sees all info; users are testing themselves against it).

Reference: Glickman, M.E. (2012). Example of the Glicko-2 System.
http://www.glicko.net/glicko/glicko2.pdf

For the prototype we use the standard formulas, with one simplification:
volatility (sigma) is held constant at the initial value rather than
iteratively updated each rating period. The full iterative step (Eq. 12 in
the paper) would add complexity for marginal gain on a 1-week window;
flag for v2.
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from core.confidence import MetricResult, versioned

WAREHOUSE_DB = _REPO / "warehouse" / "indiastox.duckdb"
PERSONAS_PARQUET = _REPO / "data" / "personas.parquet"
SKILL_PARQUET = _REPO / "data" / "skill_ratings.parquet"

# Initial Glicko-2 priors.
INIT_RATING = 1500.0
INIT_RD = 350.0
INIT_VOL = 0.06

# Glicko-2 scaling.
GLICKO_SCALE = 173.7178

# Market opponent: very stable rating, very low RD (the market is a
# well-calibrated baseline of all-information).
MARKET_RATING = 1500.0
MARKET_RD = 50.0


@dataclass
class GlickoRating:
    rating: float
    rd: float
    vol: float

    def to_glicko2(self) -> tuple[float, float]:
        mu = (self.rating - 1500.0) / GLICKO_SCALE
        phi = self.rd / GLICKO_SCALE
        return mu, phi


def _g(phi: float) -> float:
    return 1.0 / math.sqrt(1.0 + 3.0 * phi * phi / (math.pi * math.pi))


def _E(mu: float, mu_j: float, phi_j: float) -> float:
    return 1.0 / (1.0 + math.exp(-_g(phi_j) * (mu - mu_j)))


def update_glicko2(prior: GlickoRating, matches: list[tuple[float, float, float]]) -> GlickoRating:
    """matches: list of (opponent_rating, opponent_rd, score in {0, 0.5, 1})."""
    if not matches:
        # No games this rating period: RD widens by sqrt(phi^2 + sigma^2),
        # rating stays.
        mu, phi = prior.to_glicko2()
        new_phi = math.sqrt(phi * phi + prior.vol * prior.vol)
        return GlickoRating(prior.rating, new_phi * GLICKO_SCALE, prior.vol)

    mu, phi = prior.to_glicko2()

    # Step 3: variance v.
    inv_v = 0.0
    for opp_rating, opp_rd, _ in matches:
        mu_j = (opp_rating - 1500.0) / GLICKO_SCALE
        phi_j = opp_rd / GLICKO_SCALE
        g_phi_j = _g(phi_j)
        e_val = _E(mu, mu_j, phi_j)
        inv_v += g_phi_j * g_phi_j * e_val * (1.0 - e_val)
    if inv_v == 0:
        v = float("inf")
    else:
        v = 1.0 / inv_v

    # Step 4: Delta.
    delta_sum = 0.0
    for opp_rating, opp_rd, score in matches:
        mu_j = (opp_rating - 1500.0) / GLICKO_SCALE
        phi_j = opp_rd / GLICKO_SCALE
        g_phi_j = _g(phi_j)
        delta_sum += g_phi_j * (score - _E(mu, mu_j, phi_j))
    delta = v * delta_sum

    # Step 5 (volatility iterative update) — SKIPPED for prototype; sigma held constant.
    sigma = prior.vol

    # Step 6: pre-rating-period phi*.
    phi_star = math.sqrt(phi * phi + sigma * sigma)

    # Step 7: new phi'.
    new_phi = 1.0 / math.sqrt(1.0 / (phi_star * phi_star) + 1.0 / v)

    # Step 8: new mu'.
    new_mu = mu + new_phi * new_phi * delta_sum

    # Step 9: convert back.
    new_rating = new_mu * GLICKO_SCALE + 1500.0
    new_rd = new_phi * GLICKO_SCALE

    return GlickoRating(new_rating, new_rd, sigma)


def compute_ratings() -> pd.DataFrame:
    """Walk closed prediction outcomes and produce a skill_ratings DataFrame."""
    con = duckdb.connect(str(WAREHOUSE_DB), read_only=True)
    try:
        rows = con.execute(
            """
            SELECT p.user_id, p.outcome, p.made_at, u.acquisition_source
            FROM fact_prediction p
            JOIN dim_user u ON u.user_id = p.user_id
            WHERE p.is_outcome_resolved = TRUE
              AND p.outcome IS NOT NULL
            ORDER BY p.user_id, p.made_at
            """
        ).fetchall()
    finally:
        con.close()

    score_for = {"WIN": 1.0, "LOSS": 0.0, "DRAW": 0.5}

    matches_by_user: dict[str, list[tuple[float, float, float]]] = {}
    channel_by_user: dict[str, str] = {}
    outcomes_by_user: dict[str, list[str]] = {}

    for user_id, outcome, _made_at, channel in rows:
        if outcome not in score_for:
            continue
        matches_by_user.setdefault(user_id, []).append((MARKET_RATING, MARKET_RD, score_for[outcome]))
        channel_by_user[user_id] = channel
        outcomes_by_user.setdefault(user_id, []).append(outcome)

    out_rows = []
    for user_id, matches in matches_by_user.items():
        if len(matches) < 2:  # require >= 2 closed outcomes per spec
            continue
        rating = GlickoRating(INIT_RATING, INIT_RD, INIT_VOL)
        rating = update_glicko2(rating, matches)
        n = len(matches)
        n_correct = sum(1 for o in outcomes_by_user[user_id] if o == "WIN")
        out_rows.append(
            dict(
                user_id=user_id,
                mu=rating.rating,
                phi=rating.rd,
                sigma=rating.vol,
                n_predictions=n,
                n_correct=n_correct,
                acquisition_channel=channel_by_user.get(user_id, "unknown"),
            )
        )

    return pd.DataFrame(out_rows)


def run() -> None:
    df = compute_ratings()
    SKILL_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(SKILL_PARQUET, index=False)
    print(f"wrote {SKILL_PARQUET}  rows={len(df)}", file=sys.stderr)
    print(f"  mu range: {df['mu'].min():.0f} .. {df['mu'].max():.0f}", file=sys.stderr)
    print(f"  mean mu: {df['mu'].mean():.0f}  median mu: {df['mu'].median():.0f}", file=sys.stderr)
    print(f"  by channel:\n{df.groupby('acquisition_channel')['mu'].agg(['mean', 'median', 'count'])}", file=sys.stderr)


# ---------------------------------------------------------------------------
# MetricResult-wrapped distribution tool — for the agent.
# ---------------------------------------------------------------------------

@versioned("1.0.0")
def get_skill_distribution(channel: Optional[str] = None, cohort: Optional[str] = None) -> MetricResult:
    """Mean / median / std of mu over a filtered subset; high-skill (mu>1600)
    and low-skill (mu<1400) fractions surfaced.

    cohort is currently a stub (W01 only) — future versions filter by signup week.
    """
    if not SKILL_PARQUET.exists():
        raise FileNotFoundError(f"{SKILL_PARQUET} missing — run `make skill` first.")
    df = pd.read_parquet(SKILL_PARQUET)
    if channel and channel != "all":
        df = df[df["acquisition_channel"] == channel]
    if df.empty:
        return MetricResult(
            metric_name="skill_distribution",
            value=1500.0,
            confidence=0.0,
            sample_n=0,
            provenance=[f"channel:{channel}", "no_users_with_closed_outcomes"],
            window_open=False,
            interpretation=f"No users with >= 2 closed outcomes matched the filter (channel={channel}).",
            trace=[
                f"skill_distribution = 1500 (Glicko-2 prior) because no users matched channel={channel} with >= 2 closed outcomes.",
                f"this is the cold-start signal: an empty filter is information itself — propose data collection, not a point estimate.",
                f"confidence = 0.00: there is nothing to estimate.",
            ],
        )
    mean_mu = float(df["mu"].mean())
    median_mu = float(df["mu"].median())
    std_mu = float(df["mu"].std())
    n = int(len(df))
    high = int((df["mu"] > 1600).sum())
    low = int((df["mu"] < 1400).sum())
    high_pct = high / n
    low_pct = low / n

    # Confidence shaped by sample coverage: large n → high conf.
    confidence = min(0.95, 0.40 + 0.55 * min(1.0, n / 500))

    interp = (
        f"Mean Glicko-2 mu = {mean_mu:.0f} (median {median_mu:.0f}, std {std_mu:.0f}) "
        f"over {n} users with >= 2 closed outcomes "
        f"(channel={channel or 'all'}). "
        f"High-skill (mu > 1600) = {high_pct:.1%}; low-skill (mu < 1400) = {low_pct:.1%}."
    )
    trace = [
        f"skill_distribution mean mu = {mean_mu:.0f} over {n} users (channel={channel or 'all'}); median {median_mu:.0f}, std {std_mu:.0f}.",
        f"high-skill (mu > 1600): {high_pct:.1%} ({high} users); low-skill (mu < 1400): {low_pct:.1%} ({low}). The brief's 'latent skill curve' is the long tail in both directions.",
        f"confidence = {confidence:.2f}: scales with n (clamped to 0.95); estimator is simplified Glicko-2 with no volatility update — phi drops faster than a full implementation would justify.",
    ]
    return MetricResult(
        metric_name="skill_distribution",
        value=mean_mu,
        confidence=confidence,
        sample_n=n,
        provenance=[
            f"channel_filter:{channel or 'all'}",
            f"n_users:{n}",
            f"high_skill:{high}",
            f"low_skill:{low}",
            "estimator:glicko2_simplified_no_volatility_update",
        ],
        window_open=False,
        interpretation=interp,
        trace=trace,
        definition_version="1.0.0",
        breakdowns=dict(mean=mean_mu, median=median_mu, std=std_mu, high_pct=high_pct, low_pct=low_pct, n=n),
    )


if __name__ == "__main__":
    run()
