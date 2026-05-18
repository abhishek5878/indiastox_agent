"""Shared FastAPI dependencies — DuckDB connection, repo paths, env."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / ".env")
except ImportError:
    pass

REPO = _REPO
WAREHOUSE = _REPO / "warehouse" / "indiastox.duckdb"
PROPOSALS_DIR = _REPO / "proposals"
INTERVENTIONS_DIR = _REPO / "interventions"
ASSETS = _REPO / "assets"
EVAL_RESULTS = _REPO / "eval" / "results"


def warehouse_path() -> Path:
    """FastAPI dependency that asserts the warehouse exists."""
    if not WAREHOUSE.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="warehouse missing — run `make all`")
    return WAREHOUSE
