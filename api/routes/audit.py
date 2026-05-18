"""Audit trail route — wraps agent.audit_summary.render."""
from __future__ import annotations

from fastapi import APIRouter, Query

from agent.audit_summary import render as audit_render

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
def audit(days: int = Query(7, ge=1, le=90)):
    return audit_render(days=days)
