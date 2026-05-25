"""Auto-file the top insight as a Proposal (P7b growth-hack adapter).

The insights extractor (P7) produces a ranked list of observations,
each carrying a `suggested_experiment` field. P7b closes the loop:
takes that suggested_experiment and files it as a Proposal through the
same path `bonus/experiment_loop.py` uses, so the Critic + readout +
calibration loop pick it up unchanged.

Output of `file_top_insight()`:
  - YAML at `proposals/pending/PROP-XXX.yaml`
  - row in `proposals` table (status='pending')
  - row in `agent_actions` table (linked via downstream_proposal_id)
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import duckdb
import yaml

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agent.insights import Insight, generate_insights

WAREHOUSE = _REPO / "warehouse" / "indiastox.duckdb"
PROPOSALS_PENDING = _REPO / "proposals" / "pending"
NOTION_DIR = _REPO / "bonus" / "notion"
AGENT_ACTIONS_NDJSON = _REPO / "raw" / "agent_actions.ndjson"

AUTO_PROPOSAL_VERSION = "1.0.0"

# Heuristic: insights below this score aren't strong enough to commit
# eng/ops cycles to. Tunable.
SURPRISE_FLOOR = 0.30


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _heuristic_lift_pct(insight: Insight) -> float:
    """Convert an insight's surprise_score into an expected_lift_pct
    estimate. Conservative — assume the suggested experiment delivers
    a fraction of the surprise gap.

    For near-miss insights (where surprise IS the gap), aim for full
    closure. For design-surprise insights, aim for half-closure.
    """
    if insight.kind == "near_miss_aspirant":
        # Closing the gap moves the affected user from aspirant -> locked,
        # which at the cohort level translates to ~the surprise score in pp.
        return round(insight.surprise_score * 10.0, 2)
    if insight.kind == "archetype_design_surprise":
        return round(insight.surprise_score * 50.0, 2)
    if insight.kind == "funnel_gate_clog":
        return round(insight.surprise_score * 20.0, 2)
    return round(insight.surprise_score * 15.0, 2)


def _kind_to_metric(insight: Insight) -> str:
    """Map insight kind -> the affected_metric a proposal targets."""
    return {
        "near_miss_aspirant": "gyaani_locked_share",
        "archetype_design_surprise": "gyaani_aspirant_share",
        "funnel_gate_clog": "funnel_stages",
        "axis_outlier_mu": "gyaani_aspirant_share",
    }.get(insight.kind, "gyaani_aspirant_share")


def _required_sample_n(insight: Insight) -> int:
    """Conservative sample-size requirement per insight kind."""
    return {
        "near_miss_aspirant": 50,         # cohort of aspirants is bounded
        "archetype_design_surprise": 200,
        "funnel_gate_clog": 500,
        "axis_outlier_mu": 200,
    }.get(insight.kind, 200)


def _insert_proposal(con, proposal: dict, triggered_by_action_id: str) -> None:
    con.execute(
        """INSERT INTO proposals
           (proposal_id, created_ts, triggered_by_action_id, hypothesis, affected_metric,
            expected_lift_pct, confidence, required_sample_n, estimated_days,
            status, _source_system)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        [
            proposal["proposal_id"],
            datetime.fromisoformat(proposal["created_ts"].replace("Z", "+00:00")),
            triggered_by_action_id,
            proposal["hypothesis"],
            proposal["affected_metric"],
            proposal["expected_lift_pct"],
            proposal["confidence"],
            proposal["required_sample_n"],
            proposal["estimated_days"],
            "pending",
            "auto_proposal_v1",
        ],
    )


def _log_agent_action(action_id: str, tool_name: str, args: dict,
                      proposal_id: str) -> None:
    """Append a row to raw/agent_actions.ndjson (the append-only audit log).
    Mirrors the pattern used by experiment_loop + the ToolSession."""
    AGENT_ACTIONS_NDJSON.parent.mkdir(parents=True, exist_ok=True)
    event = dict(
        action_id=action_id,
        ts=_utc_now().isoformat().replace("+00:00", "Z"),
        session_id=f"auto-{uuid.uuid4().hex[:10]}",
        tool_name=tool_name,
        args=args,
        downstream_proposal_id=proposal_id,
        generator="auto_proposal_v1",
    )
    with AGENT_ACTIONS_NDJSON.open("a") as fh:
        fh.write(json.dumps(event) + "\n")


def file_top_insight(week_of: str = "2024-W01",
                     surprise_floor: float = SURPRISE_FLOOR) -> dict:
    """Run insights_generate, pick the top, file it as a Proposal.

    Returns a dict describing what happened:
      {
        "filed": bool,
        "reason": str,             # why filed / why not
        "proposal_id": str | None,
        "insight": Insight.to_dict() | None,
      }

    Idempotency: this is a write operation. Calling twice files two
    proposals. Use sparingly (cron once a day, or on-demand from the
    Growth Agent). The proposals table dedupes nothing; that's a
    deliberate signal that the substrate is generating insight-driven
    proposals at a measurable cadence.
    """
    insights = generate_insights(week_of)
    if not insights:
        return dict(filed=False, reason="no insights cleared scanner floors",
                    proposal_id=None, insight=None)
    top = insights[0]
    if top.surprise_score < surprise_floor:
        return dict(
            filed=False,
            reason=f"top insight surprise={top.surprise_score:.2f} below floor {surprise_floor:.2f}",
            proposal_id=None,
            insight=top.to_dict(),
        )

    proposal_id = f"PROP-{uuid.uuid4().hex[:12]}"
    action_id = f"act-{uuid.uuid4().hex[:12]}"
    proposal = dict(
        proposal_id=proposal_id,
        created_ts=_utc_now().isoformat().replace("+00:00", "Z"),
        triggered_by_action_id=action_id,
        hypothesis=top.summary,
        affected_metric=_kind_to_metric(top),
        expected_lift_pct=_heuristic_lift_pct(top),
        confidence=0.55,  # heuristic-generated, not RCT-grade
        required_sample_n=_required_sample_n(top),
        estimated_days=14,
        finding=top.summary,
        proposed_experiment=top.suggested_experiment,
        insight_kind=top.kind,
        insight_surprise=top.surprise_score,
        generator="auto_proposal_v1",
    )

    # 1) YAML to proposals/pending/
    PROPOSALS_PENDING.mkdir(parents=True, exist_ok=True)
    yaml_path = PROPOSALS_PENDING / f"{proposal_id}.yaml"
    yaml_path.write_text(yaml.safe_dump(proposal, sort_keys=False))

    # 2) DuckDB insert + agent_actions audit
    con = duckdb.connect(str(WAREHOUSE), read_only=False)
    try:
        _insert_proposal(con, proposal, action_id)
    finally:
        con.close()
    _log_agent_action(action_id, "auto_propose_top_insight",
                      dict(week_of=week_of, insight_kind=top.kind), proposal_id)

    return dict(
        filed=True,
        reason=f"top insight surprise={top.surprise_score:.2f} above floor",
        proposal_id=proposal_id,
        yaml_path=str(yaml_path),
        insight=top.to_dict(),
    )


def main() -> int:
    """CLI: `python3 -m agent.auto_proposal` runs file_top_insight() once."""
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--week", default="2024-W01")
    p.add_argument("--floor", type=float, default=SURPRISE_FLOOR)
    args = p.parse_args()
    result = file_top_insight(week_of=args.week, surprise_floor=args.floor)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["filed"] else 2


if __name__ == "__main__":
    sys.exit(main())
