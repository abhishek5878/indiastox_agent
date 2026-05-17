"""Tool layer — the interface the Growth Agent calls.

Every tool returns a `core.confidence.MetricResult`. The `@tool_result`
decorator on each metric function enforces this at runtime; bare-float
returns raise TypeError.

Each tool invocation is also logged to the `agent_actions` table in
DuckDB: action_id, ts, session_id, tool_name, args_json, result_hash,
result_confidence, downstream_proposal_id. This makes agent behavior
reproducible — given an action_id you can replay the exact tool call
and verify the result.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import duckdb

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from core.confidence import MetricResult, tool_result
from metrics.definitions import (
    weekly_active_posters as _weekly_active_posters,
    time_to_first_action as _time_to_first_action,
    unstop_to_participation_rate as _unstop_to_participation_rate,
    ghost_rate as _ghost_rate,
    dark_channel_fraction as _dark_channel_fraction,
    channel_cac_bounds as _channel_cac_bounds,
    brier_score as _brier_score,
    gyaani_graduation_rate as _gyaani_graduation_rate,
    predictions_per_user as _predictions_per_user,
    email_click_to_signup as _email_click_to_signup,
    metric_gameability_index as _metric_gameability_index,
)
from metrics.skill import get_skill_distribution as _get_skill_distribution

WAREHOUSE_DB = _REPO / "warehouse" / "indiastox.duckdb"


# ---------------------------------------------------------------------------
# @tool_result-wrapped exports
# ---------------------------------------------------------------------------

@tool_result
def weekly_active_posters(week_of: str, min_identity_confidence: float = 0.70) -> MetricResult:
    return _weekly_active_posters(week_of, min_identity_confidence)


@tool_result
def time_to_first_action(week_of: str, acquisition_source: str = "all") -> MetricResult:
    return _time_to_first_action(week_of, acquisition_source)


@tool_result
def unstop_to_participation_rate(week_of: str) -> MetricResult:
    return _unstop_to_participation_rate(week_of)


@tool_result
def ghost_rate(week_of: str, acquisition_source: str = "all") -> MetricResult:
    return _ghost_rate(week_of, acquisition_source)


@tool_result
def dark_channel_fraction(week_of: str) -> MetricResult:
    return _dark_channel_fraction(week_of)


@tool_result
def channel_cac_bounds(week_of: str, **kwargs) -> MetricResult:
    return _channel_cac_bounds(week_of, **kwargs)


@tool_result
def brier_score(week_of: str) -> MetricResult:
    return _brier_score(week_of)


@tool_result
def gyaani_graduation_rate(week_of: str, acquisition_source: str = "all") -> MetricResult:
    return _gyaani_graduation_rate(week_of, acquisition_source)


@tool_result
def predictions_per_user(week_of: str, acquisition_source: str = "all", threshold: int = 5) -> MetricResult:
    return _predictions_per_user(week_of, acquisition_source, threshold)


@tool_result
def email_click_to_signup() -> MetricResult:
    return _email_click_to_signup()


@tool_result
def get_skill_distribution(channel: Optional[str] = None, cohort: Optional[str] = None) -> MetricResult:
    return _get_skill_distribution(channel, cohort)


@tool_result
def metric_gameability_index() -> MetricResult:
    return _metric_gameability_index()


TOOLS: dict[str, Callable[..., MetricResult]] = {
    "weekly_active_posters": weekly_active_posters,
    "time_to_first_action": time_to_first_action,
    "unstop_to_participation_rate": unstop_to_participation_rate,
    "ghost_rate": ghost_rate,
    "dark_channel_fraction": dark_channel_fraction,
    "channel_cac_bounds": channel_cac_bounds,
    "brier_score": brier_score,
    "gyaani_graduation_rate": gyaani_graduation_rate,
    "predictions_per_user": predictions_per_user,
    "email_click_to_signup": email_click_to_signup,
    "get_skill_distribution": get_skill_distribution,
    "metric_gameability_index": metric_gameability_index,
}


# ---------------------------------------------------------------------------
# Audit-logging wrapper
# ---------------------------------------------------------------------------

class ToolSession:
    """Wraps tool calls in an audit-logging context.

    Each invocation appends a row to `agent_actions`. The agent gets back
    the MetricResult directly; the side-effect is the audit row.
    """

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or f"sess-{uuid.uuid4().hex[:12]}"

    def call(self, tool_name: str, downstream_proposal_id: Optional[str] = None, **kwargs) -> MetricResult:
        if tool_name not in TOOLS:
            raise KeyError(f"unknown tool: {tool_name}. known: {sorted(TOOLS)}")
        result: MetricResult = TOOLS[tool_name](**kwargs)
        self._log_action(tool_name, kwargs, result, downstream_proposal_id)
        return result

    def _log_action(self, tool_name: str, args: dict, result: MetricResult, downstream_proposal_id: Optional[str]) -> None:
        if not WAREHOUSE_DB.exists():
            return  # don't fail tool calls when warehouse is missing — just skip audit
        con = duckdb.connect(str(WAREHOUSE_DB), read_only=False)
        try:
            con.execute(
                """INSERT INTO agent_actions
                   (action_id, ts, session_id, tool_name, args_json, result_hash,
                    result_confidence, downstream_proposal_id, _source_system)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    f"act-{uuid.uuid4().hex[:16]}",
                    datetime.now(timezone.utc),
                    self.session_id,
                    tool_name,
                    json.dumps(args, default=str),
                    result.result_hash(),
                    result.confidence,
                    downstream_proposal_id,
                    "mcp.tools",
                ],
            )
        finally:
            con.close()
