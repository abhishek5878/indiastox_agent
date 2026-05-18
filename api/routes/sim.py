"""Living-world simulation routes — tick, reset, state, event stream."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional

import duckdb
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from api.deps import WAREHOUSE
from sim.baseline import restore as restore_baseline
from sim.world import WorldState, fresh_world, tick as sim_tick, SIM_T0
from sim.watchers import growth_watcher_tick, cs_watcher_tick

router = APIRouter(prefix="/api/sim", tags=["sim"])

# Process-singleton WorldState — single user, single Streamlit-equivalent
# session for the demo. For multi-user we'd key off a session cookie.
_world: WorldState = fresh_world()


class TickRequest(BaseModel):
    minutes: int = 60
    run_watchers: bool = True


@router.get("/state")
def state():
    return dict(
        sim_now=_world.sim_now.isoformat(),
        tick_count=_world.tick_count,
        accel=_world.accel,
    )


@router.post("/tick")
def tick(req: TickRequest):
    if not WAREHOUSE.exists():
        raise HTTPException(status_code=503, detail="warehouse missing")
    counters = sim_tick(_world, advance_minutes=req.minutes)
    watcher_results: dict = {}
    if req.run_watchers:
        watcher_results["growth"] = growth_watcher_tick(_world.sim_now)
        watcher_results["cs"] = cs_watcher_tick(_world.sim_now)
    return dict(
        counters=counters,
        watchers=watcher_results,
        sim_now=_world.sim_now.isoformat(),
        tick_count=_world.tick_count,
    )


@router.post("/reset")
def reset():
    global _world
    try:
        restore_baseline()
    except SystemExit:
        raise HTTPException(status_code=500, detail="baseline restore failed — run `make baseline` first")
    _world = fresh_world()
    return state()


@router.get("/events")
def events(
    since: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    lens: Optional[str] = None,
):
    """Return recent sim_events, optionally filtered by lens and since-iso-timestamp."""
    if not WAREHOUSE.exists():
        return []
    con = duckdb.connect(str(WAREHOUSE), read_only=False)
    try:
        # Make sure the table exists even if no tick has run.
        con.execute(
            """CREATE TABLE IF NOT EXISTS sim_events (
                 event_id TEXT PRIMARY KEY,
                 sim_ts TIMESTAMP NOT NULL,
                 wall_ts TIMESTAMP NOT NULL,
                 kind TEXT NOT NULL,
                 actor TEXT,
                 payload JSON,
                 lens TEXT
               )"""
        )
        where = ["1=1"]
        params: list = []
        if since:
            try:
                cutoff = datetime.fromisoformat(since.replace("Z", ""))
                where.append("sim_ts > ?")
                params.append(cutoff)
            except ValueError:
                pass
        if lens and lens != "all":
            where.append("(lens = ? OR lens = 'all')")
            params.append(lens)
        sql = (
            "SELECT event_id, sim_ts, wall_ts, kind, actor, payload, lens "
            "FROM sim_events WHERE " + " AND ".join(where) +
            " ORDER BY sim_ts DESC, wall_ts DESC LIMIT ?"
        )
        rows = con.execute(sql, params + [limit]).fetchall()
    finally:
        con.close()
    return [
        dict(
            event_id=r[0],
            sim_ts=r[1].isoformat() if r[1] else None,
            wall_ts=r[2].isoformat() if r[2] else None,
            kind=r[3],
            actor=r[4],
            payload=json.loads(r[5]) if r[5] else {},
            lens=r[6],
        )
        for r in rows
    ]


@router.get("/kpis")
def kpis():
    """Lens-relevant KPI bundle, all in one round-trip."""
    if not WAREHOUSE.exists():
        return {}
    from mcp.tools import ToolSession
    s = ToolSession()
    try:
        gr = s.call("ghost_rate", week_of="2024-W01", acquisition_source="unstop")
        dk = s.call("dark_channel_fraction", week_of="2024-W01")
    except Exception:
        return {}

    con = duckdb.connect(str(WAREHOUSE), read_only=False)
    try:
        sim_n = con.execute(
            "SELECT COUNT(*) FROM dim_user WHERE _source_system = 'sim.world'"
        ).fetchone()[0] or 0
        recent_24h = con.execute(
            "SELECT COUNT(*) FROM fact_prediction WHERE _source_system = 'sim.world' AND made_at >= ?",
            [_world.sim_now - timedelta(hours=24)],
        ).fetchone()[0] or 0
        at_risk = con.execute(
            """SELECT COUNT(*) FROM dim_user du
               WHERE du.signup_time IS NOT NULL AND du.signup_time < ?
                 AND NOT EXISTS (
                   SELECT 1 FROM fact_prediction p
                   WHERE p.user_id = du.user_id AND p.made_at >= ?
                 )""",
            [_world.sim_now, _world.sim_now - timedelta(days=3)],
        ).fetchone()[0] or 0
        resolved_24h = con.execute(
            "SELECT COUNT(*) FROM fact_prediction WHERE is_outcome_resolved AND resolved_at >= ?",
            [_world.sim_now - timedelta(hours=24)],
        ).fetchone()[0] or 0
    finally:
        con.close()

    return dict(
        ghost_rate_unstop=dict(value=gr.value, confidence=gr.confidence,
                                interpretation=gr.interpretation, sample_n=gr.sample_n),
        dark_fraction=dict(value=dk.value, confidence=dk.confidence,
                            interpretation=dk.interpretation),
        sim_personas_new=int(sim_n),
        sim_preds_24h=int(recent_24h),
        at_risk_3d=int(at_risk),
        outcomes_resolved_24h=int(resolved_24h),
        sim_now=_world.sim_now.isoformat(),
        tick_count=_world.tick_count,
    )


# WebSocket for streaming live events. Frontend opens once; server polls
# sim_events for new rows every 1.5s and pushes deltas.
@router.websocket("/ws")
async def ws_events(websocket: WebSocket):
    await websocket.accept()
    last_seen: Optional[datetime] = None
    try:
        while True:
            if WAREHOUSE.exists():
                con = duckdb.connect(str(WAREHOUSE), read_only=False)
                try:
                    con.execute(
                        """CREATE TABLE IF NOT EXISTS sim_events (
                             event_id TEXT PRIMARY KEY,
                             sim_ts TIMESTAMP NOT NULL,
                             wall_ts TIMESTAMP NOT NULL,
                             kind TEXT NOT NULL,
                             actor TEXT,
                             payload JSON,
                             lens TEXT
                           )"""
                    )
                    if last_seen is None:
                        rows = con.execute(
                            "SELECT event_id, sim_ts, wall_ts, kind, actor, payload, lens "
                            "FROM sim_events ORDER BY wall_ts DESC LIMIT 20"
                        ).fetchall()
                    else:
                        rows = con.execute(
                            "SELECT event_id, sim_ts, wall_ts, kind, actor, payload, lens "
                            "FROM sim_events WHERE wall_ts > ? ORDER BY wall_ts ASC LIMIT 100",
                            [last_seen],
                        ).fetchall()
                finally:
                    con.close()

                if rows:
                    for r in rows:
                        await websocket.send_json(dict(
                            event_id=r[0],
                            sim_ts=r[1].isoformat() if r[1] else None,
                            wall_ts=r[2].isoformat() if r[2] else None,
                            kind=r[3],
                            actor=r[4],
                            payload=json.loads(r[5]) if r[5] else {},
                            lens=r[6],
                        ))
                    last_seen = max(r[2] for r in rows if r[2])

            await asyncio.sleep(1.5)
    except WebSocketDisconnect:
        return
