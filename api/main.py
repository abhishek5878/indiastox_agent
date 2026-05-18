"""IndiaStox FastAPI gateway.

Run:
    make api                              # uvicorn api.main:app --reload --port 8000
    open http://localhost:8000/docs       # Swagger UI

Routes are split across api/routes/* by concern.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from api.deps import ASSETS
from api.routes import (
    metrics as metrics_routes,
    sim as sim_routes,
    proposals as proposals_routes,
    identity as identity_routes,
    eval_route,
    interventions as interventions_routes,
    audit as audit_routes,
    llm as llm_routes,
)

app = FastAPI(
    title="IndiaStox substrate API",
    version="1.0.0",
    description="Agent-native analytics substrate — REST + WebSocket gateway over the same tool layer the agents use.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(metrics_routes.router)
app.include_router(sim_routes.router)
app.include_router(proposals_routes.router)
app.include_router(identity_routes.router)
app.include_router(eval_route.router)
app.include_router(interventions_routes.router)
app.include_router(audit_routes.router)
app.include_router(llm_routes.router)


@app.on_event("startup")
def _scrub_sim_state_on_boot() -> None:
    """Wipe any sim.world rows left in the warehouse so the demo boots clean.

    The warehouse ships baked into the Docker image; if the build snapshot
    contains rows from a previous local run, the deterministic tick seeds will
    collide on the very first /api/sim/tick. Scrubbing on startup also means
    every Render cold-start gives a fresh world.
    """
    from api.deps import WAREHOUSE
    if not WAREHOUSE.exists():
        return
    import duckdb
    con = duckdb.connect(str(WAREHOUSE), read_only=False)
    try:
        for sql in [
            "DELETE FROM sim_events",
            "DELETE FROM fact_prediction WHERE _source_system = 'sim.world'",
            "DELETE FROM fact_acquisition WHERE _source_system = 'sim.world'",
            "DELETE FROM dim_user WHERE _source_system = 'sim.world'",
        ]:
            try:
                con.execute(sql)
            except duckdb.CatalogException:
                pass
    finally:
        con.close()


@app.get("/api/health")
def health():
    return dict(ok=True, service="indiastox-api", version="1.0.0")


@app.get("/api/assets/{name}")
def asset(name: str):
    p = ASSETS / name
    if not p.exists() or p.suffix != ".png":
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="asset not found")
    return FileResponse(str(p), media_type="image/png")
