# Task: Weekend prototype — analytics substrate in miniature

## Goal

Ship the IndiaStox weekend-brief prototype (per `IndiaStox_Agent_Native_Analytics_Brief.md` §4): a 48-hour working miniature of the production analytics platform, on synthetic data we generate ourselves. One week of synthetic Indiastox traffic (~2k users) across five mock sources, with deliberate identity-graph fuzz (70% clean / 30% needing fuzzy stitching), the weekly-challenge-signup → challenge-participation deferred-join pattern, and five artifacts: a versioned workbook schema, a confidence-scored identity-resolution step, a metric semantic layer with the four required metrics defined exactly once, a Metabase (or Superset) dashboard wired to those metrics, and a one-page position paper on three open questions.

## Phase 1: Pick the stack
- [x] Storage shape: **DuckDB + Pydantic schema-as-code** for Phase 1; migration story to warehouse + serving in POSITION_PAPER.md §Q1.
- [x] Language: Python 3.9+, `from __future__ import annotations`. CLAUDE.md stack section updated.
- [x] Dashboard tool: Metabase via Docker (DuckDB JDBC driver). docker-compose.yml shipped.
**Done when:** `CLAUDE.md` stack section has no `TBD` lines; the four metrics return numbers end-to-end.
**Status:** complete

## Phase 2: Synthetic data generator
- [x] `generate.py` deterministic with `SEED = 42`. Sub-seeds per stream (personas, devices, predictions, etc.) prevent cross-stream coupling.
- [x] Five sources: unstop_week01.csv, backend_events.ndjson, posthog_events.ndjson, klaviyo_events.ndjson, ga4_sessions.ndjson.
- [x] Identity fuzz exactly as spec'd: 70% trivial (1400), 20% fuzzy (400), 10% shared-device (100 pairs / 200 personas). Klaviyo 5% clock-skew. PostHog 15% never-identify.
- [x] Deferred join: outcomes_week01.ndjson with resolved_at = made_at + 5 days. Earliest resolved is 2024-01-06; earliest made is 2024-01-01. Delta verified.
**Done when:** generator produces a deterministic dataset; identity fuzz rate verifiable; deferred join verified.
**Status:** complete

## Phase 3: Identity resolution with typed confidence
- [x] `identity/resolve.py` 3-pass pipeline.
- [x] Pass 1 (deterministic, conf=1.0): 1567 unstop rows / 1567 backend signups matched on local-part equality.
- [x] Pass 2 (fuzzy, conf in [0.50, 0.84]): 806 edges from rapidfuzz token_sort_ratio gated on browser_fingerprint == device_fingerprint.
- [x] Pass 3 (anti-merge, conf=-1.0): 200 blocked_shared_device edges. All 100 expected pairs verified by `verify_failure_modes.py` check 4.
- [x] Final stats — High ≥0.85: 1567 (78.35%) / Medium 0.60–0.84: 403 (20.15%) / Low <0.60: 30 (1.5%) / Blocked: 200.
**Done when:** identity edges typed end-to-end; dashboard can query by confidence band.
**Status:** complete

## Phase 4: Metric semantic layer
- [x] Four metric functions in `metrics/definitions.py`, each returning a `MetricResult` with definition_version, is_complete, confidence_interval, computation_sql.
- [x] W01 numbers: `weekly_active_posters(≥0.70)=1335`, `(≥0.85)=1059`, `time_to_first_action=33.35h`, `unstop_to_participation_rate=0.7110`, `ghost_rate(unstop)=0.2913`.
- [x] 12 pytest tests pass (3 per metric: determinism, sensitivity, logical consistency).
- [x] `load_metrics_to_db.py` materializes to `metric_results`; built-in audit rejects inline metric SQL outside `metrics/`.
**Done when:** all four metrics defined in exactly one place; tests green; metric_results queryable.
**Status:** complete

## Phase 5: Dashboard
- [x] `docker-compose.yml` for Metabase + DuckDB JDBC plugin path.
- [x] Four dashboard questions specified inline in docker-compose.yml; Q2 + Q4 read `metric_results`, not the raw facts. The "defined once" contract is enforced.
- [ ] Manual step (left for the user): bring up Metabase, load DuckDB driver, build the four saved questions.
**Done when:** four saved questions render against the synthetic data.
**Status:** in_progress  (code shipped; manual UI step pending — Metabase needs Docker)
**Handoff:** Run `docker compose up -d`, drop the DuckDB driver JAR into `plugins/`, then build the four questions per the spec in `docker-compose.yml`.

## Phase 6: Position paper
- [x] 1007 words, three brief §6 questions answered (storage, engagement definition, Unstop drop ownership) plus one added (typed freshness on model-derived attributes).
- [ ] Cross-model verification pass (per `.claude/rules/cross-model-verification.md`). Pending the user picking a second model and running the check.
**Done when:** paper is in repo and reviewed by a second model.
**Status:** in_progress  (text shipped; cross-model verification pending)

## Phase 7 (bonus): Closed-loop event
- [x] `bonus/experiment_loop.py` reads `ghost_rate("2024-W01", "unstop")` from the metric layer (no inline SQL), compares to a hardcoded prior-week baseline of 0.182, detects the +10.93pp delta (above threshold), writes the proposal JSON + Notion stand-in + an `experiment_proposed` event into the same `raw/agent_actions.ndjson` event stream the data lives in.
**Done when:** proposal event is in the same event stream as the data that produced the finding.
**Status:** complete

## Files likely touched
- `synth/generator.py` (new) — synthetic-data generator.
- `pipeline/identity.py` (new) — identity resolution with typed confidence.
- `semantic/metrics.py` (new) — metric semantic layer.
- `dashboard/` (new) — Metabase config or Superset dashboard JSON.
- `docs/position_paper.md` (new) — three answers.
- `tests/` (new) — property tests for generator, identity, metrics.
- `CLAUDE.md` — stack section filled in by Phase 1.

## Errors Encountered

| Phase | Error | Resolution |
|---|---|---|
|   |   |   |

## Adversarial review (counterarguments)

1. **The synthetic data may be too clean to test identity resolution.** If 30% fuzz is generated by a simple "swap email domain" rule, the resolution step will solve it trivially. **Mitigation:** seed the fuzz with multiple noise types (email swap, name typos, device-id reset, IP collision) so the algorithm has to actually work.

2. **Picking Postgres-only for Phase 1 may foreclose on the warehouse+serving-layer architecture we'll need at 500M events.** **Mitigation:** the position paper has to take this on directly — what's the migration story, what's the latency budget for tool-callable metrics, and at what event volume does the choice change?

3. **The metric semantic layer can drift even when defined "once" — a copy-paste in a dashboard query silently re-defines `weekly_active_posters`.** **Mitigation:** the dashboard must call the metric *by function name*, not embed the SQL. Validate this with a test that diffs the rendered SQL.

## Open questions

- Stack — see Phase 1. This is the load-bearing first decision.
- Which second model for cross-model verification on the position paper.
- Should the deferred-join pattern be modeled as a separate event table or as a self-join on the events stream?

## Review (filled at end)

- What shipped:
- What's left:
- Lessons for `lessons.md`:
