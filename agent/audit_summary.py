"""`make audit` — rolling summary of the agent_actions audit log.

The audit log fills up with every tool call, every proposal, every
critique, every CS-Agent draft, every human approval — and nobody
reads it. This script makes it consumable in 20 seconds.

Sections:
  1. Tool-call counts (last 7 days) by name, sorted.
  2. Mean result_confidence per tool — surfaces tools whose confidence
     has drifted low without anyone noticing.
  3. Proposals by status — pending / approved / executed / rejected.
  4. Critique severity distribution — parsed from
     agent_actions.args_json where tool_name = 'critique_proposal'.
  5. Top sessions by activity — the long-running agent sessions worth
     auditing in detail.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb

_REPO = Path(__file__).resolve().parents[1]
WAREHOUSE = _REPO / "warehouse" / "indiastox.duckdb"


def _ascii_bar(n: int, total: int, width: int = 20) -> str:
    if total <= 0:
        return ""
    filled = int(round(n * width / total))
    return "█" * filled + "·" * (width - filled)


def render(days: int = 7) -> dict:
    """Return the summary as a dict so it's reusable from tests + the UI."""
    if not WAREHOUSE.exists():
        return dict(error="warehouse missing", days=days)

    cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None).isoformat()
    con = duckdb.connect(str(WAREHOUSE), read_only=False)
    try:
        tools = con.execute(
            """SELECT tool_name, COUNT(*) AS n, AVG(result_confidence) AS mean_conf
               FROM agent_actions WHERE ts >= ?
               GROUP BY tool_name ORDER BY n DESC""",
            [cutoff_iso],
        ).fetchall()
        total_calls = sum(r[1] for r in tools)

        try:
            statuses = con.execute(
                "SELECT status, COUNT(*) FROM proposals GROUP BY status ORDER BY COUNT(*) DESC"
            ).fetchall()
        except duckdb.CatalogException:
            statuses = []

        severities: dict[str, int] = {"low": 0, "medium": 0, "high": 0, "unknown": 0}
        critique_rows = con.execute(
            """SELECT args_json FROM agent_actions
               WHERE ts >= ? AND tool_name = 'critique_proposal'""",
            [cutoff_iso],
        ).fetchall()
        for (args,) in critique_rows:
            try:
                d = json.loads(args)
                sev = d.get("severity", "unknown")
                if sev in severities:
                    severities[sev] += 1
                else:
                    severities["unknown"] += 1
            except Exception:
                severities["unknown"] += 1

        top_sessions = con.execute(
            """SELECT session_id, COUNT(*) AS n,
                      COUNT(DISTINCT tool_name) AS tool_variety,
                      MIN(ts) AS first_at, MAX(ts) AS last_at
               FROM agent_actions WHERE ts >= ?
               GROUP BY session_id ORDER BY n DESC LIMIT 5""",
            [cutoff_iso],
        ).fetchall()

        downstream = con.execute(
            """SELECT tool_name, downstream_proposal_id, ts FROM agent_actions
               WHERE downstream_proposal_id IS NOT NULL AND ts >= ?
               ORDER BY ts DESC LIMIT 5""",
            [cutoff_iso],
        ).fetchall()
    finally:
        con.close()

    return dict(
        days=days,
        total_calls=total_calls,
        tools=[dict(name=t[0], n=int(t[1]), mean_conf=float(t[2] or 0)) for t in tools],
        proposal_status=[dict(status=s[0], n=int(s[1])) for s in statuses],
        critique_severity=severities,
        top_sessions=[dict(
            session_id=s[0], n=int(s[1]), tool_variety=int(s[2]),
            first_at=str(s[3]), last_at=str(s[4]),
        ) for s in top_sessions],
        downstream=[dict(tool=d[0], proposal_id=d[1], ts=str(d[2])) for d in downstream],
    )


def print_summary(summary: dict) -> None:
    if "error" in summary:
        print(f"audit-summary: {summary['error']}")
        return
    days = summary["days"]
    total = summary["total_calls"]
    print(f"\n=== agent_actions audit — last {days} days ===\n")
    print(f"Total tool calls: {total}\n")

    print("Tool-call frequency + mean confidence:")
    if not summary["tools"]:
        print("  (no tool calls in window)")
    for t in summary["tools"]:
        bar = _ascii_bar(t["n"], total)
        print(f"  {t['name']:32s}  {t['n']:5d}  {bar}  conf={t['mean_conf']:.2f}")

    print("\nProposals by status:")
    if not summary["proposal_status"]:
        print("  (no proposals)")
    for s in summary["proposal_status"]:
        print(f"  {s['status']:12s}  {s['n']}")

    print("\nCritique severity distribution:")
    for sev, n in summary["critique_severity"].items():
        print(f"  {sev:8s}  {n}")

    print("\nTop sessions (by activity):")
    if not summary["top_sessions"]:
        print("  (no sessions in window)")
    for s in summary["top_sessions"]:
        print(f"  {s['session_id']}  calls={s['n']}  tool_variety={s['tool_variety']}  "
              f"window={s['first_at'][:19]} → {s['last_at'][:19]}")

    print("\nDownstream-proposal events (recent):")
    if not summary["downstream"]:
        print("  (none)")
    for d in summary["downstream"]:
        print(f"  {d['ts'][:19]}  {d['tool']:24s} → {d['proposal_id']}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    s = render(days=args.days)
    if args.json:
        print(json.dumps(s, indent=2, default=str))
    else:
        print_summary(s)


if __name__ == "__main__":
    main()
