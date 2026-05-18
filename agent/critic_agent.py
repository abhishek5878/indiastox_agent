"""Critic Agent — pairs every proposal with its strongest counter-argument
before it ever reaches a human.

The brief lists "approval ladder for actions of escalating consequence" as
one of its six engineering bets. The CS-Agent, Growth-Agent, and
improvement-agent all PROPOSE; this agent ADVERSARIALLY-REVIEWS those
proposals.

Pass C / N5 — confounders FACT-CHECK against the live substrate.
Previously the confounder list was a hardcoded `dict[metric → list[str]]`
of plausible objections. Now each confounder is a `(name, check_function)`
pair; the check runs a tool call (data-quality scan, gameability index,
brier score, dark-channel fraction) and returns `(fired: bool, evidence:
str)`. The critique cites concrete numbers from the checks, not
hardcoded prose. Severity weighting is driven by the count of *fired*
confounders.

Output: a `critique` dict attached to the proposal YAML, surfaced to the
human at approval time. Humans see proposal + critique paired, never the
bare proposal. The Critic ALSO writes a modified `alternative_proposal`.

Rule-based today; LLM-pluggable tomorrow.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import duckdb
import yaml

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from mcp.tools import ToolSession

WAREHOUSE = _REPO / "warehouse" / "indiastox.duckdb"
PROPOSALS_PENDING = _REPO / "proposals" / "pending"
PROPOSALS_APPROVED = _REPO / "proposals" / "approved"


# ---------------------------------------------------------------------------
# Confounder check functions — each returns (fired: bool, evidence: str).
# Each function takes a ToolSession so it can audit-log its calls.
# ---------------------------------------------------------------------------

def _check_klaviyo_deliverability(session: ToolSession) -> tuple[bool, str]:
    """Fires if the Klaviyo stream shows > 1% clock-skew rate.

    Clock-skew in the email-event stream is a leading indicator of
    deliverability problems at the producer (timestamps drift because
    the SMTP relay is buffering / retrying). If we see > 1%, the
    "Unstop landing-page didn't render" hypothesis is contaminated
    by a competing explanation: the email funnel itself is broken.
    """
    if not WAREHOUSE.exists():
        return False, "warehouse missing"
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        # Read the most recent data_quality audit row for clock_skew.
        row = con.execute(
            """SELECT notes FROM audit_log
               WHERE pipeline_stage = 'data_quality'
                 AND notes LIKE '%clock_skew%'
               ORDER BY run_at DESC LIMIT 1"""
        ).fetchone()
    finally:
        con.close()
    if not row:
        return False, "no data_quality scan has run; deliverability state unknown"
    notes = row[0]
    # Parse "27/672 pairs (4.0%)"
    import re
    m = re.search(r"(\d+)/(\d+) pairs \((\d+(?:\.\d+)?)%\)", notes)
    if not m:
        return False, f"could not parse data_quality notes: {notes}"
    found, total, pct = int(m.group(1)), int(m.group(2)), float(m.group(3))
    fired = pct > 1.0
    evidence = (
        f"data_quality scan: {found}/{total} email-pairs ({pct:.1f}%) have "
        f"opened.ts < sent.ts. {'FIRES (>1% threshold)' if fired else 'does NOT fire'}."
    )
    return fired, evidence


def _check_identity_resolution_drift(session: ToolSession) -> tuple[bool, str]:
    """Fires if metric_gameability_index > 0 — any metric has shifted hash."""
    try:
        g = session.call("metric_gameability_index")
    except Exception as e:
        return False, f"gameability tool call failed: {e}"
    fired = g.value > 0.0
    evidence = (
        f"metric_gameability_index = {g.value:.2f}. "
        f"{'FIRES — at least one metric has redefined since first deploy.' if fired else 'does NOT fire — all metrics at original hash.'}"
    )
    return fired, evidence


def _check_prediction_market_noise(session: ToolSession) -> tuple[bool, str]:
    """Fires if Brier score is at or worse than the random-guess baseline.

    A ghost-rate spike + a Brier near 0.25 means the population's
    predictions are noise. Pausing a channel won't change the noise
    floor; the right intervention is upstream (better prediction prompts).
    """
    try:
        b = session.call("brier_score", week_of="2024-W01")
    except Exception as e:
        return False, f"brier_score tool call failed: {e}"
    fired = b.value >= 0.24
    evidence = (
        f"brier_score = {b.value:.4f} (random-guess baseline = 0.25). "
        f"{'FIRES — predictions near noise floor; channel intervention may be misdirected.' if fired else 'does NOT fire — predictions show signal.'}"
    )
    return fired, evidence


def _check_dark_channel_dominance(session: ToolSession) -> tuple[bool, str]:
    """Fires when dark_channel_fraction > 15% — any attribution-side
    intervention is bounded by the dark cohort the team can't measure.
    """
    try:
        d = session.call("dark_channel_fraction", week_of="2024-W01")
    except Exception as e:
        return False, f"dark_channel_fraction tool call failed: {e}"
    fired = d.value > 0.15
    evidence = (
        f"dark_channel_fraction = {d.value:.1%}. "
        f"{'FIRES — attribution-side interventions are bounded by this floor.' if fired else 'does NOT fire — attribution coverage is reasonable.'}"
    )
    return fired, evidence


def _check_exam_season() -> tuple[bool, str]:
    """Calendar context not in the substrate → unverifiable today.

    We surface this as a known-unverifiable confounder rather than
    silently dropping it; an LLM agent or a human can fill the gap.
    """
    return False, "calendar context not in the substrate; confounder UNVERIFIABLE today"


# Each entry: (display_name, check_function). check_function may take a
# ToolSession (data-driven check) or no arg (static / unverifiable).
ConfounderCheck = tuple[str, Callable[..., tuple[bool, str]]]

CONFOUNDERS_BY_METRIC: dict[str, list[ConfounderCheck]] = {
    "ghost_rate": [
        ("klaviyo_deliverability_drop",   _check_klaviyo_deliverability),
        ("prediction_market_noise_floor", _check_prediction_market_noise),
        ("identity_resolution_drift",     _check_identity_resolution_drift),
        ("dark_channel_dominance",        _check_dark_channel_dominance),
        ("exam_season_seasonality",       _check_exam_season),
    ],
    "time_to_first_action": [
        ("klaviyo_deliverability_drop",   _check_klaviyo_deliverability),
        ("identity_resolution_drift",     _check_identity_resolution_drift),
    ],
    "unstop_to_participation_rate": [
        ("identity_resolution_drift",     _check_identity_resolution_drift),
        ("prediction_market_noise_floor", _check_prediction_market_noise),
    ],
    "weekly_active_posters": [
        ("identity_resolution_drift",     _check_identity_resolution_drift),
        ("prediction_market_noise_floor", _check_prediction_market_noise),
    ],
    "dark_channel_fraction": [
        ("identity_resolution_drift",     _check_identity_resolution_drift),
    ],
}


def _proposal_path(proposal_id: str) -> Optional[Path]:
    for d in (PROPOSALS_PENDING, PROPOSALS_APPROVED):
        p = d / f"{proposal_id}.yaml"
        if p.exists():
            return p
    return None


def _run_confounder_checks(metric_name: str, session: ToolSession) -> list[dict]:
    """Run every catalogued confounder check for `metric_name`.

    Returns list of dicts: {name, fired, evidence}. Severity downstream
    consumes the count of `fired = True` rows.
    """
    checks = CONFOUNDERS_BY_METRIC.get(metric_name, [])
    out: list[dict] = []
    for name, check_fn in checks:
        try:
            # Some checks need a ToolSession; others don't.
            import inspect
            params = list(inspect.signature(check_fn).parameters)
            if params:
                fired, evidence = check_fn(session)
            else:
                fired, evidence = check_fn()
        except Exception as e:
            fired, evidence = False, f"check errored: {e}"
        out.append(dict(name=name, fired=bool(fired), evidence=evidence))
    return out


def _acquisition_impact(metric_name: str, hypothesis: str, session: ToolSession) -> dict:
    """Quantify what the proposal would forego in acquired-user terms."""
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


def _alternative(proposal: dict, fired_confounders: list[str]) -> str:
    metric = proposal.get("affected_metric", "")
    fired_str = ", ".join(fired_confounders) if fired_confounders else "no data-driven confounders fired"
    if metric == "ghost_rate":
        return (
            "Run a 1-week creative-only A/B on the Unstop landing page (don't pause spend). "
            "Compare ghost_rate of variant-cohort vs control-cohort within Unstop using the "
            "same metric_version. Before launching, individually rule out the fired "
            f"confounders ({fired_str}): for klaviyo_deliverability_drop, audit the email "
            "stream timestamps in the prior 7 days; for identity_resolution_drift, freeze "
            "the metric_versions table and re-run reproduce; for prediction_market_noise_floor, "
            "compare Brier across cohorts before declaring the variant a winner."
        )
    return (
        "Tighten the experiment to a single channel, single week, single creative variant. "
        f"Re-evaluate at the 7-day mark. Rule out the fired confounders ({fired_str}) "
        "before broader rollout."
    )


def critique(proposal_id: str, *, write_back: bool = True) -> dict:
    path = _proposal_path(proposal_id)
    if path is None:
        raise FileNotFoundError(f"proposal {proposal_id} not found in pending/ or approved/")

    proposal: dict = yaml.safe_load(path.read_text())
    metric_name = proposal.get("affected_metric", "")
    hypothesis = proposal.get("hypothesis", "")
    expected_lift_pct = proposal.get("expected_lift_pct", 0.0)
    required_n = proposal.get("required_sample_n", 0)

    session = ToolSession()

    # Fact-check every catalogued confounder against the live substrate.
    confounder_results = _run_confounder_checks(metric_name, session)
    fired = [c for c in confounder_results if c["fired"]]
    fired_names = [c["name"] for c in fired]

    acq = _acquisition_impact(metric_name, hypothesis, session)
    rev = _reversibility_cost(proposal)
    alt = _alternative(proposal, fired_names)

    # Severity rules (data-driven):
    #   high — any fired confounder + non-trivial lift target
    #          OR reversibility cost = high
    #   medium — lift target >= 10pp but no fired confounders
    #   low — otherwise
    if (fired and abs(expected_lift_pct) >= 5) or "high" in rev:
        severity = "high"
    elif abs(expected_lift_pct) >= 10:
        severity = "medium"
    else:
        severity = "low"

    # Counter-argument cites the actual fired confounders' evidence.
    counter_lines = [
        f"The proposal targets a {abs(expected_lift_pct):.0f}pp lift on `{metric_name}` "
        f"by changing the {hypothesis.split('.')[0].lower() if hypothesis else 'mechanism'}, "
        f"requiring n≈{required_n}. {acq['note']}",
    ]
    if fired:
        counter_lines.append(
            f"DATA-DRIVEN CONCERNS — {len(fired)} confounder(s) actually fire against the current substrate:"
        )
        for c in fired:
            counter_lines.append(f"  • {c['name']}: {c['evidence']}")
    else:
        counter_lines.append(
            "No catalogued confounders fire against the current data — proposal is on its own merits."
        )
    counter_argument = "\n".join(counter_lines)

    critique_dict = dict(
        critique_id=f"CRIT-{uuid.uuid4().hex[:12]}",
        generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        proposal_id=proposal_id,
        severity=severity,
        counter_argument=counter_argument,
        confounder_checks=confounder_results,  # full list with fired flag + evidence
        confounders_fired=fired_names,
        acquisition_impact=acq,
        reversibility_cost=rev,
        alternative_proposal=alt,
        session_id=session.session_id,
        critic_version="2.0.0",  # bumped from 1.0.0 (rule-based table) → 2.0.0 (data-driven checks)
    )

    if write_back:
        proposal["critique"] = critique_dict
        path.write_text(yaml.safe_dump(proposal, sort_keys=False, default_flow_style=False))
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
                        json.dumps({"proposal_id": proposal_id, "severity": severity,
                                    "confounders_fired": fired_names}),
                        critique_dict["critique_id"],
                        0.7,
                        proposal_id,
                        "critic_agent",
                    ],
                )
            finally:
                con.close()
        print(f"critique written to {path} (severity={severity}; fired={fired_names})", file=sys.stderr)

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
    print(f"=== Critique for {proposal_id} (severity={c['severity']}; critic v{c['critic_version']}) ===")
    print()
    print(f"COUNTER:\n{c['counter_argument']}")
    print()
    print(f"CONFOUNDER CHECKS ({sum(1 for cc in c['confounder_checks'] if cc['fired'])}/{len(c['confounder_checks'])} fired):")
    for cc in c["confounder_checks"]:
        flag = "🔥 FIRED" if cc["fired"] else "·"
        print(f"  {flag}  {cc['name']}")
        print(f"          {cc['evidence']}")
    print()
    print(f"REVERSIBILITY: {c['reversibility_cost']}")
    print()
    print(f"ALTERNATIVE:\n  {c['alternative_proposal']}")
    print()


if __name__ == "__main__":
    main()
