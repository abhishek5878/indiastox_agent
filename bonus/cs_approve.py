"""Approve a CS intervention. Moves YAML to interventions/approved/, logs an
agent_action row recording the human decision.

Usage:
  python3 -m bonus.cs_approve USER_ID=<uid>
  python3 -m bonus.cs_approve USER_ID=<uid> --reject
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb

_REPO = Path(__file__).resolve().parents[1]
PENDING = _REPO / "interventions" / "pending"
APPROVED = _REPO / "interventions" / "approved"
REJECTED = _REPO / "interventions" / "rejected"
WAREHOUSE = _REPO / "warehouse" / "indiastox.duckdb"


def _parse_kv(argv: list[str]) -> dict[str, str]:
    out = {}
    for a in argv:
        if "=" in a and not a.startswith("--"):
            k, v = a.split("=", 1)
            out[k] = v
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reject", action="store_true")
    args, rest = parser.parse_known_args()
    kv = _parse_kv(rest)
    user_id = kv.get("USER_ID")
    if not user_id:
        print("usage: python3 -m bonus.cs_approve USER_ID=<uid>", file=sys.stderr)
        sys.exit(2)

    src = PENDING / f"{user_id}.yaml"
    if not src.exists():
        print(f"ERROR: {src} not found", file=sys.stderr)
        sys.exit(2)
    dst_dir = REJECTED if args.reject else APPROVED
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    src.replace(dst)

    decision = "intervention_rejected" if args.reject else "intervention_approved"
    con = duckdb.connect(str(WAREHOUSE), read_only=False)
    try:
        con.execute(
            """INSERT INTO agent_actions
               (action_id, ts, session_id, tool_name, args_json, result_hash,
                result_confidence, downstream_proposal_id, _source_system)
               VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
            [
                f"act-{uuid.uuid4().hex[:16]}",
                datetime.now(timezone.utc),
                "human-approval",
                decision,
                json.dumps({"user_id": user_id}),
                "human-decision",
                1.0,
                "bonus.cs_approve",
            ],
        )
    finally:
        con.close()
    print(f"moved {src.name} → {dst}")
    print(f"logged agent_action: {decision}")


if __name__ == "__main__":
    main()
