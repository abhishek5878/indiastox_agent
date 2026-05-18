"""Eval scorecard route — return the latest run JSON."""
from __future__ import annotations

import json
from fastapi import APIRouter, HTTPException

from api.deps import EVAL_RESULTS

router = APIRouter(prefix="/api/eval", tags=["eval"])


@router.get("/latest")
def latest():
    runs = sorted(EVAL_RESULTS.glob("run_*.json"))
    if not runs:
        raise HTTPException(status_code=404, detail="no eval runs — run `make eval`")
    return json.loads(runs[-1].read_text())
