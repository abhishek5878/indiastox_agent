"""LLM Growth Agent route — server-sent events streaming tool calls + final answer."""
from __future__ import annotations

import json
import os
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/llm", tags=["llm"])


class ChatRequest(BaseModel):
    question: str


def _has_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


@router.get("/status")
def status():
    return dict(has_key=_has_key(), model="claude-sonnet-4-6")


def _format_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def _run_agent(question: str) -> AsyncGenerator[str, None]:
    """Run the LLM growth agent and emit SSE events along the way.

    We re-use the existing LLMGrowthAgent. It's synchronous, so we
    stream the START / TOOL_CALL / FINAL frames after each completes.
    """
    yield _format_sse("start", dict(question=question))
    try:
        from agent.llm_growth_agent import LLMGrowthAgent
        agent = LLMGrowthAgent()
    except Exception as e:
        yield _format_sse("error", dict(message=str(e)))
        yield _format_sse("end", dict(ok=False))
        return

    try:
        ans = agent.answer("user", question)
    except Exception as e:
        yield _format_sse("error", dict(message=str(e)))
        yield _format_sse("end", dict(ok=False))
        return

    for t in ans.tool_trace:
        yield _format_sse("tool_call", t)
    yield _format_sse("final", dict(text=ans.final_text, turns=ans.n_turns))
    yield _format_sse("end", dict(ok=True))


@router.post("/chat")
async def chat(req: ChatRequest):
    if not _has_key():
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not set")
    return StreamingResponse(_run_agent(req.question), media_type="text/event-stream")
