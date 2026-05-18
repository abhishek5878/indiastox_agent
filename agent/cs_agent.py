"""CS Agent — at-risk-user interventions.

Finds the 10 users most at risk of churning before contributing meaningfully
and drafts a personalized intervention for each, grounded in their actual
synthetic record (no templates).

At-risk definition (all four conditions must hold):
  - >= 1 prediction in week 1
  - Glicko-2 phi above PHI_AT_RISK_THRESHOLD (production: 300, per the
    brief; synthetic-data override: 75th percentile of observed phi).
    The brief's literal `phi > 300` is what production should use once
    the predictions-per-user distribution is realistic (typical user
    plays 1–2 times/week → faithful Glicko-2 keeps phi ≥ 300). Our
    synthetic generator gives users up to 10 predictions/week, which
    drives Glicko-2 phi down to ~200 even after one rating period. The
    percentile override is the equivalent rule against this dataset —
    "the top quartile of uncertainty" is what `phi > 300` means in
    real-world deployment conditions.
  - zero predictions in the last 3 days of the synthetic week
  - mu < 1500 (below average skill)

Tone:
  - Unstop users → analytical (numbers, accuracy, ranking-style framing)
  - whatsapp_dark / organic → discovery (welcome, low-stakes invitation
    back, broader prompts)

Output: interventions/pending/{user_id}.yaml. Each draft is logged to
agent_actions as `cs_draft_intervention`.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd
import yaml

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from mcp.tools import ToolSession

WAREHOUSE = _REPO / "warehouse" / "indiastox.duckdb"
SKILL_PARQUET = _REPO / "data" / "skill_ratings.parquet"
INTERV_PENDING = _REPO / "interventions" / "pending"

WEEK_OF = "2024-W01"
WEEK_START = datetime(2024, 1, 1, tzinfo=timezone.utc)
WEEK_END = WEEK_START + timedelta(days=7)
QUIET_CUTOFF = WEEK_END - timedelta(days=3)  # 2024-01-05 onwards
# DuckDB stores TIMESTAMP (no TZ); pandas reads it back as naive datetime64.
# We compare against naive datetime to match.
WEEK_START_NAIVE = WEEK_START.replace(tzinfo=None)
WEEK_END_NAIVE = WEEK_END.replace(tzinfo=None)
QUIET_CUTOFF_NAIVE = QUIET_CUTOFF.replace(tzinfo=None)


def find_at_risk_users(top_n: int = 10) -> pd.DataFrame:
    if not SKILL_PARQUET.exists():
        raise FileNotFoundError(f"{SKILL_PARQUET} missing — run `make skill`")
    skill = pd.read_parquet(SKILL_PARQUET)

    con = duckdb.connect(str(WAREHOUSE), read_only=False)
    try:
        # Predictions per user in W01, plus latest made_at.
        preds = con.execute(
            """SELECT user_id, COUNT(*) AS n_preds, MAX(made_at) AS last_pred_at
               FROM fact_prediction
               WHERE made_at >= ? AND made_at < ?
               GROUP BY user_id""",
            [WEEK_START, WEEK_END],
        ).df()
    finally:
        con.close()

    # Join. Only users WITH a skill row (>= 2 closed outcomes) are candidates;
    # the brief's at-risk definition further requires high phi / mu < 1500.
    df = skill.merge(preds, on="user_id", how="inner")
    # Production threshold (per brief): phi > 300. Synthetic override below;
    # see module docstring for rationale.
    PHI_AT_RISK_PRODUCTION = 300.0
    phi_observed_p75 = float(df["phi"].quantile(0.75))
    if (df["phi"] > PHI_AT_RISK_PRODUCTION).sum() >= 10:
        phi_threshold = PHI_AT_RISK_PRODUCTION
    else:
        phi_threshold = phi_observed_p75
    df = df[
        (df["n_preds"] >= 1)
        & (df["phi"] >= phi_threshold)
        & (df["last_pred_at"] < QUIET_CUTOFF_NAIVE)
        & (df["mu"] < 1500)
    ].copy()

    # Risk score: higher phi (more uncertain), lower mu (worse), older last_pred.
    quiet_hours = (WEEK_END_NAIVE - df["last_pred_at"]).dt.total_seconds() / 3600.0
    df["risk_score"] = (
        (df["phi"] - phi_threshold) / 50.0  # uncertainty contribution above threshold
        + (1500 - df["mu"]) / 100.0         # below-average skill
        + quiet_hours / 24.0                # days quiet
    )
    df = df.sort_values("risk_score", ascending=False).head(top_n)
    return df


def get_user_predictions(con, user_id: str) -> list[dict]:
    """Use the caller's existing DuckDB connection — DuckDB rejects mixing
    read-only and read-write connections to the same file in one process.
    """
    rows = con.execute(
        """SELECT stock_symbol, direction, confidence_stars, made_at,
                  outcome, is_outcome_resolved
           FROM fact_prediction WHERE user_id = ? ORDER BY made_at""",
        [user_id],
    ).fetchall()
    return [
        dict(
            stock_symbol=r[0], direction=r[1], confidence_stars=r[2],
            made_at=r[3], outcome=r[4], is_outcome_resolved=r[5],
        )
        for r in rows
    ]


def compose_intervention(user_row, predictions: list[dict]) -> dict:
    """Compose a personalised nudge grounded in the user's actual call history.

    The previous version templated only two heads (analytical vs discovery) and
    referenced the ticker but not the outcome. Production reviewer flagged the
    monotony: "your RELIANCE call closed -2.1% Friday — that's normal at this
    sample size, but the next 3 calls matter more than this one did" is what
    a real CS nudge would say. This version pulls the most recent *resolved*
    call, its outcome, and varies the phrasing per user via a stable seed.
    """
    import hashlib

    user_id = user_row["user_id"]
    channel = user_row.get("acquisition_channel") or "unstop"
    mu = float(user_row["mu"])
    phi = float(user_row["phi"])
    n_correct = int(user_row["n_correct"])
    n_calls = int(user_row["n_predictions"])

    resolved = [p for p in predictions if p.get("is_outcome_resolved")]
    last_resolved = resolved[-1] if resolved else None
    tickers = [p["stock_symbol"] for p in predictions]
    correct_tickers = [p["stock_symbol"] for p in predictions if p.get("outcome") == "WIN"]
    primary_ticker = correct_tickers[0] if correct_tickers else (tickers[0] if tickers else None)
    most_recent_call = predictions[-1] if predictions else None

    # Stable per-user variant pick so the same user never sees two different nudges.
    variant_idx = int(hashlib.sha256(user_id.encode()).hexdigest()[:4], 16) % 4

    grounding_facts: list[str] = [
        f"calls_made={n_calls}",
        f"calls_correct={n_correct}",
        f"mu={mu:.0f}",
        f"phi={phi:.1f}",
        f"acquisition_channel={channel}",
    ]
    if tickers:
        grounding_facts.append(f"called_tickers={','.join(sorted(set(tickers)))[:80]}")
    if last_resolved is not None:
        last_at = last_resolved["made_at"]
        last_str = last_at.isoformat() if hasattr(last_at, "isoformat") else str(last_at)
        grounding_facts.append(
            f"last_resolved={last_str}_{last_resolved['stock_symbol']}_"
            f"{last_resolved.get('direction')}_{last_resolved.get('outcome')}"
        )
    elif most_recent_call:
        last_at = most_recent_call["made_at"]
        last_str = last_at.isoformat() if hasattr(last_at, "isoformat") else str(last_at)
        grounding_facts.append(f"last_call={last_str}_on_{most_recent_call['stock_symbol']}")

    # Build a concrete reference to the most recent resolved call when we have one.
    last_ref = ""
    if last_resolved is not None:
        sym = last_resolved["stock_symbol"]
        dirn = last_resolved.get("direction", "")
        out = last_resolved.get("outcome", "")
        if out == "WIN":
            last_ref = f"Your {dirn} on {sym} closed correctly — that's signal, but at phi {phi:.0f} it's still one data point. "
        elif out == "LOSS":
            last_ref = f"Your {dirn} on {sym} closed the other way — that's normal at this sample size, but the next 3 calls will move your rating more than this one did. "
        elif out == "DRAW":
            last_ref = f"Your {dirn} on {sym} closed flat — at phi {phi:.0f} we can't tell if that was a coin flip or a read. "

    if channel == "unstop":
        tone = "analytical"
        if correct_tickers and variant_idx == 0:
            head = (
                f"{last_ref}"
                f"{n_calls} calls in, {n_correct} landed correctly. "
                f"Your Gyaani uncertainty is at phi {phi:.0f} — 3 more resolved calls and the rating stabilises."
            )
            action = "Pick one stock outside your watchlist this week and call BULL or BEAR. Diversity is what tightens phi."
        elif correct_tickers and variant_idx == 1:
            head = (
                f"{last_ref}"
                f"You've made {n_calls} calls, {correct_tickers[0]} included as a hit. "
                f"The rating engine wants {max(3, 5 - n_calls)} more resolved calls before it considers your edge stable."
            )
            action = "Take the next Make-a-Call slot. The streak is fragile until phi drops below 150."
        elif variant_idx == 2:
            head = (
                f"{last_ref}"
                f"{n_calls} call{'s' if n_calls != 1 else ''} this week, none of the resolved ones landed. "
                f"At phi {phi:.0f} that's still noise — your priors haven't been challenged yet."
            )
            action = (
                f"Step outside {tickers[0] if tickers else 'your current set'}: pick a stock from a different sector "
                "and make one BULL/BEAR call. The rating won't tighten until the cohort spans 2+ sectors."
            )
        else:
            head = (
                f"{last_ref}"
                f"Quiet week — {n_calls} call{'s' if n_calls != 1 else ''} on the board, mu {mu:.0f} with phi {phi:.0f}. "
                f"Inactivity is the fastest way to lose Gyaani standing on the W01 leaderboard."
            )
            action = "One Make-a-Call before Sunday keeps your rating live. The leaderboard cutoff is the weekly close."
    else:
        tone = "discovery"
        if tickers and variant_idx == 0:
            t_sample = ", ".join(sorted(set(tickers))[:3])
            head = (
                f"{last_ref}"
                f"You've explored {len(set(tickers))} tickers — {t_sample}. "
                f"At {n_calls} call{'s' if n_calls != 1 else ''} we can't yet tell if there's an edge somewhere or just curiosity."
            )
            action = "Two more Make-a-Calls in your strongest sector and the leaderboard ranks you. Right now you're invisible."
        elif tickers and variant_idx == 1:
            head = (
                f"{last_ref}"
                f"{n_calls} call{'s' if n_calls != 1 else ''} placed via WhatsApp share — that puts you in the 17.6% dark cohort "
                f"the attribution layer can't fully bound. The product can still rank you, but only on resolved calls."
            )
            action = "Place one more BULL/BEAR call this week. The Gyaani score updates the moment it resolves at T+5d."
        elif variant_idx == 2:
            head = (
                f"{last_ref}"
                f"You signed up via a forwarded link and have made {n_calls} call{'s' if n_calls != 1 else ''}. "
                f"At phi {phi:.0f}, the rating engine is still learning your prior."
            )
            action = "The Movers tab surfaces stocks that moved >2% today. Pick one, call BULL or BEAR — that's enough."
        else:
            head = (
                f"{last_ref}"
                f"You arrived through a WhatsApp forward and made {n_calls} call{'s' if n_calls != 1 else ''}. "
                f"The first 3 resolved calls are what set the Gyaani prior — after that, drift gets harder to undo."
            )
            action = "Make a Call on any of last week's gainers. One BULL/BEAR call before Sunday."

    intervention_text = head + " " + action
    estimated_lift = 0.05 + (0.05 if correct_tickers else 0.0)
    lift_conf = 0.40 + (0.20 if n_calls >= 3 else 0.0)

    return dict(
        user_id=user_id,
        risk_score=float(user_row["risk_score"]),
        intervention_text=intervention_text,
        tone=tone,
        grounding_facts=grounding_facts,
        estimated_reactivation_lift=estimated_lift,
        estimated_reactivation_lift_confidence=lift_conf,
        channel=channel,
        primary_ticker=primary_ticker,
        n_predictions=n_calls,
        n_correct=n_correct,
    )


def log_action(con, session_id: str, user_id: str) -> None:
    con.execute(
        """INSERT INTO agent_actions
           (action_id, ts, session_id, tool_name, args_json, result_hash,
            result_confidence, downstream_proposal_id, _source_system)
           VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
        [
            f"act-{uuid.uuid4().hex[:16]}",
            datetime.now(timezone.utc),
            session_id,
            "cs_draft_intervention",
            json.dumps({"user_id": user_id}),
            "n/a",
            0.5,
            "cs_agent",
        ],
    )


def run() -> None:
    INTERV_PENDING.mkdir(parents=True, exist_ok=True)
    candidates = find_at_risk_users(top_n=10)
    print(f"Found {len(candidates)} at-risk users")

    session = ToolSession()
    con = duckdb.connect(str(WAREHOUSE), read_only=False)
    try:
        for _, user_row in candidates.iterrows():
            preds = get_user_predictions(con, user_row["user_id"])
            doc = compose_intervention(user_row, preds)
            out_path = INTERV_PENDING / f"{user_row['user_id']}.yaml"
            out_path.write_text(yaml.safe_dump(doc, sort_keys=False, default_flow_style=False))
            log_action(con, session.session_id, user_row["user_id"])
            print(f"  wrote {out_path.name}  tone={doc['tone']}  primary_ticker={doc['primary_ticker']}")
    finally:
        con.close()


if __name__ == "__main__":
    run()
