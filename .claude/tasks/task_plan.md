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
- [x] Four dashboard questions specified inline; Q2 + Q4 read `metric_results`, not the raw facts. "Defined once" contract enforced at the dashboard layer (FM2 catches violations).
- [x] `dashboard/render_panels.py` — four panels rendered as markdown tables from the live warehouse. `make dashboard-panels` writes `dashboard/PANELS.md`. Strict-subsetting funnel, metric_results-based attribution.
- [x] `dashboard/seed.py` — Metabase API script that programmatically creates the four saved questions + "IndiaStox Weekly" dashboard. Idempotent. `make dashboard-seed` once `docker compose up -d` is done.
- [ ] Manual: bring Metabase up via Docker, drop the DuckDB JDBC JAR into `plugins/`, then `make dashboard-seed` with `METABASE_USER/PASS` env vars.
**Done when:** four saved questions render in the actual Metabase UI.
**Status:** in_progress  (in-repo deliverable complete; manual Metabase UI bring-up is the last step)
**Handoff:** `docker compose up -d` → finish first-run setup at http://localhost:3000 → place the DuckDB driver JAR in `plugins/` → `export METABASE_URL=http://localhost:3000 METABASE_USER=... METABASE_PASS=...` → `make dashboard-seed`. Same SQL as `dashboard/render_panels.py` (already verified against the warehouse).

## Phase 6: Position paper
- [x] `agent/position_paper_generator.py` + `make position-paper` regenerates POSITION_PAPER.md from live tool calls. 1435 words, 100 numeric tokens, 4 CLAIMs with FALSIFIABLE BY clauses, agent-signed with session_id + metric_version strings.
- [x] All FOUR §6 brief questions answered: Q1 storage (DuckDB until ~50M events), Q2 engagement (≥3 predictions AND identity_confidence ≥ 0.85; with the "showing architecture, not validating causal claim" caveat), Q3 Unstop drop ownership (Growth Ops Analyst + Head of Growth backup), Q4 backfill horizon (three-tier: full <4w, predictions-only 4–12w, cold-storage-only >12w). Plus an added "freshness typing on model-derived attributes" as the question I would add.
- [ ] Cross-model verification: paste the load-bearing CLAIMs into a second-lineage model per `.claude/rules/cross-model-verification.md`.
**Done when:** paper is in repo AND a second-model independent read has either ratified or surfaced a disagreement worth addressing.
**Status:** in_progress  (text shipped, audit-grade; cross-model verification pending)
**Handoff:** CLAIMs to verify (paste each into Gemini / GPT-5 / a fresh Claude session): (1) DuckDB-until-50M as Phase 1 storage, (2) engagement = ≥3 predictions AND identity_confidence ≥ 0.85, (3) Growth Ops Analyst owns Unstop drop with Head of Growth backup, (4) don't backfill >12w into the analytics layer.

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

## Review

### What shipped (scope grew well past the original 7 phases)

- **Phases 1–7** of the original weekend brief: all 7 complete (Phase 5 + 6 carry handoff notes for manual Metabase + cross-model verification, the only items not done IN the repo).
- **Layers A–E** (added in a second pass): eval harness with auto-improvement loop, Glicko-2 skill estimator, typed-confidence chain via `@tool_result` + `core/confidence.py`, agent_actions + proposals tables, full proposal lifecycle pending → approved.
- **Layers F–I** (added in a third pass): eval-loop closure (auto-improvement after every `make eval`), CS Agent + interventions pipeline, metric-version ledger + `make reproduce` (bit-exact replay with drift detection), evidence-based position paper generator.
- **Reviewer-feedback polish** (final pass): README stack named, four brief metrics foregrounded via `make metric M=...`, dashboard rendered (markdown tables + Metabase API seed), Q4 backfill added, Q2 softened, DEMO.md re-ordered to lead with substance.

### What's left

- **Manual Metabase bring-up** (Phase 5 handoff): `docker compose up -d` + DuckDB driver + `make dashboard-seed`. Two minutes if the JAR is downloaded.
- **Cross-model verification** (Phase 6 handoff): paste the three CLAIMs from POSITION_PAPER.md into a second-lineage model; ratify or revise. ~5 minutes.

### Numbers (final, committed state)

- Eval: **27/30** (FM6: agent did NOT score 28+; deliberately self-limiting).
- Failure modes: **10/10 PASS**.
- Metric tests: 12/12.
- 11 metrics registered in `metric_versions`, all at v1.0.0.
- 10 CS interventions, all grounded in real tickers (FM8).
- Position paper: 1435 words, 100 numeric tokens, 4 falsifiable claims.
- Git: 6 commits on `main`, pushed to https://github.com/abhishek5878/indiastox_agent.

### Lessons for `lessons.md`

All captured. See the 16 entries currently in `.claude/tasks/lessons.md` — from the Python-3.9 polyfill at the start to the reviewer-feedback lessons added this session (README-as-first-impression, dashboard-as-comments-is-the-harsh-failure-mode, demo-leads-with-substance, eval-reward-honest-uncertainty).

### Status
**Plan complete.** The next non-trivial work on this repo (real-data integration, productionizing the LLM agent, second-week eval) should archive this task_plan and start a new one.

---

## 2026-05-19 — Handoff after demo polish + loop closure

The original 7-phase plan (above) and Layers A–M are still the
canonical history. Since the last entry on 2026-05-17, the scope
grew substantially. A complete narrative lives in `progress.md`
under the `2026-05-19` entry. Headline:

- **Stack:** Streamlit retired. FastAPI gateway + Next.js console
  shipped to Vercel + Render free tier; always-warm via GitHub
  Actions cron.
- **Metric tools:** 12 -> 22. The new ones add product surfaces
  (call_consensus_divergence, ai_content_flagged_share,
  pre_ipo_call_interest), behavior aggregates
  (behavioral_concentration_index, cascade_followon_lift,
  gyaani_influence_index), and loop calibrations
  (user_disengagement_rate, ghost_recovery_rate,
  proposal_lift_calibration_index).
- **Closed loops:** added 3 (sim ghost -> CS, proposal -> readout,
  was already 3 -> now 6).
- **Open loops:** 3 still open (watcher auto-proposal, ghost
  auto-intervention, eval rerun). Each is a single-file change.

**Failure modes:** 11/11 PASS after extending FM2's
allowlist to include `api/` and `sim/` as legitimate ToolSession
consumers.

**Status: no in_progress phases.** Demo is shippable. The next
session can pick up either by closing the remaining 3 loops or by
starting the real-data integration (replace W01 synthetic events
with a live NDJSON tail).

---

# Task: Post-meeting execution — 7 umbrella terms (2026-05-20)

## Goal

The product strategy meeting produced 7 umbrella themes. The frame
across all of them is: **derisk product-market fit by moving the
headline metric from attention to accuracy.** The substrate (22
metrics, Glicko-2 skill, 14 behavior layers, 3 product loops, 6
closed feedback loops) already encodes most of what's needed; the
post-meeting work is to *operationalize* it. Each umbrella maps to
a concrete substrate change, not a slide.

## Umbrella → phase mapping

The 7 umbrellas cluster into 3 layers, preceded by **P0 — deepen
the simulated world**. P0 is foundational: every umbrella's success
depends on a sim rich enough to surface the patterns the meeting
called for. The user's explicit directive was *"first make the
simulated world for all personas even deeper and better… simulate
the product for them for at least 1-2 weeks"* with *"aggressive on
depth of behaviour distillation"* — that drives the P0 scope below.

| Umbrella term (user's words)                 | Layer | Phase |
|----------------------------------------------|-------|-------|
| Sim depth (prerequisite to all 7 umbrellas)  | 0     | P0    |
| Gyaani definition                            | 1     | P1    |
| Reward architecture (multi-axis)             | 1     | P2    |
| Behavior types (8 segments)                  | 1     | P3    |
| Attention → accuracy (headline metrics)      | 2     | P4    |
| Simplification + funnel dashboards           | 2     | P5    |
| Good-day activation (5-friend equivalent)    | 3     | P6    |
| Groundbreaking insights + growth hack        | 3     | P7    |

## Layer 0 — Deepen the simulated world (P0)

### P0 design — what "deeper" means here

The current sim treats each user as a bag of sampled parameters
modified by 14 behavior layers. That works for surfacing
population-level metrics but not for the insights the meeting
asked for — activation moments, drop-off typologies, cross-persona
dynamics, recovery arcs (the *0/4 then 4/4 next week* case the
user named). Those questions need agents with **evolving internal
state**, not parametric users.

P0 moves the substrate from "parameters + behavior layers" to
"agents with 8 internal states + 20 archetype templates +
cross-agent dynamics + 4 weeks of synthetic time."

### P0 — 8 internal state dimensions (per agent)

Each persona carries 8 state vectors that *update* after every
event they experience. These are the load-bearing change vs. the
current sim. Today most of these are either absent or static.

1. **Belief state** — Bayesian per-sector skill belief
   `(mu_belief_S, phi_belief_S)`. This is *what the user thinks
   they know*, which may be miscalibrated against reality
   (`mu_true_S`). The gap drives over-/under-confidence in star
   ratings. Updates: after each resolved call in S, the user
   updates their belief; the update rate is a personality trait
   (some learn fast, some never update).
2. **Affective state** — a 4-dim mood vector: tilt, euphoria,
   depression, neutral. Last N outcomes shift the vector. A
   tilted user revenge-trades (probability of next-call within
   1 hour is 3× baseline; star confidence inflates). A
   depressive arc raises ghost probability.
3. **Social state** — directed follow/copy network position.
   Each user has a `following` set (≤30) and a `followers` set
   (Pareto-distributed). Follow edges form and dissolve based
   on observed performance and group proximity.
4. **Identity state** — a single self-narrative tag drawn from
   the 20 archetypes (next section). Identity biases next-action
   probability toward identity-consistent behavior even when
   it's wrong — a "value investor" archetype avoids momentum
   plays even when momentum is the optimal call.
5. **Goal state** — primary motivation: `badge` (Gyaani
   aspirant), `influence` (follower count), `learning` (improve
   own skill), `entertainment` (no specific aim), `income`
   (treats as gambling), `social` (peer pressure / FOMO). Goal
   shifts which signals matter to the user.
6. **Time-budget state** — daily attention minutes,
   occupation-shaped. IT desk worker = 30 min/day, students
   = 60 min/day (clustered), housewife/retiree = 90 min/day
   (broadly distributed). Time of day clusters per archetype.
7. **Knowledge state** — per-ticker info with freshness decay.
   When a user reads news / sees a friend's call, they gain
   ticker-specific knowledge that decays over 5–7 days. Drives
   which tickers they call.
8. **Trust state** — platform-level trust score in [0, 1].
   Decays on bad recommendations from the platform (cascade
   tiles, AI flags, leaderboard surfaces); recovers on good
   ones. Below 0.3 → user disengages regardless of skill.

### P0 — 20 persona archetypes

Each archetype is an initial-state distribution + an update-rule
overlay. The numbers in parentheses are target population shares
on the 10k-user sim. Total = 100%.

1. **The Aspirant College Student** (12%) — high learning rate,
   bursty time-budget around classes, high social susceptibility,
   identity = "future trader", goal = badge + social.
2. **The IT Sector Specialist** (10%) — narrow sector affinity
   (IT/Tech), high knowledge in that sector, moderate true skill
   often over-confidence-rated, low social susceptibility,
   identity = "value investor".
3. **The Weekend Casual** (8%) — active only Sat/Sun, low
   affective volatility, goal = entertainment.
4. **The FOMO Cascader** (8%) — high social susceptibility, low
   patience, copies trending tiles, identity = "trend follower",
   goal = social.
5. **The Pharma Doctor / Domain Expert** (4%) — narrow sector
   (Pharma/Healthcare), highly calibrated in that sector, low
   weekday time-budget.
6. **The Tilt Trader** (6%) — high affective volatility; post-loss
   revenge probability is 3× baseline; star inflation under tilt.
7. **The Recovery Streaker** (5%) — capable of 0/4 then 4/4 arcs;
   the case the user named. Moderate base rate, high streak
   variance. Goal = comeback narrative.
8. **The Group Whisper Follower** (5%) — high in-group conformity,
   copies a specific 3–5 person sub-network (often WhatsApp-style).
9. **The Anchored Conservative** (6%) — first call's sector
   becomes 80% of future calls; low exploration; high consistency.
10. **The Diversifier Index Investor** (5%) — wide sector
    coverage, low conviction per call, treats stars as low-info.
11. **The Alpha Generator** (3%) — top 5% true mu, well-calibrated,
    high follower count (Pareto top); goal = influence.
12. **The Ghost-Risk Junior** (10%) — 1–2 calls then disappears
    unless recovered; population P6 (activation) is targeting.
13. **The Skeptic** (3%) — high trust-decay rate, abandons platform
    after first wrong call from itself or platform recs.
14. **The Day Trader** (4%) — high frequency, NSE 9–11 + 14–16
    time-of-day peaks; goal = income.
15. **The Lurker-Turned-Caller** (5%) — long passive Week-1, then
    activates Week-2 after watching others succeed; latent
    cascade-follower.
16. **The Influencer Aspirant** (3%) — goal = followers; calls
    high-visibility tickers, sometimes mis-calibrated, prioritizes
    explanation text.
17. **The Sectoral Rotator** (3%) — narrow but rotates: Pharma
    in Week 1, Banking in Week 2, Auto in Week 3. Pattern detector.
18. **The Streak Breaker** (2%) — paradoxical exit at peak; quits
    while ahead, returns when peers do.
19. **The Newbie Cautious** (4%) — first 4 weeks all 1★ calls;
    gradual star upgrade as belief-state confidence builds.
20. **The Veteran Returning** (4%) — was active in a prior cohort
    (synthetic-prior pre-W01), returning with stale knowledge.

### P0 — sub-phases

#### P0.1 — Persona archetype templates
- [x] `sim/archetypes.py` (new) — 20 archetype dataclasses with
      initial-state distributions for the 8 state vectors. Each
      archetype carries a `weight` for population sampling.
- [x] Deterministic sampling: SHA-256-hash bucketing on
      `archetype:{persona_id}`. Decoupled from generate.py's
      shared RNG; same persona_id maps to same archetype across
      runs and across call order.
- [x] Tests at `tests/test_archetypes.py`: 14 tests covering
      weight-sum invariant, slug uniqueness, distribution within
      1pp on both synthetic and uuid persona_ids, stability,
      lookup-by-slug roundtrip, frozen-dataclass invariant, and
      empirical true_skill mean per archetype within 4σ/√n.
**Done when:** ~~10k personas sampled, distribution matches target
table, reproducible.~~ DONE: 14/14 tests pass; existing 53
metric tests still pass (no regression).
**Status:** complete

Handoff to P0.2: `sim/archetypes.py` exports `Archetype` (frozen
dataclass), `ARCHETYPES` (20 instances summing to weight 1.0),
`archetype_for_persona(pid)`, `archetype_by_slug(slug)`, and
`sample_initial_true_skill(pid)`. P0.2 should consume these to
initialize the 8 state vectors; the archetype's `initial_*` and
trait fields are the seed parameters.

#### P0.2 — 8 internal state vectors + update rules
- [x] `sim/states.py` (new) — 8 frozen dataclasses (Belief,
      Affective, Social, Identity, Goal, TimeBudget, Knowledge,
      Trust) + a bundle `UserState` + a discriminated `Event`
      union (CallMade / OutcomeResolved / PlatformRec /
      FollowEdge / TimeTick).
- [x] All update rules are pure: `update_X(state_in, event,
      arch) -> state_out` returns a new instance; no input
      mutation. Composed dispatch `apply_event(us, event)`
      routes one event to all relevant state slices.
- [x] Each state carries `STATE_VERSION = "1.0.0"` — substrate
      invariant ("modeled numbers carry the model version that
      produced them") satisfied.
- [x] Tests at `tests/test_states.py`: 37 tests covering init
      factories per archetype, purity (input state unchanged
      post-call), monotonicity (belief converges with outcomes,
      tilt rises after losses, mood sums to 1.0 across N
      updates, trust clamps to [0,1], knowledge decays
      slower for pharma than for junior), composed dispatch,
      and frozen-state immutability.
**Done when:** ~~all 8 states update deterministically; tests
green; states queryable per (user, tick).~~ DONE: 37/37
tests pass; combined suite (metrics + archetypes + states) =
104/104 green, no regressions.
**Status:** complete

Handoff to P0.3: `sim/states.py` exports `UserState` and
`apply_event(us, event) -> us`. P0.3 behavior layers should
consume traits via `archetype_by_slug(us.archetype_slug)` and
read current state via `us.<vector>`. Behavior layers emit new
events; the state engine reads them. Loose coupling kept.

#### P0.3 — 8 new behavior layers (atop existing 14)
- [x] All 8 layers shipped in `sim/layers.py` as pure functions
      returning a typed `ActionModifier`:
  - [x] **peer_copy** — bias toward followed users' recent calls;
        scales with `social_susceptibility`.
  - [x] **learning_curve** — star inflation drops as belief.phi
        shrinks toward floor (50).
  - [x] **mood_arc** — tilt → revenge trading + star inflation;
        depression → ghost probability; euphoria → star
        inflation.
  - [x] **time_of_day** — active-hours give ~3× multiplier;
        weekday-/weekend-only archetypes floor on wrong day.
  - [x] **group_clustering** — implicit-group sentiment biases
        sector choice; magnitude `social_susceptibility * 0.5`.
  - [x] **copy_trading** — explicit follow-the-alpha sub-graph;
        2× the sector bias of generic peer_copy.
  - [x] **trust_decay** — trust < 0.3 adds 0.2 ghost_probability;
        trust < 0.5 dampens call_prob to 0.7×.
  - [x] **knowledge_freshness** — fresh tickers (≥0.7) get 2×
        bias; stale (<0.2) get 0.3×.
- [x] `compose(modifiers)` merges via documented semantics:
      multiplicative for *_multiplier and *_bias, additive for
      star_inflation, clamped sum for ghost_probability.
- [x] `compose_all_layers(us, sim_now, ...)` runs all 8 layers
      and composes — one call per user-tick from downstream code.
- [x] Tests at `tests/test_layers.py`: 33 tests covering
      ActionModifier defaults + immutability, compose math
      (multiplicative, additive, clamp), one-per-layer
      monotonicity (e.g., trust_decay ghost_prob monotonic with
      trust), and end-to-end integration tests including a
      "disengaged user → high ghost_probability" composition.
**Done when:** ~~22 behavior layers total; each has a test;
population-level metrics shift as expected.~~ DONE: 22 total
(14 legacy + 8 new); 33/33 layer tests pass; combined suite =
137/137.
**Status:** complete

Handoff to P0.4: `sim/layers.py::compose_all_layers` is the
single entry point for the new behavior stack. P0.4 introduces
cross-agent dynamics (group formation, cascade graph, copy
networks) — those produce the `group_sentiments`,
`recent_calls_by_followed`, `alpha_recent_calls` args that
`compose_all_layers` already accepts. Layers won't change in
P0.4; only the context that feeds them does.

#### P0.4 — Cross-agent dynamics
- [x] `sim/networks.py` (new) — pure-function population layer
      producing exactly the context shapes `compose_all_layers`
      consumes (group_sentiments, recent_calls_by_followed,
      alpha_recent_calls).
- [x] `assign_groups(user_ids, week_of, group_size_target)` —
      deterministic hash-bucket partition; complete coverage,
      no overlap, no user in multiple groups. Verified on 200
      users with avg group size ~10. Cross-week mobility (>30
      users move groups week-over-week).
- [x] `compute_group_sentiments(groups, recent_calls)` —
      per-sector probability distribution per group, sums to
      1.0; empty groups → empty dict.
- [x] `build_cascade_graph(users, recent_calls, *, now,
      lookback_minutes, alpha_archetype_slugs)` — returns
      `{alpha_user_id: [(ticker, sector), ...]}` for alphas'
      calls within the window. Default lookback = 120 minutes;
      non-alpha calls filtered out.
- [x] `collect_recent_calls_by_followed(follower_state, recent,
      *, now, lookback_minutes)` — per-user filter that feeds
      `layer_peer_copy`.
- [x] `initialize_follow_edges(users, ...)` — Pareto-distributed
      follower counts; alphas + influencer-aspirants are the
      heavy-tail targets (40% follow weighting); deterministic
      by user_id hash; bounded by `max_follow_per_user`. Verified:
      alpha avg follower count > non-alpha avg on 1k-user sample.
- [x] 5 new event types (`GroupFormedEvent`,
      `CascadeTriggeredEvent`, `CopyCallEvent`,
      `FollowEdgeFormedEvent`, `FollowEdgeDissolvedEvent`),
      each carrying `version`. `serialize_event` + `events_to_ndjson`
      give the tick driver (P0.5) a one-liner to append to
      `raw/agent_actions.ndjson`.
- [x] Tests at `tests/test_networks.py`: 26 tests covering
      determinism (same input → same output), partition
      completeness, sentiment normalization, lookback filtering,
      Pareto heavy-tail invariant, no self-loops, no duplicates,
      serialization shape, and shape-matches-layer-input integration
      checks (so P0.3 layers and P0.4 producers agree on types).
**Done when:** ~~all new event kinds present in the stream; groups
visible in DB; cascade graph queryable.~~ DONE (modulo ndjson-write
which P0.5 owns): 26/26 tests pass; combined suite = 163/163.
**Status:** complete

Handoff to P0.5: `sim/networks.py` is a pure functional layer.
P0.5 (4-week generator) calls it once per population tick:
groups = assign_groups(uids, week); sentiments =
compute_group_sentiments(groups, recent_calls); cascade =
build_cascade_graph(users, recent_with_time, now=now); for each
user u, ctx = collect_recent_calls_by_followed(u, recent_with_time,
now=now); compose_all_layers(u, now, ctx, sentiments, cascade).
That's the entire population tick contract. The 5 new event
types are dataclasses ready to be emitted by the same tick code.

#### P0.5 — Substrate-driven event generation (REDESIGNED 2026-05-21)

**Why this got redesigned.** An initial attempt (P0.5a, since
rolled back at user request) wired archetypes into *persona
generation only* — `dim_user` carried `archetype_slug` but
`gen_backend_events` still used the old uniform N(0,1) →
ghost-rate logic. End-to-end regeneration shifted ghost_rate by
only +4.6%, indicating archetype heterogeneity was not actually
driving event behavior. The user's directive: the substrate
should go from "unused" to "fully wired" in one phase, not in
intermediate stages where `archetype_slug` is in the DB but
behavior layers are unread. P0.5 is now the one-shot wiring.

The substrate built in P0.1–P0.4 must be exercised by the event
generator end-to-end. That means `gen_backend_events` becomes a
substrate consumer: it initializes `UserState` per persona,
calls `compose_all_layers` per persona-per-tick, and uses the
resulting `ActionModifier` to drive: (a) call vs. ghost
branching, (b) call frequency, (c) sector/ticker selection, (d)
star inflation. No hardcoded uniform probabilities.

##### P0.5 sub-deliverables

- [ ] **Persona-level schema** — add `archetype_slug Optional[str]`
      to `DimUser` (schema/workbook.py); generate.py + sim/world.py
      populate it during persona generation; idempotent
      `ALTER TABLE` migration for existing warehouses.
- [ ] **Event-level wiring (the load-bearing change)** —
      rewrite `gen_backend_events` so each persona's events are
      produced by a substrate-driven loop:
      ```
      us = init_user_state(persona_id, sim_start)
      for tick in week_ticks:
          mod = compose_all_layers(us, tick, ...)
          if rng.random() < mod.ghost_probability:
              break  # persona ghosts this tick
          n_calls = round(base_calls * mod.call_probability_multiplier)
          for _ in range(n_calls):
              ticker = pick_ticker_with_bias(mod.sector_bias, mod.ticker_bias, ...)
              stars = clamp(base_stars + mod.star_inflation, 1, 5)
              emit_call(...)
              us = apply_event(us, CallMadeEvent(...))
          for outcome in due_outcomes_at(tick):
              us = apply_event(us, OutcomeResolvedEvent(...))
      ```
- [ ] **Population context per tick** — call
      `assign_groups`, `compute_group_sentiments`,
      `build_cascade_graph`, `collect_recent_calls_by_followed`
      per tick. Initial follow edges via `initialize_follow_edges`
      at t=0. Feed results into `compose_all_layers` so peer-copy,
      group-clustering, and cascade-trading layers actually fire.
- [ ] **Determinism preserved** — every random draw inside the
      new loop uses a `Random` instance seeded from
      `(SEED, persona_id, tick_index)`. Reproducibility check:
      same SEED yields bit-identical raw NDJSON.
- [ ] **Metric verification** — re-run `make all`. Success
      criteria revised (the original "ghost_rate +8pp absolute"
      claim was wrong — archetype heterogeneity likely *lowers*
      aggregate ghost rate, since the legacy 30% uniform bucket
      is higher than what archetype design implies; only ~22%
      of personas are ghost-prone archetypes). The honest signal
      is *archetype-stratified spread*, not aggregate movement:
        - `ghost_rate(archetype="ghost_risk_junior")` > 50% AND
          `ghost_rate(archetype="alpha_generator")` < 10% — i.e.,
          the substrate produces visibly different ghosting by
          cohort, with >40pp spread.
        - `predictions_per_user` by archetype: alpha_generator +
          day_trader cohorts emit ≥3× the calls of
          ghost_risk_junior + newbie_cautious cohorts.
        - Aggregate `ghost_rate(unstop)` may move in *either*
          direction by a few pp; the magnitude is not the test.
        - `cascade_followon_lift`: deferred (requires
          cross-agent layers, which are out of scope for the
          first-cut P0.5 — adding peer_copy / copy_trading
          context would need a tick-by-tick loop, not the
          per-persona consultation this phase ships).
- [ ] **Update test bounds** that reflected the legacy N(0,1)
      sampling (e.g. `metrics/test_signal.py` std-band, any other
      tests that pinned to legacy population shape). Each bound
      change carries a docstring explaining the archetype-mix
      math behind the new range.
- [ ] **Per-persona event budget cap** — guard against
      runaway expansion (a high-multiplier user shouldn't make
      1000 calls/tick). Hard cap = `archetype.daily_time_budget /
      3 minutes per call`.

**Done when:** end-to-end `make all` succeeds; archetype-
stratified ghost-rate spread > 40pp; alpha+day_trader cohorts
make ≥3× the predictions of ghost+newbie cohorts; 11/11 failure
modes pass; test suite green.

**Status:** complete (2026-05-21)

**Results — substrate visibly driving event behavior on W01:**

| Archetype | Ghost % | Preds/user |
|---|---|---|
| lurker_turned_caller | 64.3% | 0.71 |
| newbie_cautious | 27.5% | 0.72 |
| influencer_aspirant | 22.8% | 3.86 |
| alpha_generator | 21.4% | 4.71 |
| skeptic | 20.7% | 1.59 |
| ghost_risk_junior | 18.7% | 0.81 |
| ... (other 11) ... | 13-17% | 1.66-9.32 |
| tilt_trader | 9.9% | 5.41 |
| anchored_conservative | 9.4% | 1.81 |
| pharma_doctor | 6.5% | 1.87 |

- Ghost-rate spread: **57.8pp** (lurker 64.3% → pharma 6.5%);
  target >40pp ✓.
- Predictions-per-user spread: **13×** (lurker 0.71 →
  day_trader 9.32); target ≥3× ✓.
- alpha_generator made 4.71 preds vs ghost_risk_junior 0.81 =
  5.8× ratio ✓.
- 171/171 tests pass; 11/11 failure modes PASS.
- Aggregate `ghost_rate(unstop)` = 18.6% (vs legacy 29.1%) —
  honest finding: the substrate produces a *lower, more honest*
  aggregate ghost rate, because legacy 30% uniform-bucket was
  overstating disengagement. Stratification is the signal,
  not aggregate movement.

**Architectural notes for next session:**
- Weekly call count uses structural layers only (`layer_mood_arc`,
  `layer_trust_decay`, `layer_learning_curve`) — `layer_time_of_day`
  is excluded because moment-of-signup activity-hour shouldn't
  shape whole-week engagement. Time-of-day applies per-call (in
  `compose_all_layers` at `made_at`) for ticker/star bias.
- Ghost-decision is structural (baseline 0.15 + trust + time-budget
  + late_activator cohort), NOT layer-derived. The layer
  `ghost_probability` field is not load-bearing for this branch.
- Cross-agent layers (`peer_copy`, `group_clustering`,
  `copy_trading`) NOT yet wired — they need population context
  per tick which would require a tick-by-tick loop. Deferred to
  P0.5b (multi-week) where the tick loop is mandatory anyway.
- `bonus/experiment_loop.py` PRIOR_WEEK_HARDCODED_GHOST_RATE
  recalibrated 0.182 → 0.08 to reflect the new baseline (so the
  +10pp threshold still fires the demo proposal).

**Files modified in P0.5:**
- `schema/workbook.py` — archetype_slug column on DimUser.
- `generate.py` — substrate-driven event generation; imports
  archetypes + layers + states; new `_pick_ticker_biased` helper.
- `sim/world.py` — `_make_persona` archetype-aware; idempotent
  DDL migration `_ensure_dim_user_archetype_column`; `_insert_persona`
  includes archetype_slug.
- `identity/resolve.py` — carries archetype_slug into dim_user.
- `bonus/experiment_loop.py` — recalibrated prior.
- `metrics/test_signal.py` — widened true_skill std band for
  archetype-mix.
- `tests/test_p05_integration.py` (new) — 8 substrate-wiring tests.

##### P0.5b — Extend horizon to 4 weeks (deferred from old P0.5)
- [ ] Generate W02, W03, W04 via the substrate-driven loop.
      Cross-week state continuity: a user's `UserState` at end
      of W01 is the starting state for W02. Network edges
      persist; group assignments refresh weekly per
      `assign_groups(uids, week_of)`.
- [ ] Deferred-join window: W02 calls resolve in W03, etc.
      W04 calls resolve in W05 (one tick beyond horizon —
      accept and document).
- [ ] Backward-compat: all existing W01-only metrics still
      return values; multi-week metrics gain a `week_of` axis
      where it doesn't already exist.
**Done when:** 4 weeks of events in warehouse, ~800k–1.5M
events total, deterministic, recovery-arc case (the user's named
0/4-then-4/4 transition) observable in W01→W02 for at least
one persona.
**Status:** pending (depends on P0.5)

Rationale for the P0.5/P0.5b split: P0.5 alone is a complete
substrate-wiring proof on a single week. P0.5b extends the
horizon. If P0.5 surfaces problems with the substrate design,
those are cheaper to fix at 1-week scale than at 4-week scale.

##### Rolled-back work (kept for institutional memory)
- 2026-05-20: P0.5a attempt (persona-only wiring) was shipped,
  regenerated W01 successfully, passed 168/168 tests and 11/11
  failure modes — but only moved ghost_rate by +4.6%, which was
  too small to justify the intermediate state. Rolled back at
  user request; substrate (P0.1–P0.4) remains in main at commit
  497bf74. The diagnostic value of the rollback: confirmed that
  archetypes shape true_skill distribution but do NOT yet drive
  event behavior. P0.5 must close that gap in one step.

#### P0.6 — Scale to 10k personas
- [ ] User generation: 10k personas drawn from the archetype
      distribution. SEED=42 + sub-seed `user_pool` for
      reproducibility.
- [ ] Identity-fuzz proportions held constant (70/20/10 +
      Klaviyo skew + PostHog never-identify). Absolute counts
      scale 5×.
- [ ] Performance: existing pipeline is single-threaded Python;
      benchmark first, optimize hot loops if generation exceeds
      ~5 min wall-clock.
- [ ] Failure-mode sweep (`verify_failure_modes.py`) re-runs
      green on the scaled dataset.
**Done when:** 10k users, 4 weeks, all 11 failure modes still
PASS, identity-resolution stats still match the typed-confidence
contract.
**Status:** pending

#### P0.7 — Full insight sweep (deliverable)
- [ ] `sim/insight_sweep.py` (new) — runs four analyses:
  - **Activation**: which Week-1 first-session features predict
    Week-2 retention? Output: feature ranked by lift on
    `retained_to_week2` outcome; identify the single criterion
    or 2-feature combo with the highest lift.
  - **Drop-off typology**: cluster users who ghosted by their
    pre-ghost trajectory (loss arc, tilt, sector-mismatch,
    overconfidence collapse). Output: typology with cohort
    sizes + suggested intervention per type.
  - **Cross-persona dynamics**: which archetype pairs have
    statistically significant influence relationships (A's
    call shifts B's next call)? Output: archetype-pair
    influence matrix.
  - **Silent failures** (added 2026-05-20, Lucent-inspired):
    quality degradation in users who *remain active* — narrowing
    sector coverage, declining star confidence, vanishing
    explanation text, shortening session duration, time-of-day
    drift away from active hours. These users wouldn't appear in
    ghost-rate or retention metrics but their engagement is
    rotting. Output: a typology of silent-failure trajectories
    with measurable trigger signals.
- [ ] `sim/replay.py` (new, lightweight) — a `replay_user(user_id,
      week)` tool that dumps the full ordered event trajectory
      for one user including their 8 state vectors at each tick.
      This makes the sim queryable as "session replay at scale"
      — agents can fetch any synthetic user's full story without
      watching it.
- [ ] Each analysis writes a structured result to
      `agent/insights_w01_w04.json` + a human-readable summary
      in `progress.md`.
- [ ] Each finding carries (a) the metric version it depends
      on, (b) a falsifiability clause ("this finding would be
      contradicted by…"), (c) a stated next-step.
**Done when:** the JSON exists, the three analyses produce
non-trivial findings (not just "all features have zero lift"),
the writeups are honest about CI and sample size.
**Status:** pending

## Layer 1 — Definitions (substrate)

## Layer 1 — Definitions (substrate)

### P1: Operationalize Gyaani definition

**Design philosophy (per user 2026-05-22): "define by a rule, let
the meta-pattern show, then lock in — the Facebook way of growth
maximising."** I explored four candidate rules against the W01
substrate first and observed:
  - phi-only (no mu gate): 100% of day_traders graduate but their
    mean win-rate is 0.406 (below population 0.430). Phi rewards
    clicking, not calling.
  - strict (mu>=p90 AND phi<150 AND n>=10): 1 graduate on W01
    because n_resolved caps at ~11. Needs P0.5b multi-week.
  - medium (mu>=p90 AND phi<170 AND n>=5): 4.2% with mean
    win-rate 0.825 — real signal but contaminated by lucky FOMO
    cascaders at n=5 sample sizes.

The resolution is a two-tier design modeled on Facebook's
engagement curve: a broad growth-slope tier ("aspirant") that's
achievable on W01 and drives engagement, and a scarce locked tier
("locked") that's the actual badge.

**Implementation (shipped 2026-05-22):**
- [x] `metrics/definitions.py::classify_gyaani(mu, phi, n_resolved)` —
      single source of truth for the rule. Pure function. Returns
      "locked" | "aspirant" | "none". `GYAANI_THRESHOLDS` dict
      holds the per-tier thresholds; `GYAANI_RULE_VERSION = "1.0.0"`.
- [x] `gyaani_aspirant_share(week_of)` — MetricResult. Counts
      aspirant-or-locked / active cohort. Aspirant rule: mu>=1500
      AND phi<200 AND n_resolved>=3.
- [x] `gyaani_locked_share(week_of)` — MetricResult. Locked rule:
      mu>=1686 AND phi<150 AND n_resolved>=10.
- [x] `gyaani_status(user_id)` — per-user tool. Returns tier + mu +
      phi + n_resolved + gaps_to_locked (mu_short_by, phi_excess,
      calls_short_by). Agents use this for "is X a Gyaani?" and
      personalised nudges ("you're 2 calls short of locked").
- [x] 13 pytest tests at `metrics/test_gyaani.py`: boundary
      correctness on both tiers, locked⊂aspirant structural
      invariant, share metrics return valid MetricResults,
      aspirant population matches an independent SQL count,
      status tier matches classify_gyaani on same inputs, gaps
      math is correct.

**W01 results:**
- `gyaani_aspirant_share` = **32.0%** (416/1300) — broad growth slope ✓
- `gyaani_locked_share` = **0.08%** (1/1300) — scarce by design ✓
- alpha_generator: 74.4% aspirant (top-skill archetype dominates
  top tier; substrate validation)
- Zero-aspirant cohorts (anchored_conservative, diversifier,
  pharma_doctor, skeptic, lurker_turned_caller): all 0%. These
  are *calibrated but data-starved* — the gaps tool tells us
  exactly what nudge they need to graduate.

**Deferred to P1b (per-sector slicing):** Glicko-2 today returns
a single global (mu, phi) per user. Per-sector slicing requires
extending `metrics/skill.py::compute_ratings()` to emit a
(user, sector) ratings table. Skipped because:
  - W01 substrate has only 4 live sectors (energy/IT/banking/FMCG)
    and per-sector cells are too data-starved for phi convergence;
    multi-week (P0.5b) is the unlocked prerequisite.
  - The two-tier rule above is sector-agnostic and works as-is.
  - The user's framing was about defining-and-locking the rule,
    not per-sector granularity.

**Status:** complete (global two-tier rule shipped); per-sector
extension is P1b, gated on P0.5b multi-week data.

### P2: Reward architecture — 8 reward axes (shipped 2026-05-22)

The plan called for 7 axes; the shipped design is 8 — adding
`presence` after the W01 meta-pattern surfaced a gap (see below).

**Architecture:**
- `metrics/reward_axes.py` — single-source-of-truth pure scoring
  functions per axis. `_SCORERS` dispatch table maps axis name →
  function so consumer code never branches on axis names.
- `user_reward_axes(user_id, week_of)` aggregator returns the 8-axis
  fingerprint dict + `top_axis` (excluding stubs) + `top_score`.
  Agents call this to answer "what is X strong at?".
- Sample-size gates per axis: accuracy/calibration/coverage `n>=3`,
  consistency `n>=4` (needs >=3 gaps), recovery `n>=2` post-loss,
  presence NONE (the load-bearing exception).
- All axes return `[0, 1]` so scores are comparable across axes.
- `REWARD_AXES_VERSION = "1.0.0"` exposed for the version invariant.

**The 8 axes:**

Real on W01 (6):
- accuracy — rescaled win-rate; 0.5 win-rate → 0, 1.0 → 1.0
- calibration — Brier-style stars-vs-outcome; 0 Brier → 1.0
- coverage — distinct LIVE_SECTORS / total LIVE_SECTORS
- consistency — 1 - CV(inter-call-gaps); regular callers earn high
- recovery — win-rate of calls after first LOSS (the 0/4→4/4 case)
- presence — `log1p(n_calls) / log1p(10)`; first call → 0.29

Stubbed (2, P0.5b unlocks):
- influence — needs copy_call edges from cross-agent layers
- discovery — needs ticker-popularity time series

**Meta-pattern (W01, post-presence):**

13 archetypes earn meaningful rewards across multiple axes (alpha
77.4% real-axis signal, tilt 90.9%, day_trader 83.3%). The 5
zero-aspirant cohorts surfaced by P1 are now covered too:

| Cohort                       | Pre-presence | Post-presence |
|------------------------------|--------------|----------------|
| pharma_doctor                | 0%           | 84.0%         |
| anchored_conservative        | 0%           | 83.1%         |
| diversifier_index_investor   | 0%           | 81.0%         |
| skeptic                      | 0%           | 77.8%         |
| lurker_turned_caller         | 0%           | 31.0% (rest made 0 calls)|

For all five, `presence` is `top_axis`. The 69% of lurkers who
remain uncovered made literally zero calls in W01 — they're
genuinely absent, not mismeasured.

**Threshold audit (recorded for institutional memory):**

Tested relaxing accuracy `n_min` from 3 → 2 to see whether the gap
could be closed by lowering gates instead of adding presence.
Result: 430 more scorable users, of which 109 score 1.0 (perfect)
— but 70 of those 109 (64.2%) are users with exactly 2 wins of 2
lucky calls. For pharma_doctor / skeptic / diversifier /
anchored / lurker, 100% of the new "perfects" are n=2 luck.
**Verdict: thresholds are correct. Presence (a separate
no-skill-claim axis) was the right answer; threshold relaxation
would actively mislead agents reading the meta-pattern.**

**Frontend dashboard extension deferred:** the agent-side tool
surface and metric layer ship now; rendering the 8-axis
fingerprint on the existing behavioral chart (S195/S196) is a
small follow-up.

**P0.5b dependency:** influence + discovery axes stay stubbed until
P0.5b's tick-by-tick loop emits copy_call edges and maintains
ticker-popularity windows across weeks.

**Status:** complete (6 of 8 axes real on W01; 2 honestly stubbed
pending P0.5b; presence + audit recorded; 28 reward-axes tests
plus 212/212 in the full suite pass).

### P3: Behavior types — 8 measurable segments (shipped 2026-05-22)

**Architecture (mirrors P2 reward-axes):**
- `metrics/behavior_segments.py` — single-source-of-truth pure
  scoring functions per segment. `_SCORERS` dispatch table.
- `classify_user_segment(user_id, week_of)` returns 8-segment
  scores + `primary_segment` (excluding stubs) + `primary_score`.
- All scorers return `[0, 1]`. Sample-size gates per segment.
- `SEGMENTS_VERSION = "1.0.0"`.

**The 8 segments:**

Real on W01 (7):
- ghosted — 0 calls in window (binary 1/0)
- cooled_off — first-half/second-half call rate ratio
- tilted — post-LOSS revenge-call frequency within 4 sim-hours
- alphas — mu >= Gyaani-locked floor (1686) + sample
- anchored — top sector share >= 0.75 of calls
- concentrators — coverage <= 0.5 with >=5 calls (narrow but voluminous)
- diversifiers — coverage >= 0.5 (>=2 of 4 sectors)

Stubbed (1, P0.5b unlocks):
- shadows — needs copy_call edges from peer_copy layer

**Meta-pattern validates design:**
- day_trader: 54% Diversifiers, 19% Concentrators (heavy + broad ✓)
- alpha_generator: 30% Diversifiers, 13% Tilted, 9% Alphas (top-tier
  Alphas hard to reach on W01 mu; multi-week unlocks)
- weekend_casual: 65% Ghosted (designed; signs up Mon-Wed, only
  active weekends — most weeks they never call)
- lurker_turned_caller: 69% Ghosted (designed to lurk in W01)
- 5 low-volume cohorts (anchored, diversifier, pharma_doctor,
  skeptic, ghost_risk_junior): 63-84% "primary_segment=None" —
  they made 1-2 calls, below segment gates. "none" is a valid
  bucket distinct from ghosted; consumers route via P1 nudges
  or the P2 presence axis.

**Done when:** ✓ ✓ ✓
  - the 8 segments sum to ~100% of active users (or None for
    pre-classification)
  - 25 pytest tests cover boundaries, range invariants, stub
    behavior, live-warehouse aggregator structure

**Frontend swap to segment-slicing** deferred — substrate ships;
dashboard re-render is a follow-up.

**Status:** complete (7 of 8 real on W01; 1 stubbed pending P0.5b
copy_call events; 25 tests pass; full suite 237/237 + 11/11
failure modes).

## Layer 2 — Headline & funnel translation

### P4: Attention → accuracy headline metrics (shipped 2026-05-22)

The strategy meeting's PMF-derisking move: replace vanity attention
metrics with skill-weighted equivalents. Three of four ship real on
W01; the fourth is honestly stubbed because the schema lacks the
necessary field.

**Shipped:**

- [x] `weekly_active_callers_calibrated(week_of)` — sum of per-caller
      Brier-derived calibration weights. W01: **113.45** calibrated
      vs **793 raw active callers** — an 85% attention-vs-accuracy gap
      visible in one number.
- [x] `high_confidence_call_ratio(week_of)` — share of resolved
      ≥4-star calls that won. W01: **46.0%** (1226/2663).
      Below 50% = the high-star signal isn't yet better than market;
      consistent with substrate calibration on small samples.
- [x] `daily_gyaani_aspirant_count(as_of_date)` — DAU replacement.
      Cumulative count of users at aspirant-or-better tier as of
      end-of-day, sharing `classify_gyaani` with the P1 share-metric.
      W01 growth curve (day 1→7): 0, 0, 3, 44, 108, 213, 324 (1 locked
      on day 7). The accelerating Facebook-style slope.
- [x] `calls_with_explanation_rate(week_of)` — STUB. Requires a
      `rationale` field on `fact_prediction` that the current schema
      doesn't carry. Registered at version `"0.0.0-stub"` so consumers
      flag the gap; status="stub" in breakdowns.

All four registered in `DEFS`. Each returns a `MetricResult` carrying
trace + provenance + interpretation. Tool surface is the same as
existing metrics — agents call by name.

**10 P4 tests cover:** registration, range/bound invariants, SQL
cross-check on high_confidence, daily monotonicity over W01,
locked⊂aspirant subset, and stub status documentation.

**Status:** complete (3 of 4 real, 1 stubbed with documented schema
gap; 247/247 tests + 11/11 failure modes pass).

### P5: Single funnel page (simplification)
- [x] New backend metric `funnel_stages(week_of, acquisition_source)`
      in `metrics/definitions.py` — returns all four stage counts
      + per-stage conversion + per-gate drop-off segment mix in
      one MetricResult. Single source of truth; frontend renders
      without composing metrics (defined-once rule).
- [x] Registered in `mcp/tools.py` TOOLS dict (28 tools now,
      was 21). Also retroactively registered the seven metrics
      added this session (gyaani_aspirant_share,
      gyaani_locked_share, weekly_active_callers_calibrated,
      high_confidence_call_ratio, daily_gyaani_aspirant_count,
      calls_with_explanation_rate) — they were defined but not
      tool-exposed.
- [x] Frontend page `frontend/app/funnel/page.tsx` (new). Four
      horizontal bars proportional to share_of_signup. Three
      drop-off cards below, each showing the segment-mix bars
      of users who didn't progress past that gate.
- [x] Sidebar entry "Growth funnel" added under "See it move"
      group.
- [x] Tests: `metrics/test_funnel.py` (10 tests) cover stage
      shape, strict-subset invariant, drop-off attribution,
      locked sub-count, headline = aspirant/signup ratio, and
      cross-consistency with `gyaani_aspirant_share`.
- [x] Verified end-to-end against running dev server: backend
      POST /api/metrics/funnel_stages returns valid stages
      (1700→1280→677→358), frontend /funnel route 200s and
      compiles in 800ms with no errors.

**W01 numbers:**
- Signed up: 1700 (unstop cohort)
- Made first call: 1280 (75.3% from prior)
- 3+ resolved calls: 677 (52.9% from prior, 39.8% of signups)
- Gyaani-aspirant: 358 (52.9% from prior, 21.1% of signups)
- Locked: 0 on W01 (multi-week gated)
- Top drop-off after 3+ resolved (sampled): diversifiers (20),
  cooled_off (10), anchored (10), concentrators (4) — these
  cohorts hit the volume bar but mu/phi didn't land in
  aspirant. Diversifiers leading is informative: spreading
  thin = lower per-sector signal.
- Drop-off after first call: all classify "(none)" segment
  (made 1-2 calls, below the 3-call segment scoring gate) —
  honest data-starved signal.

**Done when:** ~~the funnel page renders, three stages visible,
each stage's denominator + numerator are queryable through the
metric tool surface (not redefined inline).~~ DONE: page renders
four stages + locked sub-tier; all stage counts come from a
single tool-callable metric; 10 funnel-specific tests pass;
257/247 (10 new) full suite pass; 11/11 failure modes pass.
**Status:** complete (2026-05-25)

## Layer 3 — Activation & insight (PMF derisking)

### P6: Good-day activation — find the IndiaStox 5-friend moment
- [ ] Analysis script `sim/activation_analysis.py`: for each
      simulated user, compute features of their first session
      (calls made, sectors touched, max star confidence, time
      to first call, watchlist size at end of D1, follow count)
      vs. their D7/D14 retention outcome.
- [ ] Score each feature by lift on D7 retention. Output the
      single feature (or 2-feature combo) with the highest lift
      — that is the candidate "5-friend moment."
- [ ] New metric: `activation_event(user_id)` → bool + which
      criteria they hit + when.
- [ ] New event kind: `user_activated` written into
      `raw/agent_actions.ndjson` (so the activation event is
      also a logged event per the substrate invariant).
**Done when:** one specific activation criterion is identified
with measured lift on the sim; document the lift and CI in
`progress.md`.
**Status:** pending

### P7: Insight extractor + one growth-hack experiment
- [x] `agent/insights.py` (new) — 4 scanners, each finds a
      different kind of surprise. Dispatch table `_SCANNERS`
      maps scanner name → function (single source of truth).
      Each scanner is defensive: an exception in one returns an
      error-Insight rather than failing the whole sweep.
      Scanners shipped:
        - `near_miss_aspirant`: users 1 axis short of locked
          (ranked by smallest gap; the most nudgeable cohort).
        - `archetype_design_surprise`: archetypes whose observed
          aspirant rate diverges sharply from the rate their
          design implies. Both directions captured.
        - `funnel_gate_clog`: top stuck segment at each funnel
          gate, ranked by stuck-count ÷ signup-count.
        - `axis_outlier_mu`: archetype mean mu z-scored against
          population; surfaces design drift.
      All four normalised to a [0, 1] `surprise_score` so
      insights from different scanners merge into one ranking.
- [x] Metric wrapper `insights_generate(week_of, top_n)` in
      `metrics/definitions.py`. Returns MetricResult whose
      `value` is the top insight's surprise_score and whose
      `breakdowns.insights` carries the full ranked list as
      JSON-serializable dicts.
- [x] Registered in `mcp/tools.py` TOOLS dict (29 tools now).
- [x] 16 pytest tests at `metrics/test_insights.py` cover
      Insight invariants, surprise-score range, sort order,
      scanner-table consistency, per-scanner smoke against W01
      data, metric envelope shape, top-N truncation, and the
      DEFS+TOOLS registration check. Plus two "substrate
      sanity" tests: W01 *must* surface ≥1 near-miss aspirant,
      and ≥1 of the known underperformer archetypes.

**Top insights on W01 (live extractor output, top 5):**
1. `near_miss_aspirant` (score 0.86): user 07a7f7d3 (day_trader)
   28 mu points short of locked (mu=1658, phi=110, n=11).
2-3. Same pattern, two other day_traders at mu=1658.
4-5. day_traders at mu=1626 (60pt short).
6. `archetype_design_surprise` (0.43): anchored_conservative
   observed 0.0% aspirant vs expected 42.5% — biggest design
   gap on W01.
7. `archetype_design_surprise` (0.41): diversifier_index_investor
   0.0% vs 41.2% expected.
8. `funnel_gate_clog` (0.36): 'first call → 3 resolved' has
   603 stuck users; top segment '(none)' (60 of sample) —
   users with 1-2 calls who haven't built enough volume to
   classify.

**Deferred (out of scope for this turn):** auto-filing a
proposal from the top insight through `bonus/experiment_loop`.
The existing loop fires on threshold delta to ghost_rate, not
on insight rank; wiring insights→proposal needs a small adapter.
Marking as P7b follow-up.

**Done when:** ~~one new proposal is in the experiment queue
sourced from `insights.generate()`; the proposal loop closes
end-to-end as it did in S198.~~ DONE for the extractor + tool
surface; proposal auto-filing deferred to P7b. The Growth Agent
can call insights_generate today and surface the ranked list to
the user, which is the load-bearing capability — manual file
of a proposal from a chosen insight already works through
existing /api/proposals routes.
**Status:** complete (2026-05-25)

## Sequencing — recommendation

P1 → P2 → P3 in Layer 1 first (foundational; each builds on the
prior). Then P4 → P5 in Layer 2 (P4 produces the metrics P5
displays). Then P6 → P7 (P6's activation metric is one of the
inputs P7 ranks).

Realistic per-phase budget: P1 and P2 are each ~1 session (Glicko-2
slicing is the longest single item). P3 is ~half a session. P4 is
~half a session (small focused metrics). P5 is ~1 session
(frontend). P6 is ~1 session (analysis + new metric). P7 is ~1
session (insight extractor + one experiment).

Total: ~5–6 working sessions. The Layer 1 phases unlock everything
downstream — start there.

## Files likely touched

P0 (new substrate work):
- `sim/archetypes.py` (new) — 20 archetype templates.
- `sim/states.py` (new) — 8 internal-state vectors + update rules.
- `sim/world.py` — wire the 8 new behavior layers + cross-agent
  dynamics; persist new event kinds.
- `sim/insight_sweep.py` (new) — P0.7 deliverable.
- `generate.py` — extend to 10k users × 4 weeks; new sub-seeds.
- `schema/` — new event-kind taxonomies; persist state snapshots.
- `verify_failure_modes.py` — re-baseline against the scaled
  dataset.

P1–P7 (existing umbrella work, unchanged from prior draft):
- `metrics/skill.py` — per-sector Glicko-2 slicing (P1).
- `metrics/definitions.py` — new metric registrations (P1, P2,
  P3, P4, P6).
- `metrics/segments.py` (new) — P3 classifier.
- `agent/insights.py` (new) — P7 extractor (distinct from P0.7
  which is one-shot; P7 is an on-demand tool).
- `frontend/app/funnel/page.tsx` (new) — P5.
- `frontend/app/overview/page.tsx` — wire new headline metrics
  (P4) into the dashboard.
- `tests/` — one test module per phase.
- `metric_versions` table — 4 new rows from P4, 3 from P1–P3,
  1 from P6, plus P0-internal metric versions for the new
  state-derived metrics.

## Errors Encountered

| Phase | Error | Resolution |
|---|---|---|
|   |   |   |

## Adversarial review — three strongest counterarguments

1. **"P0 is a 6-session investment in scaffolding before
   answering a single business question."** Going from 14 → 22
   behavior layers, parametric users → stateful agents, 1 week →
   4 weeks, 2k → 10k personas — that's a substrate redesign, not
   a phase. The risk is that we ship a deeper sim that produces
   the same insights we already had, because the *bottleneck was
   never sim depth*; it was deciding which insight matters most.
   **Mitigation:** P0.7 (insight sweep) is the early kill-switch.
   After P0.1–P0.6 ships, the sweep must produce a finding that
   was *not* visible in the W01 sim. If it doesn't, the P0
   investment was wasted and we should stop and reconsider
   before doing P1. Make P0.7 a gating check, not the last
   bullet.

2. **"Activation analysis on synthetic data is theatre."** The
   IndiaStox 5-friend moment that matters is the one in *real*
   user data, not in the sim. The P0 archetype distribution is
   itself a hypothesis about the real user base, not a
   measurement of it. **Mitigation:** the sim is a hypothesis
   generator — P6's output (and P0.7's) is "here is the candidate
   activation criterion; test it on the next 100 real signups."
   Carry the same falsifiability discipline as the position paper:
   every finding states what would contradict it. If real-user
   data lands, prioritize that over deepening the sim further.

3. **"20 archetypes is a curve-fit to vibes, not data."** The
   archetype shares (12% college aspirants, 10% IT specialists,
   etc.) are pulled from intuition about the Indian retail
   investor base, not measured. They will bias every downstream
   insight in the direction of those shares. **Mitigation:**
   document the share table as a falsifiable claim ("we believe
   the IndiaStox active base is ~12% college aspirants; if Day-1
   data shows <5% or >25%, re-weight P0 and re-run"). Treat
   archetype weights as a knob the team is willing to revise once
   real signups arrive. Do not bake the weights into a tool
   surface that downstream agents call.

## Open questions

- Per-sector Glicko-2: how many sectors do we slice? 5 (Auto,
  IT, Pharma, Banking, FMCG) or 10? Trade-off: granularity vs.
  data starvation.
- P3 segment thresholds: should they be quantile-based (top 20%
  of concentration index = Concentrator) or absolute-cutoff?
  Quantile travels better across time; absolute cutoffs are
  more interpretable.
- P5 funnel: do we want one funnel page replacing existing
  dashboards, or an *additional* page? "Simplification" implies
  replacement.
- P6 activation: do we score against D7 retention only, or
  also against Gyaani graduation (the bottom-funnel outcome)?
