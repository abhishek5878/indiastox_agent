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


def _start_experiment(proposal_id: str) -> Optional[dict]:
    """When a proposal is approved, schedule its readout in the sim.

    Stores baseline + predicted_lift_pct + readout_at on an `experiment_started`
    sim_event. The sim's tick() later detects readouts past due and emits an
    `experiment_readout` event with actual vs predicted lift. Closes the
    proposal->experiment->outcome loop.
    """
    src = PROPOSALS_DIR / "approved" / f"{proposal_id}.yaml"
    if not src.exists():
        return None
    try:
        doc = yaml.safe_load(src.read_text())
    except Exception:
        return None
    snap = doc.get("metric_snapshot") or {}
    baseline = snap.get("value")
    if baseline is None:
        return None
    affected_metric = doc.get("affected_metric") or ""
    predicted_lift_pct = float(doc.get("expected_lift_pct") or 0.0)
    estimated_days = int(doc.get("estimated_days") or 7)

    # Pull the sim's current time so readout_at is in sim-time, not wall-time.
    try:
        from api.routes.sim import _world
        sim_now = _world.sim_now
    except Exception:
        sim_now = datetime.now(timezone.utc).replace(tzinfo=None)
    readout_at = sim_now + timedelta(days=estimated_days)

    if WAREHOUSE.exists():
        con = duckdb.connect(str(WAREHOUSE), read_only=False)
        try:
            con.execute(
                """CREATE TABLE IF NOT EXISTS sim_events (
                     event_id TEXT PRIMARY KEY, sim_ts TIMESTAMP NOT NULL,
                     wall_ts TIMESTAMP NOT NULL, kind TEXT NOT NULL,
                     actor TEXT, payload JSON, lens TEXT
                   )"""
            )
            con.execute(
                """INSERT INTO sim_events
                   (event_id, sim_ts, wall_ts, kind, actor, payload, lens)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    f"evt-{uuid.uuid4().hex[:16]}",
                    sim_now,
                    datetime.now(timezone.utc).replace(tzinfo=None),
                    "experiment_started",
                    proposal_id,
                    json.dumps(dict(
                        proposal_id=proposal_id,
                        affected_metric=affected_metric,
                        baseline=float(baseline),
                        predicted_lift_pct=predicted_lift_pct,
                        estimated_days=estimated_days,
                        readout_at=readout_at.isoformat(),
                    )),
                    "growth",
                ],
            )
        finally:
            con.close()
    return dict(
        proposal_id=proposal_id,
        affected_metric=affected_metric,
        baseline=float(baseline),
        predicted_lift_pct=predicted_lift_pct,
        readout_at=readout_at.isoformat(),
        estimated_days=estimated_days,
    )


# Need timedelta for _start_experiment.
from datetime import timedelta  # noqa: E402


@router.post("/auto")
def auto_propose(payload: Optional[dict] = None):
    """File the top insight from insights_generate as a Proposal.

    Returns the same shape as agent.auto_proposal.file_top_insight:
      {filed, reason, proposal_id, insight, ...}

    On filed=True, the proposal lands in /proposals/pending and the
    follow-up POST /api/proposals/{id}/approve schedules its
    experiment in the sim. This is the substrate's closed loop made
    callable from the browser — the /briefing page's growth_hack
    umbrella binds to it.
    """
    from agent.auto_proposal import SURPRISE_FLOOR, file_top_insight

    week = (payload or {}).get("week_of", "2024-W01")
    floor = float((payload or {}).get("surprise_floor", SURPRISE_FLOOR))
    return file_top_insight(week_of=week, surprise_floor=floor)


@router.post("/{proposal_id}/{action}")
def act(proposal_id: str, action: Literal["approve", "reject", "execute"]):
    target = {"approve": "approved", "reject": "rejected", "execute": "executed"}[action]
    label = {"approve": "proposal_approved", "reject": "proposal_rejected", "execute": "proposal_executed"}[action]
    result = _move_and_log(proposal_id, target, label)
    if action == "approve":
        result["experiment"] = _start_experiment(proposal_id)
    return result
