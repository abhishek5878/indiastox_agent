"""Eval harness — runs the Growth Agent against the 10 canonical questions
and scores answers on (accuracy, calibration, action). Max 3 per question,
30 total.

Honest scoring: a question with `ground_truth_sql: null` is genuinely
unknowable (Q10) — accuracy=1 if the agent acknowledges this, 0 if it
gives a confident wrong number. Q08 uses a non-SQL ground-truth path
(per-channel skill comparison in Python).

Output: eval/results/run_{timestamp}.json with per-question + total score
and the full agent transcript.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
import yaml

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agent.growth_agent import AgentAnswer, GrowthAgent
from mcp.tools import ToolSession

QUESTIONS_YAML = _REPO / "eval" / "canonical_questions.yaml"
WAREHOUSE = _REPO / "warehouse" / "indiastox.duckdb"
RESULTS_DIR = _REPO / "eval" / "results"
SKILL_PARQUET = _REPO / "data" / "skill_ratings.parquet"


def _resolve_ground_truth(q: dict) -> tuple[float | None, str]:
    """Returns (gt_value, kind). kind is 'numeric', 'unknowable', or 'skill_winner'."""
    if q.get("ground_truth_sql"):
        con = duckdb.connect(str(WAREHOUSE), read_only=True)
        try:
            row = con.execute(q["ground_truth_sql"]).fetchone()
            val = float(row[0]) if row and row[0] is not None else None
        finally:
            con.close()
        return val, "numeric"

    kind = q.get("ground_truth_kind") or "unknowable"
    if kind == "skill_distribution_winner":
        if not SKILL_PARQUET.exists():
            return None, "skill_winner_unbuilt"
        df = pd.read_parquet(SKILL_PARQUET)
        by_ch = df.groupby("acquisition_channel")["mu"].mean()
        if by_ch.empty:
            return None, "skill_winner_empty"
        winner = by_ch.idxmax()
        return float(by_ch.max() - 1500.0), "skill_winner:" + winner
    return None, "unknowable"


def _score_accuracy(agent_val: float | None, gt_val: float | None, gt_kind: str, tolerance: float | None) -> int:
    """Returns 0 or 1."""
    if gt_kind.startswith("unknowable"):
        # Agent must NOT give a confident wrong number. Agent.value=None means
        # the agent correctly acknowledged the limit.
        return 1 if agent_val is None else 0
    if gt_kind.startswith("skill_winner"):
        # Tolerance is mu points; agent.value is the winning channel's mean mu - 1500
        # (deviation from market baseline). If the agent reported "no difference"
        # (value=None), accept that as a calibrated answer when |gt| < tolerance.
        if agent_val is None:
            return 1 if abs(gt_val or 0) < (tolerance or 50) else 0
        return 1 if abs((agent_val - (gt_val or 0))) <= (tolerance or 50) else 0
    if gt_val is None or agent_val is None:
        return 0
    if gt_val == 0:
        return 1 if abs(agent_val) <= (tolerance or 0.01) else 0
    return 1 if abs(agent_val - gt_val) / abs(gt_val) <= (tolerance or 0.02) else 0


def _score_markers(text: str, markers: list[str]) -> int:
    """1 if all markers (case-insensitive substring) are present, else 0."""
    if not markers:
        return 0
    lt = text.lower()
    return 1 if all(m.lower() in lt for m in markers) else 0


def run() -> dict:
    spec = yaml.safe_load(QUESTIONS_YAML.read_text())
    week = spec["week_of"]
    questions = spec["questions"]

    session = ToolSession()
    agent = GrowthAgent(session=session, week=week)

    results = []
    total = 0
    max_total = 0

    for q in questions:
        ans: AgentAnswer = agent.answer(q["id"], q["text"])
        gt_val, gt_kind = _resolve_ground_truth(q)
        accuracy = _score_accuracy(ans.value, gt_val, gt_kind, q.get("tolerance"))
        calibration = _score_markers(ans.calibration, q.get("calibration_markers", []))
        action = _score_markers(ans.action, q.get("action_markers", []))
        q_score = accuracy + calibration + action
        q_max = 3
        total += q_score
        max_total += q_max

        results.append(dict(
            id=q["id"],
            text=q["text"],
            ground_truth=gt_val,
            ground_truth_kind=gt_kind,
            agent_value=ans.value,
            agent_calibration=ans.calibration,
            agent_action=ans.action,
            scores=dict(accuracy=accuracy, calibration=calibration, action=action, total=q_score, max=q_max),
        ))

    payload = dict(
        ts=datetime.now(timezone.utc).isoformat(),
        session_id=session.session_id,
        week_of=week,
        total_score=total,
        max_total=max_total,
        results=results,
    )
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.json"
    out.write_text(json.dumps(payload, indent=2, default=str))

    print(f"\nEval — week {week}  session={session.session_id}")
    print("=" * 70)
    for r in results:
        s = r["scores"]
        print(f"  {r['id']}  acc={s['accuracy']}  cal={s['calibration']}  act={s['action']}  → {s['total']}/{s['max']}")
        print(f"        agent_value={r['agent_value']}  ground_truth={r['ground_truth']}  ({r['ground_truth_kind']})")
    print("=" * 70)
    print(f"  TOTAL: {total}/{max_total}")
    print(f"  wrote {out}")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="output the full payload to stdout")
    parser.add_argument("--no-improvement-pass", action="store_true",
                        help="skip the auto-triggered improvement agent")
    args = parser.parse_args()
    payload = run()

    if not args.no_improvement_pass:
        # Layer F: the eval loop closes on itself. Auto-trigger the
        # improvement agent so a fresh PROPOSED_IMPROVEMENTS.md lands
        # right next to the scorecard.
        print()
        from agent.improvement_agent import run as run_improvement
        run_improvement()

    if args.json:
        print(json.dumps(payload, indent=2, default=str))
