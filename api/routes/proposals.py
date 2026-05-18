"""Proposals + critiques inbox routes."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

import duckdb
import yaml
from fastapi import APIRouter, HTTPException

from api.deps import PROPOSALS_DIR, WAREHOUSE

router = APIRouter(prefix="/api/proposals", tags=["proposals"])

STATUSES = ("pending", "approved", "executed", "rejected")


@router.get("")
def list_proposals(status: Optional[str] = None):
    if status and status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"unknown status {status}")
    folders = [status] if status else list(STATUSES)
    items = []
    for f in folders:
        folder = PROPOSALS_DIR / f
        if not folder.exists():
            continue
        for p in folder.glob("*.yaml"):
            try:
                doc = yaml.safe_load(p.read_text())
            except Exception:
                continue
            items.append(dict(
                proposal_id=doc.get("proposal_id", p.stem),
                status=f,
                hypothesis=doc.get("hypothesis", ""),
                affected_metric=doc.get("affected_metric", ""),
                expected_lift_pct=doc.get("expected_lift_pct", 0),
                required_sample_n=doc.get("required_sample_n", 0),
                estimated_days=doc.get("estimated_days", 0),
                created_ts=doc.get("created_ts", ""),
                critique=doc.get("critique"),
                proposed_experiment=doc.get("proposed_experiment", ""),
            ))
    items.sort(key=lambda x: x.get("created_ts") or "", reverse=True)
    return items


def _move_and_log(proposal_id: str, new_status: str, action_label: str) -> dict:
    src: Optional[Path] = None
    for s in STATUSES:
        cand = PROPOSALS_DIR / s / f"{proposal_id}.yaml"
        if cand.exists():
            src = cand
            break
    if src is None:
        raise HTTPException(status_code=404, detail=f"proposal {proposal_id} not found")

    dst_dir = PROPOSALS_DIR / new_status
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    src.replace(dst)

    if WAREHOUSE.exists():
        con = duckdb.connect(str(WAREHOUSE), read_only=False)
        try:
            con.execute(
                "UPDATE proposals SET status = ? WHERE proposal_id = ?",
                [new_status, proposal_id],
            )
            con.execute(
                """INSERT INTO agent_actions
                   (action_id, ts, session_id, tool_name, args_json, result_hash,
                    result_confidence, downstream_proposal_id, _source_system)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    f"act-{uuid.uuid4().hex[:16]}",
                    datetime.now(timezone.utc).replace(tzinfo=None),
                    "api-human",
                    action_label,
                    json.dumps({"proposal_id": proposal_id}),
                    "human-decision",
                    1.0,
                    proposal_id,
                    "api.proposals",
                ],
            )
        finally:
            con.close()
    return dict(proposal_id=proposal_id, new_status=new_status)


@router.post("/{proposal_id}/{action}")
def act(proposal_id: str, action: Literal["approve", "reject", "execute"]):
    target = {"approve": "approved", "reject": "rejected", "execute": "executed"}[action]
    label = {"approve": "proposal_approved", "reject": "proposal_rejected", "execute": "proposal_executed"}[action]
    return _move_and_log(proposal_id, target, label)
