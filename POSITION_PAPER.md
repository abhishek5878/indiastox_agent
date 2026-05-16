# IndiaStox Weekend — Position Paper

*All numbers below are from the synthetic W01 run shipped in this repo:
2,000 personas, 5 source files, 4,140 identity edges, 1,335 weekly
active posters at the 0.70 confidence gate.*

## Q1 — Excel vs Google Sheets for Phase 1 storage

**Neither.** Both are wrong by design, and the question itself is the
failure mode. Excel and Google Sheets are presentation surfaces, not
databases. Putting the event taxonomy into a spreadsheet means giving
up four things this project explicitly cannot afford:

1. **Type contracts.** `schema/workbook.py` defines six tables × ~10
   columns each as Pydantic models — nullability, audit columns, and
   primary keys all derive from one source of truth, with DDL generated
   from the schema by `generate_ddl()`. A spreadsheet has none of this;
   a column type is a render hint, not a constraint.

2. **Versioning.** `SCHEMA_VERSION = "1.0.0"` plus `SCHEMA_CHANGELOG`
   is the migration trail. When a metric changes definition, an agent
   reading `metric_results.definition_version` knows which materialization
   it is consuming. Spreadsheet revision history shows *who* changed *what*
   but not *what the contract was before*.

3. **Re-runnability.** `make personas generate resolve load test` rebuilds
   the entire substrate deterministically in under 30 seconds. The
   determinism check (`verify_failure_modes.py`) hashes 4,140 edges across
   two runs and confirms identical output. You cannot re-run a
   spreadsheet pipeline, period.

4. **Tool-callability for agents.** The four metric functions return a
   `MetricResult` carrying `value`, `definition_version`, `is_complete`,
   `confidence_interval`, and `computation_sql`. An agent reasons about
   these. A Tableau cell does not even expose the SQL that produced it.

Phase 1 storage is **DuckDB + a code-versioned schema** — exactly what
this prototype runs on. 85,000 events across five sources, 2,000
resolved entities, four metrics, full audit log: all in 430KB of
parquet plus one DuckDB file, all on a laptop with no infra.

**Switch trigger** — to a warehouse + serving layer (Iceberg + DuckDB,
Postgres + read replicas, or ClickHouse + materialized views) — when
any one of these three breaches:

- Event volume > 50M total or > 5M/week. Current: 85K — ~600× headroom.
- ≥ 3 engineers touching the warehouse files daily.
- Agent tool-call p95 > 5s at the warehouse layer. Current `ghost_rate`:
  8ms.

The real choice is not "spreadsheet vs warehouse" — it is
"code-versioned typed substrate vs human-visible artifact." Always the
former until scale forces the split.

## Q2 — What counts as engagement on IndiaStox

A like is not engagement. A pageview is not engagement. An email open
is not engagement. None of them meet the bar this product is designed
around.

On IndiaStox, an engagement event has three signatures:

- **It carries a stake.** The user puts reputation on the line. The
  Gyaani system is the ledger of those stakes.
- **It has a downstream verdict.** The market resolves the prediction
  in days, not quarters. Every engagement event has a deferred-join
  outcome event in the same stream — modeled here as
  `fact_prediction.is_outcome_resolved`.
- **It is loop-closing.** The verdict updates the user's skill estimate,
  which updates feed prominence, which produces the next prediction.

By that standard, the engagement event set is exactly three types:

- `challenge_signup` — user enters the arena.
- `prediction_made` — stake placed. **Primary engagement event.** (W01:
  4,466 events.)
- `prediction_outcome` — verdict lands (W01: 4,466 at T+5 days).

Everything else is **traffic**: `$pageview`, `email_opened`,
`challenge_cta_clicked`. Useful for funnel debugging, useless for the
Gyaani loop. The implication is hard: the homepage view-time leaderboard
does not belong on the engagement dashboard; the prediction-outcome
funnel does. By this definition the real engagement KPI is `ghost_rate`
(W01: 0.2913), not session length.

## Q3 — Who owns the weekly Unstop drop

**Role:** Growth Ops Analyst.

**Monday 08:00 IST workflow:**

1. Pull the previous week's Unstop CSV from the shared drive (today:
   manual; target: webhook into `raw/` directly).
2. Run the validator. Pass criteria: row count ≥ 80% of the trailing
   4-week median, no nulls on `college_email` or `full_name`, identity
   confidence distribution within 2σ of the prior week (now baselineable —
   W01 high-confidence rate is 78.35%, medium 20.15%, low 1.5%).
3. `make resolve` — the resolution report posts to a Slack channel with
   the four headline numbers (active posters, time-to-first-action,
   unstop-to-participation, ghost rate).
4. Spot-check three named college cohorts manually before sign-off.
5. Sign-off lands in `audit_log.notes` as `signed_off_by=<initials>` and
   blocks downstream pipeline if absent > 4h.

**Failure mode + backup:** the Growth Ops Analyst is sick on Monday.
The Head of Growth is the named backup, with (a) shared-drive access,
(b) the one-page runbook, (c) the three named cohorts to spot-check,
and (d) a Slack template. The pipeline still runs; the *sign-off*
requires a human, and that human is named in the runbook — not
inferred. If neither is available, PagerDuty pages.

**Data handoff format:** the nine-column CSV we already accept. The
validator rejects deviations rather than silently accepting them — this
prevents Q4-class incidents (see below) where a silently widened schema
poisons downstream metrics for weeks.

## The question I would add to this list

**How do we type the FRESHNESS of model-derived user attributes — Gyaani
scores, attribution-modeled conversions, churn forecasts — so that an
agent reasoning about them knows when the number has gone stale?**

The brief is rigorous about identity confidence and modeled-number
provenance. Both correct. But there is a third axis missing: time-to-
stale. A Gyaani score from nine weeks ago is not the same input as a
Gyaani score from nine minutes ago. If a CS Agent recommends an
intervention based on a stale skill estimate, it might intervene on a
user who has already self-corrected — and the intervention itself
becomes noise in the data the agent learns from. Freshness should be a
**type**, not a convention. Every model-output column carries
`(value, model_version, as_of_ts, max_staleness_minutes)`. The agent
checks the staleness budget before consuming. One column-trio across the
substrate; it unlocks safe agent consumption of every modeled attribute
without re-asking the question per consumer.

This is the same shape of fix as typed identity confidence — and like
that one, it is cheap to ship now and expensive to retrofit later.
