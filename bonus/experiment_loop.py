"""Closed-loop experiment proposer.

Reads ghost_rate from the metric layer, detects a >10pp delta vs a
prior-week baseline, and writes the proposal end-to-end:

  - proposals/pending/{proposal_id}.yaml        (the proposal artifact)
  - DuckDB `proposals` table                    (insert with status='pending')
  - DuckDB `agent_actions` table                (the proposal-triggering tool call,
                                                  with downstream_proposal_id wired)
  - bonus/notion/{week}-experiment.md           (Notion stand-in)
  - raw/agent_actions.ndjson                    (the proposal-event in the same
                                                  raw event stream as the data)

Approval flow:

  python3 -m bonus.approve PROPOSAL_ID=<id>

…moves proposals/pending/<id>.yaml → proposals/approved/, updates the
proposals.status field in DuckDB, and inserts a `proposal_approved`
row into agent_actions. Status lifecycle is fully observable from the
DuckDB tables.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import yaml

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from core.confidence import MetricResult
from mcp.tools import ToolSession

PROPOSALS_PENDING = _REPO / "proposals" / "pending"
PROPOSALS_APPROVED = _REPO / "proposals" / "approved"
PROPOSALS_EXECUTED = _REPO / "proposals" / "executed"
NOTION_DIR = _REPO / "bonus" / "notion"
AGENT_ACTIONS_NDJSON = _REPO / "raw" / "agent_actions.ndjson"
WAREHOUSE = _REPO / "warehouse" / "indiastox.duckdb"

WEEK_THIS = "2024-W01"
WEEK_PRIOR = "2023-W52"
DELTA_PP_THRESHOLD = 0.10  # 10 percentage points
PRIOR_WEEK_HARDCODED_GHOST_RATE = 0.182


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


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
            "experiment_loop_v2",
        ],
    )


def _link_action_to_proposal(con, action_id: str, proposal_id: str) -> None:
    con.execute(
        "UPDATE agent_actions SET downstream_proposal_id = ? WHERE action_id = ?",
        [proposal_id, action_id],
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prior-rate", type=float, default=PRIOR_WEEK_HARDCODED_GHOST_RATE)
    args = parser.parse_args()

    session = ToolSession()
    current = session.call("ghost_rate", week_of=WEEK_THIS, acquisition_source="unstop")
    delta = current.value - args.prior_rate

    if abs(delta) < DELTA_PP_THRESHOLD:
        print(
            f"ghost_rate delta = {delta:+.4f} (current={current.value:.4f}, prior={args.prior_rate:.4f}) — "
            f"below {DELTA_PP_THRESHOLD:+.2f}pp threshold, no proposal.",
            file=sys.stderr,
        )
        sys.exit(0)

    # Find the action_id we just logged so we can wire downstream_proposal_id.
    con = duckdb.connect(str(WAREHOUSE), read_only=False)
    try:
        row = con.execute(
            "SELECT action_id FROM agent_actions WHERE session_id = ? AND tool_name = ? ORDER BY ts DESC LIMIT 1",
            [session.session_id, "ghost_rate"],
        ).fetchone()
        triggered_by_action_id = row[0] if row else "(missing)"

        proposal_id = f"PROP-{uuid.uuid4().hex[:12]}"
        finding = (
            f"ghost_rate jumped from {args.prior_rate * 100:.1f}% to {current.value * 100:.1f}% "
            f"for Unstop cohort (Δ {delta * 100:+.1f}pp)"
        )
        proposal = dict(
            proposal_id=proposal_id,
            created_ts=_utc_now().isoformat().replace("+00:00", "Z"),
            triggered_by_action_id=triggered_by_action_id,
            hypothesis=(
                "UTM landing page mismatch between Unstop ad creative and challenge landing page "
                "increases bounce before signup completion."
            ),
            affected_metric="ghost_rate",
            expected_lift_pct=-12.0,  # 12pp reduction in ghost_rate
            confidence=0.55,
            required_sample_n=500,
            estimated_days=14,
            finding=finding,
            proposed_experiment=(
                "A/B test Unstop landing page: control = /challenge, variant = /challenge?cohort=unstop "
                "with personalized copy referencing college context."
            ),
            metric_snapshot=dict(
                metric_name=current.metric_name,
                value=current.value,
                confidence=current.confidence,
                sample_n=current.sample_n,
                window_open=current.window_open,
                definition_version=current.definition_version,
                provenance=current.provenance,
                interpretation=current.interpretation,
            ),
            generator="experiment_loop_v2",
        )

        # 1. proposals/pending/{id}.yaml
        PROPOSALS_PENDING.mkdir(parents=True, exist_ok=True)
        out_yaml = PROPOSALS_PENDING / f"{proposal_id}.yaml"
        out_yaml.write_text(yaml.safe_dump(proposal, sort_keys=False))
        print(f"wrote {out_yaml}", file=sys.stderr)

        # 2. DuckDB proposals.insert
        _insert_proposal(con, proposal, triggered_by_action_id)
        # 3. Link the action to the proposal.
        _link_action_to_proposal(con, triggered_by_action_id, proposal_id)
        print(f"inserted proposals row {proposal_id}; linked action {triggered_by_action_id}", file=sys.stderr)

        # 4. Notion stand-in.
        NOTION_DIR.mkdir(parents=True, exist_ok=True)
        notion_path = NOTION_DIR / f"{WEEK_THIS}-ghost-rate-experiment.md"
        notion_path.write_text(
            f"---\n"
            f"title: \"Ghost Rate Spike — Unstop Cohort {WEEK_THIS}\"\n"
            f"status: \"proposed\"\nowner: \"growth\"\n"
            f"tags: [\"ghost-rate\", \"unstop\", \"experiment\"]\n"
            f"proposal_id: \"{proposal_id}\"\n"
            f"---\n\n# {finding}\n\n"
            f"## Hypothesis\n{proposal['hypothesis']}\n\n"
            f"## Proposed experiment\n{proposal['proposed_experiment']}\n\n"
            f"## Expected lift\n{proposal['expected_lift_pct']:+.0f}pp ghost_rate, "
            f"confidence {proposal['confidence']:.2f}\n\n"
            f"## Source metric\n- v{current.definition_version}  "
            f"`ghost_rate(2024-W01, unstop) = {current.value:.4f}` (confidence {current.confidence:.2f})\n"
        )
        print(f"wrote {notion_path}", file=sys.stderr)

        # 5. agent_actions.ndjson — same event stream as the underlying data.
        AGENT_ACTIONS_NDJSON.parent.mkdir(parents=True, exist_ok=True)
        with AGENT_ACTIONS_NDJSON.open("a") as f:
            f.write(json.dumps(dict(
                event_type="experiment_proposed",
                proposal_id=proposal_id,
                triggered_by_action_id=triggered_by_action_id,
                metric_name="ghost_rate",
                delta=round(delta, 4),
                proposed_at=proposal["created_ts"],
                source="experiment_loop_v2",
            ), separators=(",", ":")) + "\n")
        print(f"appended event to {AGENT_ACTIONS_NDJSON}", file=sys.stderr)
    finally:
        con.close()

    # 6. Layer K — pair every proposal with its strongest counter-argument
    #    BEFORE a human ever sees it. The critic_agent attaches a `critique`
    #    section to the YAML and logs a critique_proposal action.
    try:
        from agent.critic_agent import critique as _critique
        crit = _critique(proposal_id, write_back=True)
        print(f"critic_agent: severity={crit['severity']}; counter logged to YAML + agent_actions", file=sys.stderr)
    except Exception as e:
        print(f"WARN: critic_agent failed ({e}); proposal stands without critique", file=sys.stderr)


if __name__ == "__main__":
    main()
