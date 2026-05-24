"""Daily insights digest — turn the insights extractor's JSON into a
human-readable morning briefing.

Designed to run via cron (Makefile target `make digest`, or a scheduled
GitHub Action) and emit:
  - plaintext to stdout (for Slack webhook, email, or scrollback)
  - optionally markdown to a fixed file (for the dashboard to load)

The substrate's insights_generate() already does the heavy lifting. This
module's job is presentation: pick the top N, format each into a one-
glance briefing block, and group by scanner kind so the team can scan
the digest in 30 seconds.

Format (per insight):
  [<kind>] surprise=<score>
  <one-line summary>
  -> <suggested experiment>
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from metrics.definitions import insights_generate

DIGEST_VERSION = "1.0.0"


def render_digest(week_of: str = "2024-W01", top_n: int = 5,
                  fmt: str = "text") -> str:
    """Render a digest of the top-N insights.

    fmt: 'text' for terminal/Slack, 'markdown' for file/dashboard.
    """
    m = insights_generate(week_of=week_of, top_n=top_n)
    insights = m.breakdowns["insights"]
    by_kind = m.breakdowns["by_kind"]
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if fmt == "markdown":
        return _render_markdown(insights, by_kind, week_of, when, m.value)
    return _render_text(insights, by_kind, week_of, when, m.value)


def _render_text(insights: list, by_kind: dict, week_of: str,
                 when: str, top_score: float) -> str:
    lines: list[str] = []
    lines.append(f"IndiaStox insights digest")
    lines.append(f"as of {when} -- week {week_of}")
    lines.append(f"top surprise={top_score:.2f}  scanners={sorted(by_kind)}")
    lines.append("=" * 60)
    if not insights:
        lines.append("(no insights cleared the scanner floors)")
        return "\n".join(lines)
    for i, ins in enumerate(insights, 1):
        lines.append("")
        lines.append(f"#{i} [{ins['kind']}]  surprise={ins['surprise_score']:.2f}")
        lines.append(f"   {ins['summary']}")
        lines.append(f"   -> {ins['suggested_experiment']}")
    lines.append("")
    lines.append("-" * 60)
    lines.append(f"digest_version={DIGEST_VERSION}; full ranked list via insights_generate()")
    return "\n".join(lines)


def _render_markdown(insights: list, by_kind: dict, week_of: str,
                     when: str, top_score: float) -> str:
    lines: list[str] = []
    lines.append(f"# IndiaStox insights digest")
    lines.append(f"")
    lines.append(f"_as of {when} — week {week_of}_")
    lines.append(f"")
    lines.append(f"**Top surprise score:** {top_score:.2f}")
    lines.append(f"**Scanners that fired:** {', '.join(sorted(by_kind))}")
    lines.append(f"")
    if not insights:
        lines.append("_No insights cleared the scanner floors today._")
        return "\n".join(lines)
    lines.append(f"## Top {len(insights)} observations")
    lines.append(f"")
    for i, ins in enumerate(insights, 1):
        lines.append(f"### {i}. `{ins['kind']}` — surprise {ins['surprise_score']:.2f}")
        lines.append(f"")
        lines.append(f"{ins['summary']}")
        lines.append(f"")
        lines.append(f"**Suggested experiment:** {ins['suggested_experiment']}")
        lines.append(f"")
    lines.append(f"---")
    lines.append(f"_digest v{DIGEST_VERSION}; ranked output of `insights_generate()`_")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="IndiaStox daily insights digest")
    p.add_argument("--week", default="2024-W01")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--format", choices=("text", "markdown"), default="text")
    p.add_argument("--out", type=Path, default=None,
                   help="Write to this path instead of stdout")
    args = p.parse_args()
    output = render_digest(week_of=args.week, top_n=args.top, fmt=args.format)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output + "\n")
        print(f"wrote {args.out}  ({len(output)} chars)", file=sys.stderr)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
