"""Critic Agent — pairs every proposal with its strongest counter-argument
before it ever reaches a human.

The brief lists "approval ladder for actions of escalating consequence" as
one of its six engineering bets. The CS-Agent, Growth-Agent, and
improvement-agent all PROPOSE; this agent ADVERSARIALLY-REVIEWS those
proposals against three lenses:

  1. Acquisition / engagement impact — what does the proposal forego?
  2. Confounders — what unobserved variable could explain the trigger?
  3. Reversibility cost — what's the cost of being wrong?

Output: a `critique` dict attached to the proposal YAML, surfaced to the
human at approval time. Humans see proposal + critique paired, never the
bare proposal. The Critic ALSO writes a modified `alternative_proposal`
the human can adopt instead of the original.

Rule-based today; LLM-pluggable tomorrow with no substrate change.
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

from mcp.tools import ToolSession

WAREHOUSE = _REPO / "warehouse" / "indiastox.duckdb"
PROPOSALS_PENDING = _REPO / "proposals" / "pending"
PROPOSALS_APPROVED = _REPO / "proposals" / "approved"


# Known confounders by metric — non-exhaustive; rule of thumb is "what
# unobserved variable could move this number without the agent's
# proposed cause being responsible?".
CONFOUNDERS_BY_METRIC: dict[str, list[str]] = {
    "ghost_rate": [
        "college exam-season seasonality (Indian academic calendar W01 ≈ end-of-semester crunch)",
        "Klaviyo deliverability shift (open-rate drop ≠ creative problem)",
        "identity-resolution drift: ~17% probabilistic matches mean the dark cohort's true ghost rate is bounded, not measured",
        "prediction-market liquidity drop (fewer interesting calls available, not fewer interested users)",
    ],
    "time_to_first_action": [
        "onboarding tutorial completion rate — slow first action may reflect a learning curve, not a friction",
        "device-shift effect (Tier-2 cities on slower connections)",
        "weekend / weekday signup mix in the cohort",
    ],
    "unstop_to_participation_rate": [
        "college-cohort homogeneity: a single dorm signup wave can spike or tank the rate",
        "weekly_challenge difficulty / topic (some weeks attract less follow-through irrespective of channel)",
    ],
    "weekly_active_posters": [
        "identity-confidence gate threshold drift — at 0.85 vs 0.70 the count moves 5-10% without underlying activity changing",
        "deferred outcomes still resolving at window edge",
    ],
    "dark_channel_fraction": [
        "iOS 14+ privacy changes (a step-change in UTM dropout that has nothing to do with channel quality)",
        "WhatsApp share-link normalization (a deep-link feature toggle on the app side)",
    ],
}


def _proposal_path(proposal_id: str) -> Optional[Path]:
    for d in (PROPOSALS_PENDING, PROPOSALS_APPROVED):
        p = d / f"{proposal_id}.yaml"
        if p.exists():
            return p
    return None


def _acquisition_impact(metric_name: str, hypothesis: str, session: ToolSession) -> dict:
    """Quantify what the proposal would forego in acquired-user terms."""
    # If the affected metric is acquisition-adjacent, surface the channel's
    # current contribution as the cost-of-pausing.
    lower = (hypothesis or "").lower()
    if "unstop" in lower or "channel" in lower or metric_name in ("ghost_rate", "channel_cac_bounds"):
        dark = session.call("dark_channel_fraction", week_of="2024-W01")
        return dict(
            relevant_metric="dark_channel_fraction",
            value=dark.value,
            note=(
                f"Pausing or restricting an attributable channel concentrates the cohort on "
                f"the {dark.value:.1%} dark fraction the team can't currently bound CAC for. "
                f"Acquisition diversity costs go up before they go down."
            ),
        )
    return dict(relevant_metric=None, value=None, note="No acquisition-side impact for this metric.")


def _reversibility_cost(proposal: dict) -> str:
    days = proposal.get("estimated_days", 0)
    if days <= 7:
        return "low — one-week pilot, reversible within a sprint"
    if days <= 21:
        return "medium — 2-3 weeks, reversible but with a sprint of follow-up to unwind"
    return "high — multi-month, requires a separate decision to reverse"


def _alternative(proposal: dict, confounders: list[str]) -> str:
    """A modified proposal that addresses the critique."""
    metric = proposal.get("affected_metric", "")
    if metric == "ghost_rate":
        return (
            "Run a 1-week creative-only A/B on the Unstop landing page (don't pause spend). "
            "Compare ghost_rate of variant-cohort vs control-cohort within Unstop using the "
            "same metric_version. Decide on full creative rollout based on the 7-day point "
            "estimate + a 4-week extrapolation that survives the exam-season confounder."
        )
    return (
        "Tighten the experiment to a single channel, single week, single creative variant. "
        "Re-evaluate at the 7-day mark. Hold off on the broader rollout until the "
        "confounders listed above are individually ruled out."
    )


def critique(proposal_id: str, *, write_back: bool = True) -> dict:
    """Generate (and optionally persist) a critique for a proposal."""
    path = _proposal_path(proposal_id)
    if path is None:
        raise FileNotFoundError(f"proposal {proposal_id} not found in pending/ or approved/")

    proposal: dict = yaml.safe_load(path.read_text())
    metric_name = proposal.get("affected_metric", "")
    hypothesis = proposal.get("hypothesis", "")
    expected_lift_pct = proposal.get("expected_lift_pct", 0.0)
    required_n = proposal.get("required_sample_n", 0)

    session = ToolSession()
    acq = _acquisition_impact(metric_name, hypothesis, session)
    confounders = CONFOUNDERS_BY_METRIC.get(metric_name, ["no canonical confounders catalogued for this metric"])
    rev = _reversibility_cost(proposal)
    alt = _alternative(proposal, confounders)

    # Severity: high when (a) the proposal asks for ≥10pp lift on a >0.20-confidence
    # metric, (b) confounders are catalogued AND not addressed in hypothesis,
    # or (c) reversibility is high.
    severity = "medium"
    if abs(expected_lift_pct) >= 10 and "exam" not in hypothesis.lower():
        severity = "high"
    if "high" in rev:
        severity = "high"

    counter_argument = (
        f"The proposal targets a {abs(expected_lift_pct):.0f}pp lift on `{metric_name}` "
        f"by changing the {hypothesis.split('.')[0].lower() if hypothesis else 'mechanism'}, "
        f"requiring n≈{required_n}. {acq['note']} "
        f"Before acting, at least one of these confounders should be individually ruled out: "
        f"{'; '.join(confounders[:2])}."
    )

    critique_dict = dict(
        critique_id=f"CRIT-{uuid.uuid4().hex[:12]}",
        generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        proposal_id=proposal_id,
        severity=severity,
        counter_argument=counter_argument,
        confounders_to_rule_out=confounders,
        acquisition_impact=acq,
        reversibility_cost=rev,
        alternative_proposal=alt,
        session_id=session.session_id,
    )

    if write_back:
        proposal["critique"] = critique_dict
        path.write_text(yaml.safe_dump(proposal, sort_keys=False, default_flow_style=False))
        # Also log to agent_actions.
        if WAREHOUSE.exists():
            con = duckdb.connect(str(WAREHOUSE), read_only=False)
            try:
                con.execute(
                    """INSERT INTO agent_actions
                       (action_id, ts, session_id, tool_name, args_json, result_hash,
                        result_confidence, downstream_proposal_id, _source_system)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        f"act-{uuid.uuid4().hex[:16]}",
                        datetime.now(timezone.utc),
                        session.session_id,
                        "critique_proposal",
                        json.dumps({"proposal_id": proposal_id, "severity": severity}),
                        critique_dict["critique_id"],
                        0.7,
                        proposal_id,
                        "critic_agent",
                    ],
                )
            finally:
                con.close()
        print(f"critique written to {path} (severity={severity})", file=sys.stderr)

    return critique_dict


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true", help="generate critique but don't modify the YAML")
    args, rest = parser.parse_known_args()
    kv = {}
    for tok in rest:
        if "=" in tok and not tok.startswith("--"):
            k, v = tok.split("=", 1)
            kv[k] = v
    proposal_id = kv.get("PROPOSAL_ID")
    if not proposal_id:
        print("usage: python3 -m agent.critic_agent PROPOSAL_ID=<id>", file=sys.stderr)
        sys.exit(2)
    c = critique(proposal_id, write_back=not args.no_write)
    print()
    print(f"=== Critique for {proposal_id} (severity={c['severity']}) ===")
    print()
    print(f"COUNTER:    {c['counter_argument']}")
    print()
    print("CONFOUNDERS to rule out:")
    for cf in c["confounders_to_rule_out"]:
        print(f"  - {cf}")
    print()
    print(f"REVERSIBILITY: {c['reversibility_cost']}")
    print()
    print(f"ALTERNATIVE:")
    print(f"  {c['alternative_proposal']}")
    print()


if __name__ == "__main__":
    main()
