"""CLI shim — print any metric tool's result to the console.

  python3 -m agent.print_metric weekly_active_posters
  python3 -m agent.print_metric ghost_rate --acquisition_source unstop
  python3 -m agent.print_metric predictions_per_user --threshold 5 --acquisition_source unstop

The reviewer's note: the four brief-mandated metric names (weekly_active_posters,
time_to_first_action, unstop_to_participation_rate, ghost_rate) should be
front-and-center, not buried inside the verifier. Hence this CLI + `make metric M=...`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from mcp.tools import TOOLS, ToolSession

DEFAULTS = dict(week_of="2024-W01")


def parse_kwargs(rest: list[str]) -> dict:
    """Parse remaining argv into kwargs. Accepts --key value and --key=value."""
    out = {}
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok.startswith("--"):
            key = tok[2:]
            if "=" in key:
                k, v = key.split("=", 1)
                out[k] = _cast(v)
                i += 1
            else:
                if i + 1 < len(rest):
                    out[key] = _cast(rest[i + 1])
                    i += 2
                else:
                    out[key] = True
                    i += 1
        else:
            i += 1
    return out


def _cast(v: str):
    """Best-effort numeric / bool casting; fall back to string."""
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("metric", help="metric name (one of: " + ", ".join(sorted(TOOLS)) + ")")
    parser.add_argument("--json", action="store_true", help="emit the full MetricResult as JSON")
    parser.add_argument("--help", "-h", action="store_true")
    args, rest = parser.parse_known_args()

    if args.help or args.metric == "help":
        print("Usage: python3 -m agent.print_metric <metric_name> [--key value] [--json]")
        print("Available tools:")
        for n in sorted(TOOLS):
            print(f"  {n}")
        sys.exit(0)

    if args.metric not in TOOLS:
        print(f"ERROR: unknown metric '{args.metric}'.", file=sys.stderr)
        print("Available:", ", ".join(sorted(TOOLS)), file=sys.stderr)
        sys.exit(2)

    kwargs = dict(DEFAULTS)
    kwargs.update(parse_kwargs(rest))
    # Some tools don't take week_of (email_click_to_signup,
    # get_skill_distribution, metric_gameability_index). Walk the
    # decorator chain to find the underlying function and filter kwargs
    # against its real signature.
    fn = TOOLS[args.metric]
    target = fn
    while hasattr(target, "__wrapped__"):
        target = target.__wrapped__
    fn_params = set(target.__code__.co_varnames[: target.__code__.co_argcount])
    kwargs = {k: v for k, v in kwargs.items() if k in fn_params}

    session = ToolSession()
    result = session.call(args.metric, **kwargs)

    if args.json:
        print(json.dumps(result.model_dump(), default=str, indent=2))
        return

    print(f"{result.metric_name}  ({result.metric_version})")
    print(f"  value         = {result.value}")
    print(f"  confidence    = {result.confidence:.3f}")
    print(f"  sample_n      = {result.sample_n}")
    print(f"  window_open   = {result.window_open}")
    print(f"  provenance    = {result.provenance}")
    print(f"  interpretation: {result.interpretation}")
    if result.trace:
        print(f"  trace ('why this number?'):")
        for i, step in enumerate(result.trace, 1):
            print(f"    [{i}] {step}")
    print(f"  definition_hash = {result.definition_hash[:16]}...")
    print(f"  audit_session = {session.session_id}")


if __name__ == "__main__":
    main()
