"""Typed confidence — the canonical MetricResult + the versioning layer.

Every tool the agent calls returns a MetricResult. Bare floats are rejected
at the tool boundary via the `@tool_result` decorator — the contract is
enforced, not documented.

Every MetricResult also carries `metric_version` (e.g. "ghost_rate@1.0.0")
and `definition_hash` (sha256 of the function source at import time). These
are filled automatically by the `@versioned("1.0.0")` decorator so the
audit trail records WHICH definition produced each number — the bedrock
of `make reproduce`.
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

    # Versioning (filled by @versioned decorator — Layer H).
    metric_version: str = ""    # e.g. "ghost_rate@1.0.0"
    definition_hash: str = ""   # sha256 of function source at import time

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


# ---------------------------------------------------------------------------
# Versioning — Layer H
# ---------------------------------------------------------------------------

def _hash_source(func: Callable[..., Any]) -> str:
    try:
        src = inspect.getsource(func)
    except (OSError, TypeError):
        src = func.__name__
    return hashlib.sha256(src.encode()).hexdigest()


# Module-level registry — keyed by metric_name → (version, hash).
# Populated by @versioned and read by `core.version_registry`.
VERSION_REGISTRY: dict[str, tuple[str, str]] = {}


def versioned(version: str = "1.0.0") -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Stamps `metric_version` and `definition_hash` on every MetricResult.

    Usage:

        @versioned("1.0.0")
        def ghost_rate(...): ...

    Reads `inspect.getsource()` at import time so the hash is stable across
    runs. The decorator is idempotent with `@tool_result`: apply both
    (versioned outermost) and stamping happens after the type-check.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        h = _hash_source(func)
        name = func.__name__
        VERSION_REGISTRY[name] = (version, h)

        @functools.wraps(func)
        def _wrapped(*args, **kwargs):
            out = func(*args, **kwargs)
            if isinstance(out, MetricResult):
                # Stamp in place (BaseModel allows attribute assignment by
                # default in Pydantic 2 unless `frozen=True`).
                out.metric_version = f"{name}@{version}"
                out.definition_hash = h
            return out

        _wrapped.__version__ = version  # type: ignore[attr-defined]
        _wrapped.__definition_hash__ = h  # type: ignore[attr-defined]
        _wrapped.__metric_name__ = name  # type: ignore[attr-defined]
        return _wrapped

    return decorator


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
