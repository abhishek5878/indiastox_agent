# Lessons

## Format

Each lesson is one line in the form: `[CATEGORY] Pattern — Rule`.

Categories: STYLE, GIT, SCOPE, TOOL, VERIFICATION, PLAN, INDIASTOX, AGENT.

## Entries

- 2026-05-16 [PLAN] When writing a logical-consistency test that combines two
  metrics by their *rate values*, verify both metrics share a denominator
  first — otherwise the bound (e.g. "sum ≤ 1") doesn't have to hold. Rule:
  compare counts (numerators) against a known shared denominator; rates only
  combine cleanly when they're rates of the *same* total. Caught while
  writing `test_ghost_and_participation_count_disjoint_for_unstop`.
- 2026-05-16 [TOOL] Python 3.9 environments require `from __future__ import
  annotations` plus a `types.UnionType` polyfill for files using PEP 604
  `X | None` syntax with runtime introspection (e.g. Pydantic, dataclasses).
  Rule: any file using new-style unions adds the import + handles both
  `typing.Union` and (if available) `types.UnionType`.
- 2026-05-16 [TOOL] Scripts placed in subdirs (`identity/resolve.py`,
  `bonus/experiment_loop.py`) need an explicit `sys.path.insert(0, REPO_ROOT)`
  at the top to import sibling top-level packages when run as `python3
  path/to/script.py`. Rule: every subdir entry-point includes this prelude
  so the Makefile targets work without `-m` invocations.

- 2026-05-16 [VERIFICATION] When a metric function and an "independent"
  ground-truth SQL produce different numbers on the same data with the
  same logical CTE shape, the divergence is almost always parameter-
  encoding (timestamptz vs literal string in DuckDB) rather than the
  query body. Surface this via the eval harness — comparing function
  output to SQL output is the only check that catches definition drift
  that doesn't show up in tests of the function in isolation.

- 2026-05-16 [AGENT] Honest "insufficient data" beats a confident-and-
  wrong point estimate every time. For counterfactual questions over
  small data (Q10: doubling spend on 1 week of data), the right agent
  behavior is `value=None` + wide CI + concrete data-collection proposal.
  Eval scoring should REWARD this, not punish it. Rule: when designing
  ground truth, distinguish "unknowable from current data" from "unknown
  to the agent"; only the latter counts as a failure.

- 2026-05-16 [VERIFICATION] Bare-float returns from metric tools are
  silent failures — the agent loses calibration/provenance with no
  type error to catch it. The runtime `@tool_result` decorator is the
  fix; rejecting at call time forces every tool to pass through the
  typed-confidence boundary.

- 2026-05-16 [CALIBRATION] Identity confidence should propagate down
  to metric confidence with a probabilistic-share penalty (e.g.
  `det − 0.5 × prob`). Without the penalty, every metric returns
  confidence ≥ 0.8 even when 18%+ of the underlying matches are
  fuzzy — the propagation chain "lies" by carrying only the high-
  confidence floor. FM5 in `verify_failure_modes.py` enforces this:
  ≥ 20% of metrics must dip below 0.8.

## How to use this file

- Skim at session start (read automatically via the `plan` skill).
- Add after every user correction.
- Consolidate weekly: merge similar lessons, delete obsolete ones.
- When a lesson has been followed for 30+ sessions without violation, promote it to `CLAUDE.md` as a hard rule.

## Adversarial framing for entries

When writing a lesson, ask: *would this pattern-match on the next occurrence?* "Don't break things" is not a lesson. "When editing identity-resolution logic, never collapse a probabilistic match to a boolean — always preserve the confidence and provenance" is a lesson.
