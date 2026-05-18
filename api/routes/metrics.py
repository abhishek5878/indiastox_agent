"""Metric tool routes — list registered tools and invoke any one."""
from __future__ import annotations

import inspect
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from mcp.tools import TOOLS, ToolSession

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


def _underlying(fn):
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def _tool_meta(name: str, fn) -> dict:
    underlying = _underlying(fn)
    doc = (underlying.__doc__ or name).strip().split("\n")[0]
    try:
        sig = inspect.signature(underlying)
        params = []
        for pname, p in sig.parameters.items():
            ann = p.annotation
            type_name = (
                "string" if ann in (str, inspect.Parameter.empty) else
                "number" if ann is float else
                "integer" if ann is int else
                "boolean" if ann is bool else
                str(ann)
            )
            params.append(dict(
                name=pname,
                type=type_name,
                default=None if p.default is inspect.Parameter.empty else p.default,
                required=p.default is inspect.Parameter.empty,
            ))
    except (ValueError, TypeError):
        params = []
    return dict(name=name, description=doc, params=params)


@router.get("")
def list_tools():
    return [_tool_meta(n, fn) for n, fn in sorted(TOOLS.items())]


class InvokeRequest(BaseModel):
    args: dict[str, Any] = {}


@router.post("/{name}")
def invoke(name: str, payload: InvokeRequest):
    if name not in TOOLS:
        raise HTTPException(status_code=404, detail=f"unknown tool: {name}")
    session = ToolSession()
    # Drop empty-string kwargs that the UI sometimes sends for optional params.
    kwargs = {k: v for k, v in payload.args.items() if v not in (None, "", "None")}
    try:
        result = session.call(name, **kwargs)
    except TypeError as e:
        raise HTTPException(status_code=400, detail=f"argument error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"tool errored: {e}")
    return dict(
        metric_name=result.metric_name,
        value=result.value,
        confidence=result.confidence,
        sample_n=result.sample_n,
        provenance=result.provenance,
        window_open=result.window_open,
        interpretation=result.interpretation,
        trace=result.trace,
        definition_version=result.definition_version,
        definition_hash=result.definition_hash,
        confidence_interval=result.confidence_interval,
        breakdowns=result.breakdowns,
        as_of=result.as_of.isoformat(),
        session_id=session.session_id,
    )
