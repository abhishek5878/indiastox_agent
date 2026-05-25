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

- 2026-05-22 [PROCESS] When designing substrate-level work, propose
  ONE substantive design with adversarial counterarguments, not three
  dial settings on a menu. The user pushed back: "broad paths please
  we need to think deeper" — three "conservative / moderate /
  aggressive" options were lazy menu-picking, not depth. Rule: menus
  are for picking among well-understood paths; for design decisions,
  produce the design + the strongest counterarguments + the trap to
  watch for. Only use enumerable options when the trade-offs are
  genuinely orthogonal (architecture: SQLite vs Postgres) and the
  user has the context to choose. For substrate depth/horizon/scope,
  always propose then defend.

- 2026-05-22 [ARCH] When wiring a new substrate into existing code,
  ship the FULL wiring or none — intermediate states are confusing
  and get rolled back. P0.5a wired archetypes into persona generation
  only (archetype_slug in dim_user) but `gen_backend_events` still
  used the legacy uniform 30% ghost bucket. Tests passed, failure
  modes passed, metrics moved 4.6% — but the substrate wasn't
  actually doing work, and the DB state mismatched user intent.
  Rule: if substrate goes from "unused" to "used", make it one
  commit. Persona-level wiring without event-level wiring is a
  confusing middle state that misleads consumers and reviewers.

- 2026-05-22 [METHODOLOGY] For any classification rule (Gyaani, reward
  axes, segments), run candidate variants against the substrate FIRST
  and observe which archetypes/cohorts the rule picks. Only then
  commit thresholds to code. Three failure modes the meta-pattern
  exploration caught: (a) phi-only Gyaani rewards day_traders 100%
  but their win-rate is 0.406 — phi rewards clicking; (b) strict
  Gyaani (mu>=p90 AND phi<150 AND n>=10) produces 1 graduate on
  W01 because n caps at 11 — unreachable; (c) medium rule has
  fomo_cascader contamination at n=5 sample size. The two-tier
  resolution emerged from observing each failure, not from
  top-down design. User's framing: "the Facebook way" — define a
  rule, let the meta-pattern show, then lock in. Apply this
  exploration-first pattern to every classification gate.

- 2026-05-22 [METHODOLOGY] When sample-size gates feel restrictive,
  audit the relaxation BEFORE relaxing — measure how much of the new
  positive signal is noise. P2 reward-axes accuracy n_min=3 left 5
  zero-aspirant cohorts uncovered, tempting relaxation to n_min=2.
  Audit: 430 more scorable users, 109 new "perfect" scores, but 70
  (64.2%) were users with exactly 2 wins of 2 lucky calls. For the
  cohorts we wanted to cover (pharma/skeptic/anchored/diversifier/
  lurker), 100% of the new perfects were noise. The correct fix was
  a separate `presence` axis (no skill claim, no sample-size gate)
  — semantically distinct from the skill axes. Rule: sample-size
  gates protect against luck; if a real user need exists below the
  gate, build a separate metric that doesn't claim what it can't
  measure.

- 2026-05-22 [ARCH] Single source of truth for every classification
  rule. Gyaani has `classify_gyaani(mu, phi, n_resolved)`; reward
  axes have `_SCORERS` dispatch table; segments have `_SCORERS`
  dispatch table. Aggregators (share metrics, per-user tools, tests)
  all call into the same function — threshold/scoring logic never
  duplicates. Rule: when shipping a multi-tier rule, the tier
  thresholds belong to a single dict/constant + a single pure
  function. Population aggregates, per-user tools, and SQL
  cross-checks all consult that one function. If you find yourself
  copying threshold values into a second place, stop.

- 2026-05-22 [ARCH] When the substrate or data isn't there yet,
  ship the metric/axis/segment as an EXPLICIT stub with
  `status='stub_pending_X'` visible in outputs, not as a silent
  zero. P2 reward axes left influence + discovery stubbed; P3
  shadows stubbed; P4 calls_with_explanation_rate stubbed at
  version "0.0.0-stub". Consumers (agents, dashboards, future
  reviewers) can flag the gap honestly. Rule: a silently-zero
  metric pretends to measure something it can't; an explicit stub
  documents the gap and the unlock path. Always prefer the stub.

- 2026-05-25 [CONSUMPTION] Shipping a substrate is not the same as
  shipping a product — exposing 30+ metric tools through 12 sidebar
  items is consumption-hostile to non-engineers. After P0.5/P1/P2/
  P3/P4/P5/P7 all shipped and tested, user feedback was "still very
  difficult to consume". The fix was a single /briefing page that
  answers the meeting's own questions in plain English with status
  chips (✓ shipped / ◐ partial / ○ gated), live numbers, CTAs, and
  a sidebar regrouped 12-flat → 4 priority buckets (Story / Act /
  Drill / Engineering). Rule: every substrate phase should ship with
  a consumption surface in the same commit. If users can't read it,
  it isn't done. Build the narrative before the next substrate.

- 2026-05-25 [ARCH] Production-only DuckDB attach conflicts come from
  per-row nested connections in long-lived workers. funnel_stages
  worked locally (fresh process per pytest) but 500'd on Render
  because its _seg_mix loop opened a fresh DuckDB connection per
  stuck user via classify_user_segment → _user_calls → _connect.
  Under uvicorn's persistent worker, the file's already attached as
  'indiastox', and Python's reference-counting timing made the
  per-user opens collide. Fix pattern: open one connection at the
  top of the metric, batch-fetch all needed data into memory, then
  classify via a pure helper (classify_user_segment_from_data).
  Rule: in metric code, opening a DuckDB connection per loop
  iteration is a smell. Batch the fetch; classify in memory.

- 2026-05-25 [DEPLOY] Render bakes the warehouse into the Docker
  image. Code-only commits don't ship data changes; multi-week
  metrics (recovery_arc_evidence, activation_cohort_lift) returned
  zero-cohort results on production until a second commit
  (52cc8ca) explicitly added warehouse/indiastox.duckdb +
  raw/*.ndjson + data/skill_ratings.parquet. Rule: when a substrate
  phase regenerates data (multi-week, new event types, schema
  changes), the deploy is two commits: code first, data second.
  Audit `git status` for warehouse/raw/data file changes BEFORE
  declaring shipped-to-prod.

- 2026-05-25 [METHODOLOGY] Honesty-by-default in consumption
  surfaces. The briefing page reports 7/7 shipped + 0 partial only
  because both multi-week verifications actually returned non-zero
  cohorts; otherwise the status chip auto-flips back to partial and
  the gated list auto-grows. Rule: build status reporting that
  recomputes from the substrate state every render, never from
  hardcoded labels. A page that says "shipped" when the underlying
  metric returns zero is a lie waiting to happen.

- 2026-05-25 [SCOPE] When closing "partial" work, sequence by
  dependency not size. The 3 partials in this turn were P7b
  (independent, ~30min), P1 recovery-arc (needs P0.5b data), P6
  activation (needs P0.5b data). Started with P7b for the quick
  win, then P0.5b as the unlock for both data-dependent ones.
  Trying to close them in user-named order would have meant doing
  the slowest (P6) first while the data didn't exist. Rule:
  partials are gated on each other; surface the dependency graph
  and execute by it.
