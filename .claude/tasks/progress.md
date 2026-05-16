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
