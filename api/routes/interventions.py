"""CS interventions routes — list + approve/reject."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import duckdb
import yaml
from fastapi import APIRouter, HTTPException

from api.deps import INTERVENTIONS_DIR, WAREHOUSE

router = APIRouter(prefix="/api/interventions", tags=["interventions"])

STATUSES = ("pending", "approved", "rejected")


@router.get("")
def list_interventions(status: str = "pending"):
    if status not in STATUSES:
        raise HTTPException(status_code=400, detail="unknown status")
    items = []
    folder = INTERVENTIONS_DIR / status
    if not folder.exists():
        return items
    for p in folder.glob("*.yaml"):
        try:
            doc = yaml.safe_load(p.read_text())
        except Exception:
            continue
        items.append(dict(
            user_id=doc.get("user_id", p.stem),
            tone=doc.get("tone"),
            risk_score=doc.get("risk_score"),
            channel=doc.get("channel"),
            primary_ticker=doc.get("primary_ticker"),
            intervention_text=doc.get("intervention_text"),
            grounding_facts=doc.get("grounding_facts", []),
            n_predictions=doc.get("n_predictions"),
            n_correct=doc.get("n_correct"),
            estimated_reactivation_lift=doc.get("estimated_reactivation_lift"),
        ))
    items.sort(key=lambda x: x.get("risk_score") or 0, reverse=True)
    return items


@router.post("/{user_id}/{action}")
def act(user_id: str, action: Literal["approve", "reject"]):
    src = None
    for s in STATUSES:
        cand = INTERVENTIONS_DIR / s / f"{user_id}.yaml"
        if cand.exists():
            src = cand
            break
    if src is None:
        raise HTTPException(status_code=404, detail="intervention not found")

    target = {"approve": "approved", "reject": "rejected"}[action]
    dst_dir = INTERVENTIONS_DIR / target
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    src.replace(dst)

    # Close the sim<->CS loop: an approved intervention re-engages the user
    # in the Living World so they re-enter the candidate pool. Emits a
    # `user_reengaged` sim_event for the timeline.
    reengaged = False
    if action == "approve":
        try:
            from api.routes.sim import _world  # avoid circular import at module load
            from sim.world import reengage_user
            reengaged = reengage_user(_world, user_id)
        except Exception:
            reengaged = False

    if WAREHOUSE.exists():
        con = duckdb.connect(str(WAREHOUSE), read_only=False)
        try:
            con.execute(
                """INSERT INTO agent_actions
                   (action_id, ts, session_id, tool_name, args_json, result_hash,
                    result_confidence, downstream_proposal_id, _source_system)
                   VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
                [
                    f"act-{uuid.uuid4().hex[:16]}",
                    datetime.now(timezone.utc).replace(tzinfo=None),
                    "api-human",
                    f"intervention_{target}",
                    json.dumps({"user_id": user_id, "sim_reengaged": reengaged}),
                    "human-decision",
                    1.0,
                    "api.interventions",
                ],
            )
            if reengaged:
                # Best-effort: log a sim_event so the Living World timeline
                # shows the recovery. Mirrors sim.world._log_event shape.
                try:
                    from api.routes.sim import _world as _w_for_ts
                    sim_ts = _w_for_ts.sim_now
                except Exception:
                    sim_ts = datetime.now(timezone.utc).replace(tzinfo=None)
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
                        sim_ts,
                        datetime.now(timezone.utc).replace(tzinfo=None),
                        "user_reengaged",
                        user_id,
                        json.dumps({"by": "cs_intervention", "intervention_id": user_id}),
                        "cs",
                    ],
                )
        finally:
            con.close()
    return dict(user_id=user_id, new_status=target, sim_reengaged=reengaged)
