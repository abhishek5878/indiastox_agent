"""`make reproduce PROPOSAL_ID=xxx`

Given a proposal, find the agent_actions row that triggered it, then for
EACH tool call in that agent session:
  1. Read the recorded MetricResult hash (from agent_actions.result_hash)
  2. Re-run the tool with the same args
  3. Compare result_hash to recorded
  4. Compare metric definition_hash to the recorded one

If hashes match → REPRODUCED ✓.
If any drift → print the diff so the auditor can see what changed since.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import duckdb

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from core.confidence import VERSION_REGISTRY
from mcp.tools import TOOLS, ToolSession  # noqa: F401 — ensures decorators run

WAREHOUSE = _REPO / "warehouse" / "indiastox.duckdb"


def _parse_kv(argv: list[str]) -> dict[str, str]:
    out = {}
    for a in argv:
        if "=" in a and not a.startswith("--"):
            k, v = a.split("=", 1)
            out[k] = v
    return out


def reproduce(proposal_id: str, *, force_old_hash: dict[str, str] | None = None) -> int:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        prop = con.execute(
            "SELECT triggered_by_action_id, created_ts FROM proposals WHERE proposal_id = ?",
            [proposal_id],
        ).fetchone()
        if not prop:
            print(f"ERROR: no proposal with id {proposal_id}", file=sys.stderr)
            return 2
        triggered_action_id = prop[0]
        session_id = con.execute(
            "SELECT session_id FROM agent_actions WHERE action_id = ?",
            [triggered_action_id],
        ).fetchone()[0]
        actions = con.execute(
            """SELECT action_id, tool_name, args_json, result_hash, result_confidence
               FROM agent_actions WHERE session_id = ? ORDER BY ts""",
            [session_id],
        ).fetchall()
    finally:
        con.close()

    print(f"Reproducing proposal {proposal_id} from session {session_id} ({len(actions)} tool calls)")
    print("=" * 78)
    any_diff = False
    for action_id, tool_name, args_json, recorded_hash, recorded_conf in actions:
        if tool_name in ("proposal_approved", "proposal_rejected", "proposal_executed"):
            print(f"  {tool_name}  (human-decision audit — skipped)")
            continue
        if tool_name not in TOOLS:
            print(f"  {tool_name}  WARN: tool no longer exists, cannot replay")
            any_diff = True
            continue

        # Compare the metric definition hash NOW vs what we recorded back then.
        current_version, current_hash = VERSION_REGISTRY.get(tool_name, ("?", "?"))
        if force_old_hash and tool_name in force_old_hash:
            old_hash = force_old_hash[tool_name]
        else:
            old_hash = None

        args = json.loads(args_json) if args_json else {}
        try:
            result = TOOLS[tool_name](**args)
        except Exception as e:
            print(f"  {tool_name}  ERROR re-running: {e}")
            any_diff = True
            continue
        new_hash = result.result_hash()
        new_def_hash = result.definition_hash
        if old_hash and old_hash != new_def_hash:
            print(f"  {tool_name}  DEFINITION DRIFT: recorded def_hash={old_hash[:8]} vs current={new_def_hash[:8]}")
            any_diff = True
            continue

        if new_hash == recorded_hash:
            print(f"  {tool_name}  REPRODUCED ✓  (def {new_def_hash[:8]})")
        else:
            print(f"  {tool_name}  DIFF — recorded result_hash {recorded_hash[:8]} vs new {new_hash[:8]}")
            print(f"           current value = {result.value}, current confidence = {result.confidence}")
            print(f"           definition_hash {new_def_hash[:8]} (v{current_version})")
            any_diff = True

    print("=" * 78)
    if any_diff:
        print("RESULT: DIFFs detected — proposal not bit-exact reproducible under current definitions.")
        return 1
    print("RESULT: REPRODUCED ✓ — every tool call returns the same result_hash under the same definitions.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-stale-hash-for", nargs="*", default=[],
                        help="metric=fakehash pairs — simulate definition drift (used by FM9 self-check).")
    args, rest = parser.parse_known_args()
    kv = _parse_kv(rest)
    pid = kv.get("PROPOSAL_ID")
    if not pid:
        print("usage: python3 -m bonus.reproduce PROPOSAL_ID=<id>", file=sys.stderr)
        sys.exit(2)
    force = {}
    for spec in args.force_stale_hash_for:
        if "=" in spec:
            k, v = spec.split("=", 1)
            force[k] = v
    rc = reproduce(pid, force_old_hash=force or None)
    sys.exit(rc)


if __name__ == "__main__":
    main()
