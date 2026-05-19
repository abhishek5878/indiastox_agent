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

- 2026-05-16 [VERIFICATION] A bit-exact reproducibility check
  (compare result_hash + definition_hash) is the only way to catch
  silent metric-definition drift between when a proposal was made
  and when an auditor reviews it months later. Cheap: one extra
  field on MetricResult, one ledger table, one `make reproduce`
  command. Without it, every dashboard number is a "trust me" the
  agent has no way to retract.

- 2026-05-16 [AGENT] When the data doesn't support the brief's
  intuitive answer (e.g. correlation between activity and skill
  came back at 0.02, not 0.67), the agent must say so. The position
  paper now leads with that disagreement instead of papering over
  it. Rule: if the cited number contradicts the position, restate
  the position with the qualifier — never hide the number.

- 2026-05-16 [LOOP] The eval-loop closes on itself when the
  improvement pass is *auto-triggered* after every eval run, not
  when it's a separate command the user must remember. Put the
  closure in the make target, not the runbook.

- 2026-05-16 [SCOPE] At-risk-user criteria specified in absolute
  terms (e.g. `phi > 300`) drift apart from the actual data
  distribution as the estimator matures. Use percentile thresholds
  (e.g. `phi >= 75th percentile`) so the criterion stays meaningful
  as the data evolves. The data tells you what "high" means.

- 2026-05-16 [REVIEW] The README is the single highest-leverage
  perception file. A reviewer who reads top-to-bottom and sees
  `## Stack TBD` will form a "this is unfinished" impression in 30
  seconds, even if the work below is excellent. Rule: when a
  decision is recorded ANYWHERE in the repo (CLAUDE.md, position
  paper, Makefile targets), reflect it in the README the same day.
  README inconsistency reads as project inconsistency.

- 2026-05-16 [REVIEW] Shipping no rendered dashboard is the
  HARSHER version of "dashboards that look pretty but tell no
  story" — at least the pretty-pointless dashboard has rendered
  artifacts to critique. A reviewer can't form an opinion about
  what doesn't exist except "it doesn't exist". Rule: even when
  the production dashboard tool isn't bringable-up locally, render
  the four panels as markdown tables or screenshots so the Loom
  has something to pan over. A text-rendered panel beats a YAML
  comment.

- 2026-05-16 [REVIEW] Q-numbering on a brief's open questions
  matters. The brief asked three; I answered two-and-substituted-my-own.
  A reviewer scanning for the brief's literal questions saw two of
  the four mandated names buried inside `verify_failure_modes.py`
  imports and read it as missing work. Rule: when the brief
  numbers its questions, answer them by number. Substitutions read
  as "didn't quite follow instructions" on a fast scan — even when
  the substitute question is better.

- 2026-05-16 [DEMO] Loom narrative leads with substance, not
  scaffold. The viewer wants to see the funnel, the eval scorecard
  firing, the proposal pipeline closing — not how I built it. The
  10-second mention of the .claude/ discipline goes at the end
  ("here's how I'd hand this to the next engineer"), never at the
  start. Anything that competes with the deliverable for the first
  90 seconds is debt against the perception.

- 2026-05-16 [REVIEW] When honest about a weak data signal (e.g.
  the synthetic-data correlation came back near-zero), frame it
  as "showing the architecture, not validating the causal claim"
  rather than "the data doesn't support our conclusion". Both
  statements are technically accurate; only the first preserves
  the reader's ability to evaluate the architecture on its own
  merits without the data-quality issue contaminating the read.
  Rule: when surfacing a data limitation in a position paper,
  separate it from the design argument the paper is making.

- 2026-05-16 [VERIFICATION] The defined-once-metric rule can leak
  through dashboard SQL — a panel that recomputes `ghost_rate`
  inline rather than reading `metric_results` is the failure mode
  FM2 was designed to catch. The verifier caught it during the
  reviewer-feedback pass and it would have shipped without the
  scaffold. Rule: any presentation surface (Metabase, render
  scripts, slide decks) that names a metric reads its value from
  the materialization, never recomputes — even when the SQL is
  short.

## How to use this file

- Skim at session start (read automatically via the `plan` skill).
- Add after every user correction.
- Consolidate weekly: merge similar lessons, delete obsolete ones.
- When a lesson has been followed for 30+ sessions without violation, promote it to `CLAUDE.md` as a hard rule.

## Adversarial framing for entries

When writing a lesson, ask: *would this pattern-match on the next occurrence?* "Don't break things" is not a lesson. "When editing identity-resolution logic, never collapse a probabilistic match to a boolean — always preserve the confidence and provenance" is a lesson.

- 2026-05-19 [STYLE] User explicitly flagged em-dashes (—) as
  unprofessional in user-facing surfaces (UI strings, agent
  prose, README, ONBOARDING). Same rule as the prior emoji
  prohibition. Replace with sentence breaks ("text. Text") or
  commas. Applies to *every* surface that renders to a user:
  glossary entries, page copy, system prompts, CS templates,
  proposal critique text, README, ONBOARDING. Data-layer
  identifiers (table names, event kinds) are NOT user-facing
  and stay as-is.

- 2026-05-19 [DEMO] Seed YAML files generated by experiment_loop
  + cs_agent can ship clones. A reviewer noticed 9 identical
  proposal YAMLs (same hypothesis, same lift, same metric) and
  10 templated CS messages varying only by ticker. Before any
  external demo, audit `proposals/pending/` + `interventions/
  pending/` for cohort variance. If the generator produces
  clones, either dedupe before commit OR hand-author distinct
  examples that exercise different confounders / metrics.

- 2026-05-19 [TERMINOLOGY] Data-layer names (fact_prediction,
  prediction_made event kind, weekly_active_posters function) can
  diverge from product UX names ("Make a Call", BULL/BEAR,
  "weekly active callers") indefinitely — DON'T migrate the data
  layer just to match UI. The wire protocol stays stable; the UI
  layer maps. BUT every user-facing string must be in product
  lexicon. Acceptance test: grep the UI surfaces for the legacy
  word; zero hits = done. The LLM system prompt must explicitly
  mandate the rewrite, otherwise the agent will quote the
  data-layer `interpretation` verbatim and leak the legacy term
  back into user output.

- 2026-05-19 [UX] When humanizing a function name in the UI for
  readability (`weekly_active_posters` -> "Weekly active
  callers"), ALWAYS render the raw function name beside it in
  mono ("Weekly active callers (weekly_active_posters)"). A
  reviewer who sees only the humanized form will run
  `make metric M=weekly_active_callers` and get a KeyError. The
  humanization is for skim-reading; the raw name is for
  grepping, CLI use, and debugging. Both belong on the same
  surface.

- 2026-05-19 [DEPLOY] Seed files force-added into a
  .gitignore'd directory don't auto-include new siblings.
  Generating 2 new proposal YAMLs into `proposals/pending/`
  (gitignored as `proposals/pending/*.yaml`) silently missed the
  next commit; Render redeployed without them and the live
  /proposals page kept showing the old data. Rule: after any
  generator writes into a gitignored directory, run
  `git status` AND verify the files are tracked via
  `git ls-files <path>`. The first commit force-added the
  whole directory; the second commit needed to force-add the
  new files explicitly.

- 2026-05-19 [VERIFY] When adding a new top-level directory
  that legitimately consumes a metric tool (here: `api/` and
  `sim/`), update `verify_failure_modes.py::check_2_defined_once`
  in the same commit. The check whitelists known-good
  directories by name; an unrecognized dir with SQL arithmetic
  and a ghost_rate reference will false-positive even when the
  file purely calls `ToolSession.call("ghost_rate", ...)`. The
  fix is a 2-line addition to the allowlist + a matching "ok"
  print branch. Run `make verify` before every commit that
  adds a metric-consuming module.

- 2026-05-19 [LOOPS] When you "close a loop" between product
  surfaces (sim ghost -> CS approve -> reengage_user;
  proposal approve -> experiment_started -> experiment_readout),
  also add a metric that scores the closure. ghost_recovery_rate
  scores the CS loop; proposal_lift_calibration_index scores
  the Critic. Without the score, the loop is just plumbing; with
  it, the agent has feedback. Rule: every closed loop ships
  with a calibration metric that captures whether the loop is
  doing useful work.

- 2026-05-19 [SIM] Cohort-level data clusters (mu, phi, n_calls)
  defeat template variance — all 4 "Quiet week" CS messages
  rendered "phi 215, mu 1260" identically because the underlying
  skill data clusters at that point. Fix is twofold: (a) render
  numeric values with higher precision (phi 214.9 vs 215.0
  differentiates adjacent-cluster users), AND (b) vary the
  *body* of the message via the user's actual ticker, sector,
  and last outcome — not just the surrounding template. Stylized
  numbers are necessary but not sufficient.
