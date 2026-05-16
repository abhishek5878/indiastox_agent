# IndiaStox Weekend — Position Paper

*Evidence-based. Written by Growth Agent (session `sess-30a2977709f8`) on 2026-05-16 16:28 UTC.*

*All numbers cited below come from live tool calls during this session — see the agent_actions table in `warehouse/indiastox.duckdb` for the audit trail. Metric versions referenced: channel_cac_bounds@1.0.0, dark_channel_fraction@1.0.0, get_skill_distribution@1.0.0, ghost_rate@1.0.0, gyaani_graduation_rate@1.0.0, time_to_first_action@1.0.0.*

---

## Q1 — Excel vs Google Sheets for Phase 1 storage

**Neither.** Phase 1 storage is DuckDB + a code-versioned schema. The argument is evidence-based, not preference.

This session called 6 metric tools end-to-end in under a second per call. Every call returns a typed `MetricResult` with confidence, sample_n, provenance, and a sha256 `definition_hash` — features no spreadsheet surfaces. Concretely: `ghost_rate(unstop)` returned **0.2858** (confidence 0.73) over a cohort of 1368, computed against the live warehouse with the contract that the agent reading it can verify the definition_hash today and re-verify in 6 months via `make reproduce`.

A spreadsheet cannot do this. It cannot guarantee that a number cited in a Monday workbook was computed by the *same* function tomorrow's Tuesday workbook will use. The metric_versions ledger in DuckDB makes this an enforced contract; a workbook tab makes it a hope.

**Switch trigger** (when DuckDB stops being right):
- Event volume > 50M total or > 5M/week (current: ~85K — ~600× headroom).
- Concurrent collaboration becomes a daily blocker (≥ 3 engineers daily).
- p95 agent tool-call latency > 5s (current: 8ms for ghost_rate).

**What would change my mind:** if reading 50M events from a single DuckDB file into the metric-tool path crosses the latency budget, or if concurrent writes become a contention point. Both are testable.

## Q2 — What counts as engagement on IndiaStox

**A prediction is engagement. A pageview is not. A like is not. An email open is not.**

This stance is anchored to two numbers — including one that's honest about the data's current limits:

1. The correlation between `n_predictions_week1` and Glicko-2 `mu` is **0.020** across 1039 users with at least 2 closed outcomes — essentially noise. The synthetic data does NOT yet support the brief's presumed link between activity volume and skill, because outcomes are drawn from a random distribution here. I'm calling this out, not papering over it: the *real* IndiaStox stream should reveal a correlation; if it doesn't, engagement-as-predictions has to be re-justified from first principles (loop closure, stake-bearing, deferred join) and not from correlation alone.

2. The Gyaani graduation rate (identity_confidence ≥ 0.85 AND ≥ 3 predictions) is **27.4%** of the cohort. That's the operational separation between 'acquired' and 'engaged'. A user below that threshold is acquired but not yet evaluable — their phi is too high for any action recommendation to have signal-to-noise the agent can act on.

The cliff sits between 1 and ≥ 3 predictions. Below that, the user is acquired but not yet evaluable. Above that, the user is contributing to the Gyaani ledger — the only definition that closes the prediction-outcome loop the brief describes.

**What would change my mind:** if 8-week retention turns out to be just as high for users who pageview-bounce as for users who predict ≥ 3 times, the definition is not load-bearing. That's a Q3-onwards experiment, not a Q1 one.

## Q3 — Who owns the weekly Unstop drop

**Role:** Growth Ops Analyst (named, single human accountable). Backup: Head of Growth, who has the runbook and the credentials.

This role is justified by the numbers below — without a named human, the failure modes don't get caught.

- The dark channel fraction this week is **17.6%** (292/1660 of signups). That number is the floor on attribution uncertainty, and Unstop CAC = ₹183 (₹250,000 spend / 1368 signups). WhatsApp-dark CAC is bounded: lower ₹0 (organic-quality) to upper ₹350 (paid-referral-quality). True value unknowable without attribution improvements (deep linking, opt-in referral tracking).

- Gyaani graduation rate across the cohort is **27.4%** — meaning the validator needs to catch identity-confidence distribution shifts week-over-week, because graduation is gated on `identity_confidence >= 0.85`. If next week's drop has 15% more low-confidence stitching, this number moves and no programmatic check beyond a human eye will notice.

- The median time-to-first-action is **33.4 hours**. A drop that shifts this by > 6 hours (a 20% move) is a re-classification of who the cohort actually is, not a data refresh.

**Monday 08:00 IST workflow:** validate row count vs trailing-4w median, check no NULLs on critical keys, verify identity-confidence distribution within 2σ, run `make resolve`, post the report to Slack, sign off into `audit_log.notes`.

**Failure mode + backup:** owner sick → Head of Growth runs the same pipeline. Validator rejection is the safety net (no silent acceptance of schema drift). PagerDuty pages if sign-off absent > 4h past 08:00.

**What would change my mind:** if the validator catches < 3 schema deviations per quarter for two consecutive quarters, the role is over-specified and should be merged with Growth Analytics. Reviewable on a calendar.

## The question I would add to this list

**How do we type the FRESHNESS of model-derived user attributes** — Gyaani scores, attribution-modeled conversions, churn forecasts — so an agent reasoning about them knows when the number is too stale to act on?

Today's prototype already records `definition_hash` and `as_of` on every MetricResult. Glicko-2 `mu` values (mean = 1475 across 1039 users) inherit their as_of from the moment the parquet was written. The next step is a `max_staleness_minutes` type on every model output, with the agent checking the staleness budget before consuming. One column-trio across the substrate; unlocks safe agent consumption of every modeled attribute. Cheap to ship now, expensive to retrofit.

---

## CLAIMS

**CLAIM 1.** DuckDB + a code-versioned typed schema is the correct Phase 1 substrate, at least until event volume crosses ~50M.  **FALSIFIABLE BY:** loading 50M synthetic events into the same DuckDB file and showing that a `ghost_rate(unstop)` tool call breaches the 5-second p95 budget. Until that test runs, the position stands.

**CLAIM 2.** Engagement on IndiaStox = ≥ 3 predictions per week from a user whose identity confidence is ≥ 0.85. A user below that threshold (n=391 ghosts this week) is acquired, not engaged.  **FALSIFIABLE BY:** an 8-week retention pull showing that ghost-cohort and ≥-3-predictions-cohort retention rates differ by less than 5pp. If the two cohorts retain identically, the engagement definition isn't selecting a meaningful subset.

**CLAIM 3.** Growth Ops Analyst (named human) must own the Unstop drop, with Head of Growth as named backup, because the dark fraction is 17.6% — too high to leave to automated checks alone.  **FALSIFIABLE BY:** two consecutive quarters in which the human validator catches < 3 deviations. At that point automation has subsumed the work and the role consolidates into Growth Analytics.

---

*Written by Growth Agent session `sess-30a2977709f8`, referencing metric versions: channel_cac_bounds@1.0.0, dark_channel_fraction@1.0.0, get_skill_distribution@1.0.0, ghost_rate@1.0.0, gyaani_graduation_rate@1.0.0, time_to_first_action@1.0.0. Human reviewer: ____*
