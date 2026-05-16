"""Approve a proposal — moves the YAML, updates DuckDB, logs an action event.

Usage:

  python3 -m bonus.approve PROPOSAL_ID=<id>           # approve a pending proposal
  python3 -m bonus.approve PROPOSAL_ID=<id> --reject  # reject (move to rejected/, status=rejected)
  python3 -m bonus.approve PROPOSAL_ID=<id> --execute # mark as executed

End-to-end side effects:
  - move proposals/pending/<id>.yaml → proposals/approved|executed|rejected/
  - UPDATE proposals.status in DuckDB
  - INSERT a new agent_actions row recording the human decision
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
PROPOSALS_PENDING = _REPO / "proposals" / "pending"
PROPOSALS_APPROVED = _REPO / "proposals" / "approved"
PROPOSALS_EXECUTED = _REPO / "proposals" / "executed"
PROPOSALS_REJECTED = _REPO / "proposals" / "rejected"
WAREHOUSE = _REPO / "warehouse" / "indiastox.duckdb"


def _parse_kv(argv: list[str]) -> dict[str, str]:
    out = {}
    for a in argv:
        if "=" in a and not a.startswith("--"):
            k, v = a.split("=", 1)
            out[k] = v
    return out


def _move(src: Path, dst_dir: Path) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    src.replace(dst)
    return dst


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reject", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args, rest = parser.parse_known_args()
    kv = _parse_kv(rest)
    proposal_id = kv.get("PROPOSAL_ID")
    if not proposal_id:
        print("ERROR: pass PROPOSAL_ID=<id>", file=sys.stderr)
        sys.exit(2)

    src = PROPOSALS_PENDING / f"{proposal_id}.yaml"
    if not src.exists():
        print(f"ERROR: {src} not found in pending/", file=sys.stderr)
        sys.exit(2)

    if args.reject:
        new_status = "rejected"
        dst_dir = PROPOSALS_REJECTED
    elif args.execute:
        new_status = "executed"
        dst_dir = PROPOSALS_EXECUTED
    else:
        new_status = "approved"
        dst_dir = PROPOSALS_APPROVED

    moved = _move(src, dst_dir)

    con = duckdb.connect(str(WAREHOUSE), read_only=False)
    try:
        con.execute(
            "UPDATE proposals SET status = ? WHERE proposal_id = ?",
            [new_status, proposal_id],
        )
        # Log the human decision as its own agent_actions row.
        con.execute(
            """INSERT INTO agent_actions
               (action_id, ts, session_id, tool_name, args_json, result_hash,
                result_confidence, downstream_proposal_id, _source_system)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                f"act-{uuid.uuid4().hex[:16]}",
                datetime.now(timezone.utc),
                "human-approval",
                f"proposal_{new_status}",
                json.dumps({"proposal_id": proposal_id}),
                "human-decision",
                1.0,
                proposal_id,
                "bonus.approve",
            ],
        )
    finally:
        con.close()

    print(f"moved {src.name} → {moved}")
    print(f"proposals.status[{proposal_id}] = {new_status}")
    print(f"logged agent_action: proposal_{new_status}")


if __name__ == "__main__":
    main()
