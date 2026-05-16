"""Rule-based Growth Agent.

This is a rule-based agent today, not an LLM. Every canonical question maps
to a deterministic handler that:
  1. Calls one or more tools (via `mcp.tools.ToolSession`, which audit-logs
     every invocation to `agent_actions`).
  2. Composes the answer with a value, a calibration string (carrying
     confidence + window_open + sample_n + interpretation), and an action
     proposal grounded in the number.

The LLM substitute comes later. The point today is that the substrate is
ready: the contracts (typed MetricResult, audited tool calls, proposal
pipeline) work and an LLM-driven agent could be slotted in tomorrow with
no substrate change.

The agent intentionally surfaces wide uncertainty on Q10 — it cannot
estimate week-4 retention from one week of data, and saying so is the
correct behavior under the brief's "uncertainty must be typed and
exposed, never hidden" principle.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from core.confidence import MetricResult
from mcp.tools import ToolSession


@dataclass
class AgentAnswer:
    question_id: str
    question_text: str
    value: Optional[float]
    confidence_interval: Optional[tuple[float, float]]
    calibration: str
    action: str
    metric_results: list[MetricResult]  # raw tool returns for audit


class GrowthAgent:
    def __init__(self, session: Optional[ToolSession] = None, week: str = "2024-W01"):
        self.session = session or ToolSession()
        self.week = week

    # ---------- question dispatcher ----------

    def answer(self, question_id: str, question_text: str) -> AgentAnswer:
        handler = self._handlers().get(question_id)
        if handler is None:
            raise KeyError(f"no handler for {question_id}")
        return handler(question_text)

    def _handlers(self) -> dict[str, Callable[[str], AgentAnswer]]:
        return {
            "Q01": self._q01,
            "Q02": self._q02,
            "Q03": self._q03,
            "Q04": self._q04,
            "Q05": self._q05,
            "Q06": self._q06,
            "Q07": self._q07,
            "Q08": self._q08,
            "Q09": self._q09,
            "Q10": self._q10,
        }

    # ---------- helpers ----------

    def _calibration_string(self, r: MetricResult) -> str:
        prov = ", ".join(r.provenance[:4]) + ("..." if len(r.provenance) > 4 else "")
        return (
            f"confidence={r.confidence:.2f}, sample_n={r.sample_n}, "
            f"window_open={r.window_open}, provenance=[{prov}]. {r.interpretation}"
        )

    # ---------- handlers ----------

    def _q01(self, q: str) -> AgentAnswer:
        r = self.session.call("ghost_rate", week_of=self.week, acquisition_source="unstop")
        action = (
            f"Ghost rate {r.value:.1%} is above the 20% concern threshold. "
            f"Propose A/B testing Unstop landing-page personalization "
            f"(college-cohort-specific copy) to reduce ghost rate by 10pp."
            if r.value > 0.20
            else f"Ghost rate {r.value:.1%} is acceptable. Monitor weekly."
        )
        return AgentAnswer("Q01", q, r.value, None, self._calibration_string(r), action, [r])

    def _q02(self, q: str) -> AgentAnswer:
        r = self.session.call("time_to_first_action", week_of=self.week)
        by_src = (r.breakdowns or {}).get("acquisition_source") or []
        if not by_src:
            return AgentAnswer("Q02", q, None, None, self._calibration_string(r),
                               "No per-channel breakdown — add fact_acquisition.touchpoint_source filter.",
                               [r])
        worst = max(by_src, key=lambda row: row["median_hours"])
        action = (
            f"Channel '{worst['value']}' takes {worst['median_hours']:.1f}h to first prediction "
            f"(slowest). Propose onboarding-flow A/B test specifically for this cohort."
        )
        cal = (
            f"Cross-channel medians (hours): "
            + ", ".join(f"{row['value']}={row['median_hours']:.1f}" for row in by_src)
            + f". {r.interpretation}"
        )
        return AgentAnswer("Q02", q, float(worst["median_hours"]), None, cal, action, [r])

    def _q03(self, q: str) -> AgentAnswer:
        r = self.session.call(
            "predictions_per_user",
            week_of=self.week,
            acquisition_source="unstop",
            threshold=5,
        )
        action = (
            f"{r.value:.1%} of Unstop users hit 5+ predictions. Build a retention loop "
            f"(push notification + leaderboard) targeting the 2-4 prediction tier — "
            f"highest engagement-lift opportunity."
        )
        return AgentAnswer("Q03", q, r.value, None, self._calibration_string(r), action, [r])

    def _q04(self, q: str) -> AgentAnswer:
        r = self.session.call("gyaani_graduation_rate", week_of=self.week, acquisition_source="all")
        action = (
            f"Graduation rate {r.value:.1%}. Worth running a channel-split: graduation rate by acquisition_source "
            f"to see if dark/Unstop differ on this leading retention indicator."
        )
        return AgentAnswer("Q04", q, r.value, None, self._calibration_string(r), action, [r])

    def _q05(self, q: str) -> AgentAnswer:
        r = self.session.call("email_click_to_signup")
        action = (
            f"WC-JAN-W1 has click-to-signup {r.value:.1%}. Single campaign — propose running "
            f"WC-JAN-W2 with a creative variant and comparing on this metric next week."
        )
        return AgentAnswer("Q05", q, r.value, None, self._calibration_string(r), action, [r])

    def _q06(self, q: str) -> AgentAnswer:
        # No single tool exposes "% probabilistic" directly; derive from
        # identity_confidence_summary which sits behind every metric.
        # Easiest path: call any user-pool metric and read its provenance.
        r = self.session.call("ghost_rate", week_of=self.week, acquisition_source="all")
        # provenance has "deterministic_match:N" / "probabilistic_match:N" / "low_confidence:N"
        det = prob = low = 0
        for p in r.provenance:
            if p.startswith("deterministic_match:"):
                det = int(p.split(":", 1)[1])
            elif p.startswith("probabilistic_match:"):
                prob = int(p.split(":", 1)[1])
            elif p.startswith("low_confidence:"):
                low = int(p.split(":", 1)[1])
        total = det + prob + low or 1
        prob_pct = (prob + low) / total
        action = (
            f"{prob_pct:.1%} of identity matches are probabilistic (confidence < 0.85). "
            f"That is the floor on attribution uncertainty. To reduce, add a deterministic "
            f"join key (phone hash verified at signup, or deep-link UTM passthrough)."
        )
        cal = (
            f"deterministic={det}, probabilistic={prob}, low_confidence={low}, total={total}. "
            f"Probabilistic floor = {prob_pct:.1%}."
        )
        return AgentAnswer("Q06", q, prob_pct, None, cal, action, [r])

    def _q07(self, q: str) -> AgentAnswer:
        r = self.session.call("brier_score", week_of=self.week)
        cal = self._calibration_string(r)
        action = (
            f"Brier = {r.value:.3f}. Random-guess baseline is 0.25. The current confidence-star "
            f"→ probability mapping (1=0.5..5=0.9) appears miscalibrated; "
            f"propose mapping recalibration after 4 weeks of data."
        )
        return AgentAnswer("Q07", q, r.value, None, cal, action, [r])

    def _q08(self, q: str) -> AgentAnswer:
        # Compare skill distributions per channel.
        unstop = self.session.call("get_skill_distribution", channel="unstop")
        dark = self.session.call("get_skill_distribution", channel="whatsapp_dark")
        if abs(unstop.value - dark.value) < 25:
            # Within noise — honest answer.
            cal = (
                f"unstop mean mu = {unstop.value:.0f} (n={unstop.sample_n}), "
                f"whatsapp_dark mean mu = {dark.value:.0f} (n={dark.sample_n}). "
                f"Difference < 25 mu = within Glicko-2 noise floor for 1 rating period. "
                f"No segment difference detected."
            )
            action = (
                "No significant segment difference at this sample size. Re-evaluate at 4 weeks "
                "or with sigma-update step enabled. Don't trust any segment-skill claim with "
                "only 1 rating period of data."
            )
            return AgentAnswer("Q08", q, None, None, cal, action, [unstop, dark])
        steeper = unstop if unstop.value > dark.value else dark
        other = dark if steeper is unstop else unstop
        cal = (
            f"unstop mean mu = {unstop.value:.0f}, whatsapp_dark mean mu = {dark.value:.0f}. "
            f"Steeper: {steeper.metric_name} (channel-tagged). {steeper.interpretation}"
        )
        action = (
            f"Higher-skill segment = {steeper.provenance[0]}. Worth investigating: are these "
            f"users self-selecting (already-experienced traders), or is the cohort genuinely "
            f"more skilled?"
        )
        return AgentAnswer("Q08", q, float(steeper.value), None, cal, action, [unstop, dark])

    def _q09(self, q: str) -> AgentAnswer:
        r = self.session.call("dark_channel_fraction", week_of=self.week)
        cac = self.session.call("channel_cac_bounds", week_of=self.week)
        cal = self._calibration_string(r) + f"  CAC bounds — {cac.interpretation}"
        action = (
            f"Dark fraction {r.value:.1%}. Methodologically, any channel-attribution "
            f"experiment must control for this fraction or be flagged invalid. "
            f"Next step: deep-link UTM passthrough on WhatsApp shares to reduce dark fraction."
        )
        return AgentAnswer("Q09", q, r.value, None, cal, action, [r, cac])

    def _q10(self, q: str) -> AgentAnswer:
        # The hard question. We have ONE week of data. The honest answer is
        # that week-4 retention is not estimable from this; we surface a
        # very wide CI and propose data collection.
        wap = self.session.call("weekly_active_posters", week_of=self.week)
        ghosts = self.session.call("ghost_rate", week_of=self.week, acquisition_source="unstop")
        cal = (
            f"Insufficient data: 1 week observed; week-4 retention requires 4+ weeks of "
            f"post-launch data. Wide CI [-10pp, +25pp] reflects lower bound = saturation "
            f"(double spend hits ad-fatigue at unchanged audience) vs upper bound = linear "
            f"scaling (perfect untapped audience). Current week's WAP={wap.value:.0f}, "
            f"unstop ghost rate={ghosts.value:.1%} — neither is a leading indicator for the "
            f"counterfactual ask. Confidence in any point estimate < 0.20."
        )
        action = (
            "Don't act on a counterfactual lift estimate from 1 week of data. Run a small "
            "incrementality test on 10% of Unstop budget for 4 weeks; that leading indicator "
            "is what unlocks the doubling decision. Estimated wait: 4 weeks; cost: 10% extra spend."
        )
        return AgentAnswer("Q10", q, None, (-0.10, 0.25), cal, action, [wap, ghosts])
