"""Bonus — closed-loop experiment proposer.

Reads ghost_rate from the metric layer (current week vs prior week),
detects a >10pp delta, writes:

  - bonus/proposals/2024-W01-ghost-rate-spike.json   (the proposal)
  - bonus/notion/2024-W01-ghost-rate-experiment.md   (the Notion stand-in)
  - raw/agent_actions.ndjson                         (the proposal-event,
                                                      appended to the same
                                                      event stream that
                                                      produced the finding)

No LLM needed. Pure rule-based logic over the metric layer. The whole
point is that the *action* is itself an event in the same stream — so a
future agent or human can see "the dashboard finding produced this
proposal at this time" without leaving the substrate.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Allow `python3 bonus/experiment_loop.py` from the repo root.
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from metrics.definitions import ghost_rate, MetricResult

REPO = Path(__file__).resolve().parents[1]
PROPOSALS_DIR = REPO / "bonus" / "proposals"
NOTION_DIR = REPO / "bonus" / "notion"
AGENT_ACTIONS = REPO / "raw" / "agent_actions.ndjson"

WEEK_THIS = "2024-W01"
WEEK_PRIOR = "2023-W52"
DELTA_PP_THRESHOLD = 0.10  # 10 percentage points

PRIOR_WEEK_HARDCODED_GHOST_RATE = 0.182  # per the brief's setup


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _serialize_metric(mr: MetricResult) -> dict:
    return dict(
        metric_name=mr.metric_name,
        value=mr.value,
        definition_version=mr.definition_version,
        is_complete=mr.is_complete,
        confidence_interval=list(mr.confidence_interval) if mr.confidence_interval else None,
        as_of=mr.as_of.isoformat(),
        breakdowns=mr.breakdowns,
        # Trim long SQL from the serialized proposal so the JSON stays scannable.
        computation_sql_first_120c=(mr.computation_sql or "")[:120].replace("\n", " "),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prior-rate", type=float, default=PRIOR_WEEK_HARDCODED_GHOST_RATE,
                        help="Prior-week ghost_rate to compare against (no W52 data in the prototype).")
    args = parser.parse_args()

    # Current week — call the metric function. NEVER inline SQL.
    current = ghost_rate(WEEK_THIS, acquisition_source="unstop")
    current_rate = current.value

    prior_rate = args.prior_rate
    delta = current_rate - prior_rate

    if abs(delta) < DELTA_PP_THRESHOLD:
        print(
            f"ghost_rate delta = {delta:+.4f} (current={current_rate:.4f}, prior={prior_rate:.4f}) — "
            f"below {DELTA_PP_THRESHOLD:+.2f}pp threshold, no proposal.",
            file=sys.stderr,
        )
        sys.exit(0)

    proposal_id = f"PROP-{uuid.uuid4().hex[:12]}"
    finding = (
        f"ghost_rate jumped from {prior_rate * 100:.1f}% to {current_rate * 100:.1f}% "
        f"for Unstop cohort (Δ {delta * 100:+.1f}pp)"
    )

    proposal = dict(
        proposal_id=proposal_id,
        title=f"Ghost Rate Spike — Unstop Cohort {WEEK_THIS}",
        finding=finding,
        metric_values=dict(
            current=_serialize_metric(current),
            prior=dict(
                metric_name="ghost_rate",
                value=prior_rate,
                definition_version=current.definition_version,
                source="hardcoded_prior_week_baseline",
            ),
            delta=delta,
        ),
        hypothesis=(
            "UTM landing page mismatch between Unstop ad creative and challenge landing page "
            "increases bounce before signup completion."
        ),
        proposed_experiment=(
            "A/B test Unstop landing page: control = /challenge, variant = /challenge?cohort=unstop "
            "with personalized copy referencing college context."
        ),
        expected_lift="10-15pp reduction in ghost_rate for Unstop cohort",
        generated_at=_utc_now_iso(),
        generator="bonus_loop_v1",
    )

    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    out = PROPOSALS_DIR / f"{WEEK_THIS}-ghost-rate-spike.json"
    out.write_text(json.dumps(proposal, indent=2))
    print(f"wrote {out}", file=sys.stderr)

    # Notion stand-in. Frontmatter + body.
    NOTION_DIR.mkdir(parents=True, exist_ok=True)
    notion_path = NOTION_DIR / f"{WEEK_THIS}-ghost-rate-experiment.md"
    notion_md = (
        f"---\n"
        f"title: \"Ghost Rate Spike — Unstop Cohort {WEEK_THIS}\"\n"
        f"status: \"proposed\"\n"
        f"owner: \"growth\"\n"
        f"tags: [\"ghost-rate\", \"unstop\", \"experiment\"]\n"
        f"proposal_id: \"{proposal_id}\"\n"
        f"generated_at: \"{proposal['generated_at']}\"\n"
        f"---\n\n"
        f"# {proposal['title']}\n\n"
        f"## Finding\n\n{finding}\n\n"
        f"## Hypothesis\n\n{proposal['hypothesis']}\n\n"
        f"## Proposed experiment\n\n{proposal['proposed_experiment']}\n\n"
        f"## Expected lift\n\n{proposal['expected_lift']}\n\n"
        f"## Source metric\n\n"
        f"- `ghost_rate` v{current.definition_version}\n"
        f"- as_of: `{current.as_of.isoformat()}`\n"
        f"- is_complete: `{current.is_complete}` "
        f"(if False the cohort window hasn't fully closed — proposal stands but reconfirm before launching)\n"
    )
    notion_path.write_text(notion_md)
    print(f"wrote {notion_path}", file=sys.stderr)

    # Append agent_actions.ndjson event — same stream as the data that produced
    # the finding. Auditability is the load-bearing property here.
    AGENT_ACTIONS.parent.mkdir(parents=True, exist_ok=True)
    event = dict(
        event_type="experiment_proposed",
        proposal_id=proposal_id,
        metric_name="ghost_rate",
        metric_definition_version=current.definition_version,
        delta=round(delta, 4),
        proposed_at=proposal["generated_at"],
        source="bonus_loop_v1",
    )
    with AGENT_ACTIONS.open("a") as f:
        f.write(json.dumps(event, separators=(",", ":")) + "\n")
    print(f"appended event to {AGENT_ACTIONS}: {event}", file=sys.stderr)


if __name__ == "__main__":
    main()
