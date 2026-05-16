"""Typed confidence — the canonical MetricResult.

Every tool the agent calls returns one of these. Bare floats are rejected
at the tool boundary via the `@tool_result` decorator below — the contract
is enforced, not documented.

The shape carries:
- value          : the number itself
- confidence     : a 0..1 summary the agent treats as load-bearing
- sample_n       : underlying sample size — small N → wide CI even if confidence is high
- provenance     : list of one-line strings naming the sources / breakdowns
                   that fed this number (e.g. "deterministic_match:1567")
- window_open    : True if a deferred join hasn't fully resolved yet
- interpretation : a single human-readable caveat the agent surfaces verbatim

Plus audit fields preserved from the earlier shape:
- metric_name, definition_version, computation_sql, as_of, breakdowns,
  confidence_interval (the numeric tuple — agent uses `confidence` summary,
  audits use the interval).
"""
from __future__ import annotations

import functools
import hashlib
import inspect
import json
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MetricResult(BaseModel):
    """The single return type for every metric / tool the agent sees."""

    model_config = ConfigDict(extra="forbid")

    metric_name: str
    value: float
    confidence: float = Field(ge=0.0, le=1.0)
    sample_n: int = Field(ge=0)
    provenance: list[str]
    window_open: bool
    interpretation: str

    # Audit-trail fields (preserved from the v1 shape).
    definition_version: str = "1.0.0"
    confidence_interval: Optional[tuple[float, float]] = None
    computation_sql: str = ""
    as_of: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    breakdowns: Optional[dict] = None

    @field_validator("interpretation")
    @classmethod
    def _interpretation_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("interpretation must be non-empty — the agent surfaces this verbatim")
        if len(v) > 500:
            raise ValueError("interpretation must be <= 500 chars (one sentence, agent-surfaced)")
        return v.strip()

    def to_audit_row(self) -> dict:
        """Flat dict for inserting into metric_results / agent_actions tables."""
        return dict(
            metric_name=self.metric_name,
            value=self.value,
            confidence=self.confidence,
            sample_n=self.sample_n,
            provenance=self.provenance,
            window_open=self.window_open,
            interpretation=self.interpretation,
            definition_version=self.definition_version,
            as_of=self.as_of,
            confidence_interval_low=self.confidence_interval[0] if self.confidence_interval else None,
            confidence_interval_high=self.confidence_interval[1] if self.confidence_interval else None,
            computation_sql=self.computation_sql,
            breakdowns_json=json.dumps(self.breakdowns) if self.breakdowns else None,
        )

    def result_hash(self) -> str:
        """sha256 of (metric_name, value, confidence, sample_n, provenance) — the
        agent-visible fields. Used in the agent_actions audit row.
        """
        payload = json.dumps(
            dict(
                metric_name=self.metric_name,
                value=self.value,
                confidence=self.confidence,
                sample_n=self.sample_n,
                provenance=sorted(self.provenance),
                window_open=self.window_open,
            ),
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


def tool_result(func: Callable[..., Any]) -> Callable[..., MetricResult]:
    """Decorator: rejects bare-float returns. Every tool must return a MetricResult.

    Catches the most common drift: a metric function evolving and forgetting
    to wrap its output. The validator runs at call time, so the contract is
    enforced by the runtime, not by reviewer discipline.
    """

    @functools.wraps(func)
    def _wrapped(*args, **kwargs):
        out = func(*args, **kwargs)
        if isinstance(out, MetricResult):
            return out
        raise TypeError(
            f"Tool '{func.__name__}' returned {type(out).__name__}, "
            f"expected MetricResult. Bare floats from tools are forbidden — "
            f"wrap the value in MetricResult(value=..., confidence=..., "
            f"sample_n=..., provenance=[...], window_open=..., interpretation=...)."
        )

    _wrapped.__is_tool__ = True  # type: ignore[attr-defined]
    return _wrapped


# Helper: combine identity-confidence stats from dim_user into a metric-level
# confidence summary. Used by every metric function that touches user-level
# aggregations.
def identity_confidence_summary(con) -> tuple[float, list[str]]:
    """Returns (confidence_estimate, provenance_strings) for the user pool.

    `confidence_estimate` = deterministic_share − 0.5 × probabilistic_share.

    The deterministic share is the trustable floor. The probabilistic share
    is recorded but down-weighted: a name-and-device fuzz match identifies
    a real person but may assign them the wrong channel or wrong cohort
    edge in any user-level aggregation. The 0.5 weight reflects this
    reduced (not zero) trust — the match is more likely right than wrong,
    but it is not as load-bearing as a deterministic email-equality match.
    """
    rows = con.execute(
        """
        SELECT
          SUM(CASE WHEN identity_confidence >= 0.85 THEN 1 ELSE 0 END) AS deterministic_match,
          SUM(CASE WHEN identity_confidence BETWEEN 0.60 AND 0.8499 THEN 1 ELSE 0 END) AS probabilistic_match,
          SUM(CASE WHEN identity_confidence < 0.60 THEN 1 ELSE 0 END) AS low_confidence,
          COUNT(*) AS total
        FROM dim_user
        """
    ).fetchone()
    det, prob, low, total = rows
    total = total or 1
    base = det / total
    probabilistic_penalty = 0.5 * (prob / total)
    confidence = max(0.0, base - probabilistic_penalty)
    provenance = [
        f"deterministic_match:{int(det)}",
        f"probabilistic_match:{int(prob)}",
        f"low_confidence:{int(low)}",
    ]
    return confidence, provenance
