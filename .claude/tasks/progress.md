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
