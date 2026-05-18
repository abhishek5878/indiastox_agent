"""Identity explorer routes — search dim_user, fetch edges."""
from __future__ import annotations

from typing import Optional

import duckdb
from fastapi import APIRouter, Query

from api.deps import REPO, WAREHOUSE

router = APIRouter(prefix="/api/identity", tags=["identity"])


@router.get("/search")
def search(q: str = Query(..., min_length=1), limit: int = 50):
    if not WAREHOUSE.exists():
        return []
    con = duckdb.connect(str(WAREHOUSE), read_only=False)
    try:
        rows = con.execute(
            """SELECT user_id, full_name, personal_email, college_email,
                      acquisition_source, identity_confidence, identity_flags
               FROM dim_user
               WHERE LOWER(user_id) LIKE '%' || LOWER(?) || '%'
                  OR LOWER(full_name) LIKE '%' || LOWER(?) || '%'
                  OR LOWER(personal_email) LIKE '%' || LOWER(?) || '%'
                  OR LOWER(COALESCE(college_email, '')) LIKE '%' || LOWER(?) || '%'
               LIMIT ?""",
            [q, q, q, q, limit],
        ).fetchall()
    finally:
        con.close()
    return [
        dict(
            user_id=r[0], full_name=r[1], personal_email=r[2], college_email=r[3],
            acquisition_source=r[4], identity_confidence=float(r[5] or 0),
            identity_flags=list(r[6] or []),
        )
        for r in rows
    ]


@router.get("/{user_id}/edges")
def edges(user_id: str):
    edges_db = REPO / "identity" / "edges.duckdb"
    if not edges_db.exists():
        return []
    con = duckdb.connect(str(edges_db), read_only=True)
    try:
        rows = con.execute(
            """SELECT source_system, source_key, key_type, confidence,
                      resolution_method, provenance, model_version
               FROM identity_edge WHERE entity_id = ?""",
            [user_id],
        ).fetchall()
    finally:
        con.close()
    return [
        dict(
            source_system=r[0], source_key=r[1], key_type=r[2],
            confidence=float(r[3]), resolution_method=r[4],
            provenance=r[5], model_version=r[6],
        )
        for r in rows
    ]


@router.get("/blocked-pairs")
def blocked_pairs(limit: int = 50):
    edges_db = REPO / "identity" / "edges.duckdb"
    if not edges_db.exists():
        return []
    con = duckdb.connect(str(edges_db), read_only=True)
    try:
        rows = con.execute(
            """SELECT entity_id, source_key, confidence, provenance
               FROM identity_edge WHERE resolution_method = 'blocked_shared_device'
               LIMIT ?""",
            [limit],
        ).fetchall()
    finally:
        con.close()
    return [
        dict(entity_id=r[0], source_key=r[1], confidence=float(r[2]), provenance=r[3])
        for r in rows
    ]
