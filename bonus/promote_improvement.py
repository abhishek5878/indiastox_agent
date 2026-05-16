"""Promote a proposed improvement into effect.

Usage:
  python3 -m bonus.promote_improvement LINE=<N>

For the prototype, "promotion" doesn't auto-edit code — it MARKS the
improvement as accepted in the JSON file and logs the human decision to
agent_actions with tool_name='self_improvement'. Actually applying the
change is a human edit guided by the rationale in PROPOSED_IMPROVEMENTS.md
(safer than auto-patching production code).

This keeps the loop honest: the agent identifies, the human edits, the
audit trail records WHICH improvement was accepted under WHICH eval run.
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
IMPROV_JSON = _REPO / "data" / "proposed_improvements.json"
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
    line = kv.get("LINE")
    if not line:
        print("usage: python3 -m bonus.promote_improvement LINE=<N>", file=sys.stderr)
        sys.exit(2)
    try:
        idx = int(line) - 1
    except ValueError:
        print(f"ERROR: LINE must be an integer, got {line!r}", file=sys.stderr)
        sys.exit(2)

    if not IMPROV_JSON.exists():
        print(f"ERROR: {IMPROV_JSON} not found — run `make eval` first.", file=sys.stderr)
        sys.exit(2)

    payload = json.loads(IMPROV_JSON.read_text())
    improvements = payload.get("improvements", [])
    if idx < 0 or idx >= len(improvements):
        print(f"ERROR: LINE={line} out of range (1..{len(improvements)})", file=sys.stderr)
        sys.exit(2)
    imp = improvements[idx]

    status = "rejected" if args.reject else "accepted"
    imp["promoted_at"] = datetime.now(timezone.utc).isoformat()
    imp["status"] = status
    IMPROV_JSON.write_text(json.dumps(payload, indent=2, default=str))

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
                "self_improvement",
                json.dumps({
                    "improvement_index": int(line),
                    "question_id": imp["question_id"],
                    "kind": imp["kind"],
                    "category": imp["category"],
                    "status": status,
                    "target": imp["proposed_change"]["target"],
                }),
                "human-decision",
                1.0,
                "bonus.promote_improvement",
            ],
        )
    finally:
        con.close()

    print(f"Improvement #{line} ({imp['question_id']} — {imp['kind']}): {status}")
    print(f"Target file to edit: {imp['proposed_change']['target']}")
    print(f"Note: {imp['proposed_change']['note']}")
    print(f"logged agent_action: self_improvement / {status}")


if __name__ == "__main__":
    main()
