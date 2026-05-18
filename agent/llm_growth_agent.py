"""LLM-driven Growth Agent — Anthropic SDK, claude-sonnet-4-6.

Proof point for the brief's "substrate is LLM-pluggable" claim. Same
canonical questions as `agent.growth_agent.GrowthAgent`; same
`mcp.tools.ToolSession.call()` audit-log surface; same MetricResult
contract. The router is the LLM instead of a hand-coded handler dict.

Three questions wired so far (the eval's most-distinctive shapes):
  Q01 — pull-a-number (ghost_rate, surface confidence + interpretation)
  Q09 — answer-with-bounds (dark fraction + channel CAC bounds)
  Q10 — refuse-when-unknowable (counterfactual lift, propose data
        collection instead of a number)

Usage:
  export ANTHROPIC_API_KEY=sk-ant-...
  python3 -m agent.llm_growth_agent Q01 Q09 Q10
  make llm-demo                          # runs rule-based + LLM side-by-side

If ANTHROPIC_API_KEY is missing, the script falls back to a structural
dry-run (prints what it WOULD send) so reviewers cloning the repo
without keys can still see the integration shape.

Prompt caching: the system prompt + tool descriptions are marked
`cache_control: ephemeral` so repeated calls within the 5-minute TTL
hit the cache. Per-question user prompts are not cached.
"""
from __future__ import annotations

import inspect
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / ".env")
except ImportError:
    pass

from core.confidence import MetricResult
from mcp.tools import TOOLS, ToolSession

MODEL = "claude-sonnet-4-6"
MAX_TOOL_TURNS = 8


# ---------------------------------------------------------------------------
# Tool-schema bridge — render each Python tool as an Anthropic tool spec.
# ---------------------------------------------------------------------------

def _python_param_to_json_schema(name: str, hint, default) -> dict:
    """Best-effort mapping: str → string, int → integer, float → number, bool → boolean."""
    if hint is float:
        schema = {"type": "number"}
    elif hint is int:
        schema = {"type": "integer"}
    elif hint is bool:
        schema = {"type": "boolean"}
    else:
        schema = {"type": "string"}
    if default is not inspect.Parameter.empty and default is not None:
        schema["default"] = default
    return schema


def build_tool_specs() -> list[dict]:
    """One Anthropic tool spec per registered metric. Description comes
    from the underlying function's first docstring line."""
    specs: list[dict] = []
    for name, fn in TOOLS.items():
        underlying = fn
        # Unwrap one or two layers (tool_result → versioned → real fn).
        while hasattr(underlying, "__wrapped__"):
            underlying = underlying.__wrapped__
        doc = (underlying.__doc__ or name).strip().split("\n")[0]

        try:
            sig = inspect.signature(underlying)
        except (TypeError, ValueError):
            sig = inspect.Signature()

        props: dict[str, dict] = {}
        required: list[str] = []
        for pname, p in sig.parameters.items():
            props[pname] = _python_param_to_json_schema(pname, p.annotation, p.default)
            if p.default is inspect.Parameter.empty:
                required.append(pname)

        specs.append(dict(
            name=name,
            description=doc[:1024],
            input_schema=dict(type="object", properties=props, required=required),
        ))
    return specs


# ---------------------------------------------------------------------------
# LLM agent
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are the IndiaStox Growth Agent. You have access to a metric tool
layer that returns typed MetricResult objects with a `value`,
`confidence` (0-1), `sample_n`, `provenance` (list of strings),
`window_open` (bool), `interpretation` (1 sentence), and a 3-step
`trace`. ALWAYS read the trace + interpretation; surface confidence
and window_open in your final answer.

When a question is genuinely unknowable from one week of data
(counterfactual lifts, future projections, swap-in estimators), DO NOT
fabricate a number. Refuse to estimate, surface why, and propose a
concrete data-collection plan (parallel shadow run, incrementality
test, 4-week wait, etc.).

When a question has a known answer in the substrate, call the relevant
tool(s) and report:
  value (with units), confidence, sample_n, the one-sentence
  interpretation verbatim, and a one-sentence action grounded in the
  number.

You may make multiple tool calls if a question requires combining
metrics (e.g. dark fraction + channel CAC bounds for the dark-channel
attribution question).
"""


@dataclass
class LLMAnswer:
    question_id: str
    question_text: str
    value: Optional[float]
    final_text: str
    tool_trace: list[dict]   # list of {tool, args, result_summary}
    n_turns: int


def _short_result(r: MetricResult) -> dict:
    """Compact dict an LLM can read efficiently."""
    return dict(
        metric_name=r.metric_name,
        value=r.value,
        confidence=round(r.confidence, 3),
        sample_n=r.sample_n,
        window_open=r.window_open,
        interpretation=r.interpretation,
        trace=r.trace,
    )


class LLMGrowthAgent:
    def __init__(self, session: Optional[ToolSession] = None,
                 model: str = MODEL, week: str = "2024-W01"):
        self.session = session or ToolSession()
        self.model = model
        self.week = week
        self._tool_specs = build_tool_specs()
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return
        try:
            import anthropic
        except ImportError:
            raise RuntimeError("anthropic SDK not installed. pip install anthropic")
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set in env / .env")
        self._client = anthropic.Anthropic(api_key=api_key)

    def answer(self, question_id: str, question_text: str) -> LLMAnswer:
        self._ensure_client()

        # Cache the system prompt + tool definitions for cheap re-use.
        system = [dict(type="text", text=SYSTEM_PROMPT,
                       cache_control=dict(type="ephemeral"))]

        messages: list[dict] = [
            dict(role="user", content=f"Q{question_id}: {question_text}\n\n"
                                       f"week_of context: {self.week}")
        ]

        tool_trace: list[dict] = []
        for turn in range(MAX_TOOL_TURNS):
            response = self._client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=system,
                tools=self._tool_specs,
                messages=messages,
            )

            stop = response.stop_reason
            content_blocks = response.content

            # Collect text + tool_use blocks
            text_parts: list[str] = []
            tool_uses: list[Any] = []
            for block in content_blocks:
                bt = getattr(block, "type", None)
                if bt == "text":
                    text_parts.append(block.text)
                elif bt == "tool_use":
                    tool_uses.append(block)

            # If model produced no tool calls, we're done.
            if not tool_uses or stop == "end_turn":
                final = "\n\n".join(text_parts).strip() or "(no response)"
                return LLMAnswer(question_id, question_text, None, final, tool_trace, turn + 1)

            # Append the assistant turn verbatim so the conversation stays in sync.
            messages.append(dict(role="assistant", content=content_blocks))

            # Execute each tool_use and append tool_results.
            tool_results_blocks: list[dict] = []
            for tu in tool_uses:
                tool_name = tu.name
                args = tu.input or {}
                try:
                    result = self.session.call(tool_name, **args)
                    payload = _short_result(result)
                    is_error = False
                except Exception as e:
                    payload = dict(error=str(e), tool=tool_name, args=args)
                    is_error = True
                tool_trace.append(dict(
                    tool=tool_name, args=args, result=payload, is_error=is_error,
                ))
                tool_results_blocks.append(dict(
                    type="tool_result",
                    tool_use_id=tu.id,
                    content=json.dumps(payload, default=str),
                    is_error=is_error,
                ))

            messages.append(dict(role="user", content=tool_results_blocks))

        # Exhausted turns without an end_turn — return whatever we have.
        return LLMAnswer(
            question_id, question_text, None,
            f"(MAX_TOOL_TURNS={MAX_TOOL_TURNS} reached without end_turn)",
            tool_trace, MAX_TOOL_TURNS,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

CANONICAL = {
    "Q01": "What is the week-1 ghost rate for Unstop cohort?",
    "Q09": "What is the unattributed (dark channel) fraction of week-1 signups, and what does it mean for channel attribution?",
    "Q10": "If we double Unstop spend, what is the estimated week-4 retention lift and its confidence interval?",
}


def main() -> None:
    qids = sys.argv[1:] or ["Q01", "Q09", "Q10"]
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set. Structural dry-run only.\n")
        print(f"Would send to model={MODEL} with {len(build_tool_specs())} tools registered.")
        print("Set ANTHROPIC_API_KEY in env/.env to enable live calls.")
        return

    agent = LLMGrowthAgent()
    for qid in qids:
        text = CANONICAL.get(qid, f"(unknown question id: {qid})")
        print(f"\n=== {qid} — {text} ===\n")
        try:
            ans = agent.answer(qid, text)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue
        print(f"  turns={ans.n_turns}  tool_calls={len(ans.tool_trace)}")
        for t in ans.tool_trace:
            print(f"    → {t['tool']}({t['args']})  "
                  f"{'ERROR' if t['is_error'] else 'OK'}")
        print()
        print("  agent answer:")
        for line in ans.final_text.splitlines():
            print(f"    {line}")
        print()


if __name__ == "__main__":
    main()
