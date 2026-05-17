# Progress

Backward-looking log. What happened, readable by a new session or a new engineer.

## 2026-05-16 — Phase 1: Scaffold the .claude/ directory and source-of-truth docs

### Actions taken
- Initialized git, made the "empty scaffold" first commit with SETUP.md, the IndiaStox brief, and a baseline `.gitignore`.
- Created `.claude/` skeleton per SETUP.md §3.
- Wrote the four `rules/` files (planning, git-practices, code-quality, session-persistence).
- Wrote the four `tasks/` working-memory files (todo, lessons, findings, progress).

### Files modified
- `.gitignore` — baseline ignore rules + carve-outs for `.claude/runs|logs|cache`.
- `.claude/rules/*.md` — four rule files, loaded on demand from CLAUDE.md.
- `.claude/tasks/*.md` — four working-memory files; only `todo.md` has live content so far.

### Issues encountered
- None this phase.

### Status
Phase 1 complete. Moving to Phase 2 (CLAUDE.md + starter skills).

## 2026-05-16 — Phase 2: Disciplines layer

### Actions taken
- Wrote `.claude/CLAUDE.md` (648 words, ~840 tokens, under the 1000-token hard rule).
- Wrote three starter skills: `plan`, `commit`, `verify`. Each has the §5.2 template structure with adversarial framing baked in.

### Files modified
- `.claude/CLAUDE.md` — IndiaStox-specific stack (TBD), code style, workflow, cross-model verification reminder, linked rules.
- `.claude/skills/{plan,commit,verify}/SKILL.md` — three starter skills.

### Status
Phase 2 complete.

## 2026-05-16 — Phase 3: Automation layer

### Actions taken
- Wrote six starter hook scripts (post-edit-format, post-edit-typecheck, pre-tool-use-plan, post-tool-use-progress, stop-verify, suggest-compact) as bash stubs. `chmod +x` applied.
- Wrote `.claude/settings.json` wiring hooks into PreToolUse / PostToolUse / Stop / UserPromptSubmit events with sensible matchers.
- Wrote two starter sub-agents: `planner` (Opus, planning-only) and `code-reviewer` (Opus, structured findings).

### Files modified
- `.claude/hooks/*.sh` — 6 hook scripts.
- `.claude/settings.json` — permissions + hooks block.
- `.claude/agents/{planner,code-reviewer}/*.md` — sub-agent definitions.

### Issues encountered
- Post-edit-format and post-edit-typecheck are no-op stubs because the stack is undecided. They emit a stderr note pointing at where to wire the real commands once the stack lands.

### Status
Phase 3 complete.

## 2026-05-16 — Phase 4: First plan + compounding-loop stubs

### Actions taken
- Wrote `.claude/tasks/task_plan.md` for the IndiaStox weekend prototype (per the brief §4): 7 phases covering stack pick, synthetic data, typed identity resolution, metric semantic layer, dashboard, position paper, closed-loop bonus event. Includes an adversarial-review section with three counterarguments.
- Wrote `.claude/rules/cross-model-verification.md` as a dedicated, discoverable home for the 15-exchange rule. CLAUDE.md also has the summary.
- Wrote `.claude/prompts/research-digest.md` + `.claude/research-digest.sh` for the research layer. Runner is a stub with TODOs pointing at the two cron-able invocation options.
- Wrote `.claude/hooks/log-events.sh` for the observation layer — appends every tool call and user prompt as one JSON line to `.claude/logs/events.jsonl` (gitignored).
- Wrote `.claude/prompts/self-edit-weekly.md` for the weekly ritual.
- Wrote `README.md` at repo root — points to SETUP.md as the operating manual, plus the agent-onboarding sequence.

### Files modified
- `.claude/tasks/task_plan.md` — first real feature plan.
- `.claude/rules/cross-model-verification.md` — discipline.
- `.claude/prompts/{research-digest,self-edit-weekly}.md` — prompts for the loop layers.
- `.claude/research-digest.sh` — daily runner stub.
- `.claude/hooks/log-events.sh` — observation hook (also wired in settings.json).
- `README.md` — repo entry point.

### Issues encountered
- None.

### Status
Phase 4 complete. All 13 SETUP.md §10 checklist items shipped.

## 2026-05-16 — Weekend prototype (synthetic substrate end-to-end)

### Actions taken
- Stack decision landed: Python 3.9+, Pydantic 2, DuckDB, Metabase. CLAUDE.md stack section rewritten.
- Six-tab Pydantic-as-code schema in `schema/workbook.py` with `generate_ddl()` and a version + changelog.
- `generate.py` end-to-end: 2,000 personas sampled deterministically from `nvidia/Nemotron-Personas-India` (en_IN split). Five raw sources + deferred outcomes shipped to `raw/`.
- `identity/resolve.py`: 3-pass pipeline writing `identity/edges.duckdb` (4140 edges) and the warehouse `dim_user` / facts. Resolution stats: 78.35% high-conf / 20.15% medium / 1.5% low / 200 blocked.
- `metrics/definitions.py` + `test_metrics.py`: four metric functions + 12 passing tests, every metric returning typed `MetricResult` with definition_version, is_complete, computation_sql.
- `load_metrics_to_db.py` materializes metrics to `metric_results` for Metabase. Built-in audit rejects inline metric SQL outside `metrics/`.
- `docker-compose.yml`: Metabase + DuckDB JDBC driver mount. Four dashboard questions specified inline.
- `bonus/experiment_loop.py`: rule-based loop reads `ghost_rate` from the metric layer, detects the +10.93pp spike vs hardcoded prior baseline, writes proposal JSON + Notion md + appends an `experiment_proposed` event to `raw/agent_actions.ndjson`.
- `POSITION_PAPER.md`: 1007 words. Three brief §6 questions answered + one added (typed freshness on model-derived attributes).
- `verify_failure_modes.py`: all 4/4 checks PASS — determinism, defined-once rule, deferred join (Δ=5d), shared-device anti-merge (200/200).

### Files modified
- `requirements.txt`, `Makefile`, `.gitignore`, `.claude/CLAUDE.md` (stack section).
- `schema/workbook.py` (+ `__init__.py`).
- `generate.py`.
- `identity/resolve.py` (+ `__init__.py`).
- `metrics/{definitions,test_metrics}.py` (+ `__init__.py`).
- `load_metrics_to_db.py`, `docker-compose.yml`.
- `bonus/experiment_loop.py` (+ `__init__.py`), `bonus/proposals/`, `bonus/notion/`.
- `verify_failure_modes.py`.
- `POSITION_PAPER.md`.
- Generated (gitignored): `data/personas.parquet`, `raw/*`, `identity/edges.duckdb`, `warehouse/indiastox.duckdb`.

### Issues encountered
- `from types import UnionType` only exists in Python 3.10+; fixed with a Python-3.9-compatible polyfill in `schema/workbook.py`.
- `python3 identity/resolve.py` (and `bonus/experiment_loop.py`) failed `import schema` / `import metrics` because `sys.path[0]` is the script's directory, not the repo root. Fixed by prepending repo root in each entry-point script.
- Initial test invariant `ghost_rate + unstop_to_participation_rate ≤ 1.0` is only true when the two metrics share a denominator; they don't (cohort vs challenge_signup). Replaced with a count-level disjoint test using breakdowns. Lesson candidate.

### Status
Weekend prototype shipped. Manual steps remaining: bring up Metabase + DuckDB driver + build four saved questions; cross-model verification on the position paper.

## 2026-05-16 — Layers A–E (eval harness, Glicko-2, typed-confidence chain, agent + proposal pipeline)

### Actions taken
- `core/confidence.py`: canonical `MetricResult` (value / confidence / sample_n / provenance / window_open / interpretation). `@tool_result` decorator rejects bare-float returns at runtime. `identity_confidence_summary()` propagates user-pool confidence into every metric using the formula `det − 0.5 × prob`.
- `schema/workbook.py`: added `agent_actions` and `proposals` tables. `metric_results` columns rebuilt to mirror the new shape (confidence, sample_n, provenance_json, window_open, interpretation).
- `generate.py`: 15% WhatsApp-dark channel — 300 personas with no Unstop row, no Klaviyo events. Channel-mix breakdown: 300 dark / 1190 trivial / 340 fuzzy / 170 shared-device (85 pairs).
- `identity/resolve.py`: dark users get `identity_confidence=1.0` + `single_source_attribution_unknown` flag; `fact_acquisition` carries a row with `touchpoint_source='whatsapp_dark'` and NULL UTMs.
- `metrics/definitions.py`: refactored to new MetricResult shape, added 6 new metrics (`dark_channel_fraction`, `channel_cac_bounds`, `brier_score`, `gyaani_graduation_rate`, `predictions_per_user`, `email_click_to_signup`).
- `metrics/skill.py`: Glicko-2 implementation (volatility-update step held constant for v1). 1,039 users with ≥ 2 closed outcomes; mean μ = 1475 with no meaningful cross-channel difference.
- `mcp/tools.py`: every tool wrapped with `@tool_result`. `ToolSession.call()` audit-logs each invocation to `agent_actions` with `result_hash` (sha256 of agent-visible fields).
- `agent/growth_agent.py`: rule-based agent answering the 10 canonical questions. Q08 correctly reports "no significant segment difference" (within Glicko-2 noise floor for 1 rating period); Q10 returns `value=None` with a wide CI and proposes a 4-week incrementality test.
- `eval/canonical_questions.yaml` + `eval/run_eval.py`: 10 questions, 8 with SQL ground truth, 1 with skill-distribution comparison, 1 (Q10) genuinely unknowable. Scoring: 0/1 accuracy + 0/1 calibration + 0/1 action = max 3 per Q, 30 total. Q10 scored fairly: agent answers "insufficient data" → accuracy=1, calibration=1, action=1.
- `bonus/experiment_loop.py` rewritten: proposal lands in `proposals/pending/<id>.yaml`, DuckDB `proposals` row inserted, the triggering `agent_actions.downstream_proposal_id` is set in the same transaction. `bonus/approve.py` (also `make approve PROPOSAL_ID=...`) moves the YAML, updates status, and logs a `proposal_approved` agent_action.
- `DEMO.md`: 5-minute Loom script with concrete commands per timestamp.
- `verify_failure_modes.py`: added FM5 (≥20% of metrics with conf < 0.8), FM6 (eval score < 28/30), FM7 (proposal pipeline end-to-end). Now 7 checks; all pass.

### Numbers (W01 after dark-channel addition)
- 2,000 personas; 1,700 Unstop rows; 8,308 backend events; 4,466 outcomes (deferred); 44,797 PostHog events; 2,518 Klaviyo events; 3,500 GA4 sessions.
- Identity resolution: high 1,632 (81.6%) / medium 344 (17.2%) / low 24 (1.2%) / blocked 170.
- Eval: **27/30** (FM6 passes — agent did NOT score 28+).
- Confidence-propagation: 6/11 metrics report confidence < 0.8 (FM5 passes).
- Proposal pipeline: lifecycle pending → approved verified end-to-end (FM7 passes).

### Files modified / added
- New: `core/`, `mcp/`, `agent/`, `eval/`, `proposals/`, `DEMO.md`, `metrics/skill.py`, `bonus/approve.py`.
- Edited: `schema/workbook.py`, `generate.py`, `identity/resolve.py`, `metrics/definitions.py`, `load_metrics_to_db.py`, `bonus/experiment_loop.py`, `verify_failure_modes.py`, `Makefile`.

### Issues encountered
- `is_complete` was renamed to `window_open` (opposite semantics). `load_metrics_to_db.py` and the `metric_results` schema both had to migrate. Caught by an `AttributeError` on the first end-to-end run.
- `ghost_rate` breakdowns key drift: per-source rows used `rate` after the refactor, but `load_metrics_to_db.py` still read `ghost_rate`. Bug caught immediately at end-to-end.
- FM2 false-positive on `eval/canonical_questions.yaml`: independent SQL is intentional for ground truth. Added an `is_relative_to(REPO/'eval')` exemption to the check.
- Q03 / Q04 are 1pp off between agent and YAML SQL despite identical CTE shape — likely a TZ-handling difference between parameterized timestamps and string-literal timestamps in DuckDB. The eval catches this as `accuracy=0` on those questions; the lesson is that "defined once" in code can still drift if parameter encoding differs.

### Status
Layers A–E shipped. All 7 failure-mode checks pass; 12/12 metric tests pass; 27/30 eval score. Manual Metabase bring-up still pending.

## 2026-05-16 — Layers F–I (eval-loop closure, CS agent, metric versioning, evidence-based paper)

### Actions taken
- `core/confidence.py`: added `metric_version` + `definition_hash` fields to MetricResult and the `@versioned("1.0.0")` decorator that stamps them at runtime. `VERSION_REGISTRY` populates at import time from `inspect.getsource()` hash.
- `core/version_registry.py`: registers every metric in DuckDB's `metric_versions` ledger on each pipeline run; deprecates prior versions on hash drift and prints a `WARN` line. Idempotent.
- `schema/workbook.py`: added `metric_versions` table (metric_name, version, definition_hash, deployed_at, deprecated_at, breaking_change, change_note).
- `metrics/definitions.py` + `metrics/skill.py`: applied `@versioned("1.0.0")` to all 11 tools. The `make resolve` step now writes the ledger automatically.
- `bonus/reproduce.py` + `make reproduce PROPOSAL_ID=...`: replays every tool call from a proposal's session. Happy path → `REPRODUCED ✓`. Drift simulation via `--force-stale-hash-for ghost_rate=<fakehash>` → `DEFINITION DRIFT` diff.
- `agent/cs_agent.py` + `interventions/` pipeline + `make cs-run` / `make cs-approve USER_ID=...`: finds the 10 most-at-risk users (phi above the 75th percentile, mu < 1500, quiet ≥ 3 days, ≥ 1 prediction) and writes personalized YAML interventions grounded in their actual tickers + outcomes. Each draft logs to `agent_actions` with tool_name=`cs_draft_intervention`.
- `agent/improvement_agent.py`: auto-triggered after every `make eval`. Reads the latest scorecard, classifies each <3/3 failure as `tool` / `reasoning` / `calibration`, writes `PROPOSED_IMPROVEMENTS.md` (human review) and `data/proposed_improvements.json` (machine-readable).
- `bonus/promote_improvement.py` + `make promote-improvement LINE=N`: accepts or rejects an improvement, logs the human decision to `agent_actions` with tool_name=`self_improvement`.
- `agent/position_paper_generator.py` + `make position-paper`: regenerates POSITION_PAPER.md from live tool calls. Cites real numbers, includes a CLAIMS section with FALSIFIABLE BY clauses, and signs with the agent session_id + the metric_version strings used.
- `verify_failure_modes.py`: added FM8 (≥ 3 of 10 CS interventions mention a specific ticker), FM9 (`make reproduce` detects simulated drift via `--force-stale-hash-for`), FM10 (POSITION_PAPER.md cites ≥ 20 numbers + CLAIMS + signature).

### Numbers (final session run)
- Eval: **27/30** (FM6 PASS — agent did NOT score 28+).
- Failure modes: **10/10 PASS**.
- Position paper: 1124 words, 86 numeric tokens, 3 CLAIMS + FALSIFIABLE BY, agent-signed.
- CS interventions: 10/10 mention a specific ticker (FM8 trivially passes).
- Metric versions registered: 11 (all at v1.0.0 today).
- Improvement loop: 3 concrete improvements proposed automatically (Q01 calibration markers, Q03/Q04 timestamp-parameter drift).

### Files modified / added
- New: `core/version_registry.py`, `bonus/reproduce.py`, `bonus/promote_improvement.py`, `bonus/cs_approve.py`, `agent/cs_agent.py`, `agent/improvement_agent.py`, `agent/position_paper_generator.py`, `interventions/`, `data/proposed_improvements.json`, `PROPOSED_IMPROVEMENTS.md`.
- Edited: `core/confidence.py`, `schema/workbook.py`, `metrics/definitions.py`, `metrics/skill.py`, `eval/run_eval.py`, `verify_failure_modes.py`, `Makefile`, `.gitignore`, `identity/resolve.py`.

### Issues encountered
- Glicko-2 with the simplified (no-volatility-update) variant drops phi faster than the brief's `phi > 300` threshold expects. Adjusted at-risk threshold to the 75th-percentile of phi in the live distribution; documented inline so the rule stays meaningful as the data evolves.
- DuckDB rejects mixing `read_only=True` and `read_only=False` connections to the same file from one process. CS Agent's prediction lookup re-uses the open write connection.
- Pandas `datetime64[us]` (returned from DuckDB) cannot compare to a tz-aware Python datetime. Strip tz before comparing.
- FM2 false-positive on `core/confidence.py` (framework code that runs SQL for the identity summary and mentions `ghost_rate` in docstrings). Added a `core/` exemption.
- FM9 initially picked up an orphan YAML left over from before `make clean`. Fixed by querying DuckDB's `proposals` table for the proposal_id instead of listing the filesystem.
- Correlation between `n_predictions_week1` and Glicko-2 mu came back as 0.020 (synthetic outcomes are random by design). The position paper says so explicitly rather than overclaiming — the substrate is honest about what the data shows, even when the brief's intuitive answer would be a higher number.

### Status
Layers F–I shipped. 10/10 failure modes pass. 12/12 metric tests pass. The eval-loop closes on itself (improvement agent fires after every `make eval`); CS Agent demonstrates the substrate works for a non-Growth archetype with zero re-architecture; metric versioning + reproduce gives the audit-six-months-later answer the brief asked for; the position paper is evidence-based and falsifiable.

## 2026-05-16 — Reviewer-feedback polish (pre-submission)

### Actions taken
- README.md rewritten: Stack section now names the actual stack (Python 3.9+, Pydantic 2, DuckDB, rapidfuzz, Metabase, pytest), points at POSITION_PAPER §Q1 for the migration story, and demotes the .claude/ scaffold to a "for the next maintainer" section at the bottom. The four brief-mandated metrics are foregrounded with a one-line invocation each.
- `agent/print_metric.py` + `make metric M=<name>`: CLI shim that prints any tool's full MetricResult (value, confidence, sample_n, provenance, window_open, interpretation, metric_version, definition_hash, audit_session). All 11 metrics callable; the four brief names work out of the box.
- `dashboard/render_panels.py` → `dashboard/PANELS.md`: four panels rendered as markdown tables from the live warehouse. Panel 1 fixed to be a strict-subsetting Unstop funnel (was leaking cross-channel signups → percentages over 100%). Panel 2 now reads from `metric_results` (the materialization) instead of recomputing `ghost_rate` inline — defined-once contract preserved at the dashboard layer.
- `dashboard/seed.py`: Metabase API script that creates four saved questions + "IndiaStox Weekly" dashboard once Metabase is up. Idempotent; reads `METABASE_URL/USER/PASS` from env or `.env`. Fails loudly with setup instructions when Metabase isn't running.
- POSITION_PAPER.md regenerated:
  - Q2 caveat softened to "I'm showing you the architecture, not validating the causal claim; the loop is the deliverable, the conclusion is yours once real outcomes flow." Stops undermining the metric on which the rest of the argument rests.
  - Q4 added — Backfill horizon stance (full <4w / predictions-only 4–12w / cold-storage-only >12w), grounded in the metric_versions ledger reasoning. Plus CLAIM 4 with FALSIFIABLE BY.
  - Stats: 4 CLAIMs, 4 FALSIFIABLE BY clauses, 100 numeric tokens, 1435 words.
- DEMO.md re-ordered: leads with the four brief-mandated metric calls + the rendered panels + the three-pass resolver; demotes the .claude/ scaffold mention to a 10-second beat at the end. The Loom now showcases the substrate first, the discipline-layer second.
- `verify_failure_modes.py` tightened:
  - FM2 exemption list extended for `dashboard/` (reads `metric_results`) and `DEMO.md` (script with example SQL, not metric recomputation).
  - FM7 now queries DuckDB for the freshly-created proposal instead of trusting filesystem ordering (was picking up orphan YAMLs from before `make clean`).
- Final state: **10/10 failure modes pass.**

### Files modified / added
- New: `agent/print_metric.py`, `dashboard/__init__.py`, `dashboard/render_panels.py`, `dashboard/seed.py`, `dashboard/PANELS.md`.
- Edited: `README.md`, `DEMO.md`, `POSITION_PAPER.md`, `Makefile`, `agent/position_paper_generator.py`, `verify_failure_modes.py`.

### Issues encountered
- Panel 2 was silently re-computing `ghost_rate` inline via raw SQL — exactly the failure FM2 was meant to catch. FM2 surfaced it; fixed by reading from `metric_results`.
- FM7 picked up an orphan YAML in `proposals/pending/` (PROP-a5d8daf1155c) that survived an earlier `make clean` without a DuckDB row. Fixed by querying DuckDB for the just-created proposal instead.
- `make verify` runs subprocesses that rebuild the warehouse via `make resolve` — wiping `metric_results`. So Panel 2 needs `make load` to re-run after `verify`. Documented in the Makefile chain; would tighten in a future revision by making `dashboard-panels` depend on `load`.

### Status
Polish shipped. 6th commit pushed to https://github.com/abhishek5878/indiastox_agent. Repo is review-ready.

## 2026-05-16 — Session-end ritual (per SETUP Appendix C)

1. ✅ task_plan.md phase status updated; Phase 5 (Dashboard) and Phase 6 (Position paper) remain in_progress with explicit handoff notes; final Review section filled in.
2. ✅ progress.md updated (this entry).
3. ✅ lessons.md updated — see the reviewer-feedback-pass lessons section.
4. ✅ verify: 10/10 PASS.
5. ✅ Handoff: README + DEMO.md + POSITION_PAPER.md are review-grade; the two manual handoffs (Metabase bring-up, cross-model verification on the paper) are documented in task_plan.md Phase 5 and Phase 6 respectively.

The next session opens on a complete deliverable. No work is in_progress without a handoff.

## 2026-05-17 — Layers J–M (trace + critic + calibration + anti-Goodhart)

### Actions taken
- **Layer J — "Why this number?".** Added `trace: list[str]` to MetricResult. Each of the 12 metric functions now generates a 3-step natural-language trace at evaluation time. `make trace M=<name>` prints just the trace; `make metric M=<name>` shows the full MetricResult including trace. Example for ghost_rate: (1) "0.2867 because 476 of 1660 users in the all cohort made zero predictions through the W01 + 7-day window", (2) "biggest contributor: unstop (391/476 ghosts; per-source rate 28.6% over 1368 users)", (3) "confidence = 0.73 because the identity layer carries 1632 deterministic / 344 probabilistic / 24 low-confidence matches".
- **Layer K — Critic Agent.** `agent/critic_agent.py` pairs every proposal with its strongest counter-argument BEFORE a human sees it. Auto-invoked from `bonus/experiment_loop.py` so every new YAML lands with a `critique:` section embedded. The critique covers (a) acquisition impact, (b) confounders to rule out (catalogued per-metric — e.g. "exam-season seasonality" for ghost_rate), (c) reversibility cost, (d) a concrete alternative_proposal. `make critique PROPOSAL_ID=...` runs it retrospectively. The current Unstop-pause proposal (12pp expected lift) gets severity=high and a less-destructive creative-A/B alternative.
- **Layer L — Calibration curve hero image.** `assets/calibration_curve.py` renders `assets/calibration_curve.png` via matplotlib: x = predicted P(WIN) from confidence_stars (0.5–0.9), y = realized accuracy. Diagonal = perfect calibration. The synthetic data shows a flat line at ~0.45 across all five buckets, well below the diagonal — honest, expected, captioned. Embedded as the README hero. `make calibration` regenerates against the live warehouse.
- **Layer M — `metric_gameability_index`.** 12th metric. Queries `metric_versions` for distinct `definition_hash` counts per metric and reports a global max-gameability score (0 = stable, 0.5 = one redefinition, 1.0 = three+). Today reads 0.00 across 11 substantive metrics. Named, not just measured — the act of instrumenting the failure mode is the value.
- **Position paper.** Added "On Goodhart, named" paragraph + CLAIM 5 with FALSIFIABLE BY. Position paper now: 5 CLAIMs, 5 FALSIFIABLE BY, ~1630 words, agent-signed.
- **README.** Calibration curve as hero image at top; layout table now lists Critic Agent + gameability index + calibration with their `make` targets.

### Numbers
- 12 metric tools registered (was 11); FM5 still passes (6/12 = 50% below 0.8 confidence).
- All 10 failure modes pass; all 12 metric tests pass; eval still 27/30.
- Position paper: 5 CLAIMs, 5 FALSIFIABLE BY clauses, ~1630 words.

### Files modified / added
- New: `agent/critic_agent.py`, `assets/calibration_curve.py`, `assets/calibration_curve.png`.
- Edited: `core/confidence.py`, `metrics/definitions.py` (all 11 metrics gained traces; 12th added), `metrics/skill.py`, `mcp/tools.py`, `agent/print_metric.py`, `agent/position_paper_generator.py`, `bonus/experiment_loop.py` (auto-pair critic), `Makefile` (new targets: trace, critique, calibration, gameability), `README.md`, `POSITION_PAPER.md`, `verify_failure_modes.py` (FM5 enumerates 12 metrics).

### Issues encountered
- `print_metric.py` was passing default `week_of` kwarg to metrics that don't take one (`metric_gameability_index`, `email_click_to_signup`). Decorator-chain introspection wasn't walking past `@versioned`; now walks the full `__wrapped__` chain to get the real signature and filters kwargs accordingly.

### Status
Layers J–M shipped. The substrate now: explains every number in 3 steps; pairs every proposal with its counter-argument; renders the calibration curve as the README hero; instruments its own anti-Goodhart watchdog. 10/10 failure modes pass.
