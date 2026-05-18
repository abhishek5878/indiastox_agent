# Improvements plan — N1–N9 (post-weekend hardening)

*Feature-scoped variant of `task_plan.md` per `.claude/rules/planning.md`.
The weekend-prototype plan in `task_plan.md` is complete; this is the
post-review hardening pass driven by the self-audit ("where are we
lacking right now").*

## Goal

Address nine named gaps that a careful reviewer would catch. Each
improvement closes a specific honest-or-cosmetic miss; together they
turn the substrate from "structurally honest, demonstrably-tested" into
"structurally honest, **measurably-tested against real signal**".

The position-paper word count miss (1630 vs 800–1000 spec) is
**deliberately out of scope** — the user wants the substance fixes, not
the formatting walk-back.

## Execution order (decided 2026-05-18)

Front-load **P2.N1 (real signal in synthetic data) → "Pass A"** so every
downstream check runs against the better data and visualizations are
regenerated once. Then Phase 1 bugs (Pass B), Phase 2 substance (Pass C),
Phase 3 proof (Pass D), Phase 4 polish (Pass E).

Tests for each layer ship in the same commit as the layer (decided
"AS I go", not batched). ANTHROPIC_API_KEY read from env/.env with a
clear fallback when absent.

## Phases

---

### Phase 1 — Foundation fixes (bugs, no scope debate)

**P1.N2  Fix Q03/Q04 TZ-parameter drift in `_week_bounds`**
- [ ] Reproduce the 1pp delta in a focused script (compare DuckDB
      query with TZ-aware timestamp parameter vs string literal
      against `fact_acquisition.touchpoint_at`).
- [ ] Identify the root cause: TIMESTAMPTZ vs TIMESTAMP coercion.
      Likely fix: convert to TZ-naive `datetime(..., tzinfo=None)`
      before passing as parameter.
- [ ] Apply fix in `metrics/definitions.py` `_week_bounds()`.
- [ ] Re-run `make eval`. Confirm Q03 + Q04 accuracy = 1 each.
- [ ] Add **Q11** to `eval/canonical_questions.yaml` — genuinely hard,
      `ground_truth_kind: unknowable`. Candidate:
      *"Estimate the W04 retention lift of switching from Glicko-2 to
      TrueSkill on the current population."* Agent should answer
      "insufficient data; need a 4-week parallel run plus a held-out
      cohort" and score 2/3 or 3/3 by calibration alone.
- [ ] Recalibrate FM6 threshold in `verify_failure_modes.py`:
      `< 30 out of 33` instead of `< 28 out of 30`.
- **Done when:** `make eval` shows Q03=3/3, Q04=3/3, Q11 scored, total
  in range 27–29/33; FM6 still passes.

**P1.N7  Faithful Glicko-2 with volatility-update step**
- [ ] Implement Glickman-2012 Step 5 (Illinois iterative method for
      new sigma). Test on Glickman's worked example (rating 1500 with
      RD 200, three matches against 1400/1550/1700 with scores 1/0/0
      → expected new rating 1464.06, RD 151.52, vol 0.05999).
- [ ] Re-run `make skill`. Confirm phi distribution now spans 200–350
      for low-match users.
- [ ] Revert `agent/cs_agent.py` at-risk threshold to literal
      `phi > 300` (delete the 75th-percentile workaround); add a
      comment citing Glicko-2 paper.
- [ ] Re-run `make cs-run`. Confirm 10 users still surface with the
      new phi distribution.
- **Done when:** Glickman's worked example matches; CS-Agent finds
  ≥10 at-risk users at the literal `phi > 300` threshold; the
  data-fitted-threshold comment is gone.

**P1.N3  Klaviyo data-quality surfaced**
- [ ] New file `core/data_quality.py`:
    - `find_email_clock_skew()` → list of (klaviyo_profile_id, gap_seconds) where `email_opened.ts < email_sent.ts`.
    - `find_future_dated_events()` → events with timestamp > now().
    - `find_orphan_clicks()` → clicks with no corresponding send.
- [ ] Each function returns a list + writes a row to `audit_log` with
      `pipeline_stage = 'data_quality'`.
- [ ] Hooked into `identity/resolve.py` so it runs every pipeline.
- [ ] New `make data-quality` target that prints the alerts.
- [ ] Add **FM11**: at least one `audit_log` row with
      `pipeline_stage = 'data_quality'` AND
      `notes LIKE '%clock_skew%'` exists for the synthetic week.
      Without it, the pipeline silently accepted bad data and FM11
      fails the build.
- **Done when:** `make verify` shows 11/11 (or 12/12 once N6 lands);
  `make data-quality` prints the ~140 clock-skew rows + the audit
  entries.

---

### Phase 2 — Substance upgrades (substrate stops measuring noise)

**P2.N1  Real signal in synthetic data**
- [ ] Add `true_skill: float` to each persona in
      `generate.py:build_personas` (draw from `N(0, 1)` deterministic
      by `SEED+5`).
- [ ] In `gen_backend_events`, when computing the outcome for each
      prediction, compute:
        p_win = clip(0.5 + persona.true_skill * 0.08, 0.20, 0.80)
      Use this as the win-probability instead of the fixed
      `[42, 50, 8]`. (DRAW remains a small fixed share; LOSS = 1 - p_win - p_draw.)
- [ ] Add `true_skill` to `dim_user` so we can ground-truth-validate
      Glicko-2 estimates (mu should correlate with true_skill).
- [ ] Regenerate the entire pipeline end-to-end. Re-render the
      calibration curve — expect mild bend toward the diagonal for
      n≥5 users.
- [ ] Update the position paper's Q2 to drop the "synthetic outcomes
      are random by construction" caveat; replace with the actual
      correlation number measured against the new data.
- **Done when:** `corr(n_predictions, mu)` > 0.30; Brier dips below
  0.25 for the top-skill quartile; calibration curve is no longer
  flat at 0.45.

**P2.N5  Critic Agent reasons against the data**
- [ ] Refactor `agent/critic_agent.py`: each catalogued confounder
      becomes a `(name, check_function)` pair. `check_function` runs
      a tool call and returns a bool + an evidence string.
- [ ] Confounder check examples:
    - `klaviyo_deliverability_drop`: call a (new) `email_send_rate`
      metric or query `find_email_clock_skew()` count.
    - `exam_season_seasonality`: hardcoded for now (synthetic data
      doesn't carry calendar context), but the *check* runs and
      returns `unverified`.
    - `identity_resolution_drift`: query
      `metric_gameability_index()` — if non-zero, this confounder is
      actually fired.
- [ ] Severity weighting now uses the number of fired confounders,
      not just hardcoded thresholds.
- [ ] Critique output cites concrete numbers from the check, not
      hardcoded prose.
- **Done when:** running `make critique PROPOSAL_ID=...` on the
  existing ghost-rate-spike proposal produces a critique that names
  at least one *actually-fired* confounder with a concrete supporting
  number, and skips confounders the data doesn't support.

**P2.N8  metric_gameability_index gets more teeth**
- [ ] Extend `metric_gameability_index` to compute three axes:
    1. `definition_hash_drift` (existing — distinct hashes per metric).
    2. `source_table_drift`: hash the DDL of each
       upstream-source table; flag if any source has changed since
       last deploy. (Requires snapshotting DDL in a new
       `source_table_versions` table on each run.)
    3. `value_outlier_drift`: between consecutive runs of
       `metric_results`, flag any metric whose value moved more than
       3σ without a definition_hash change.
- [ ] Per-axis score 0–1; global index = max across axes (worst-case
      reporting).
- [ ] Trace lists all three axes; flagged axes named explicitly.
- [ ] Add a `source_table_versions` table to `schema/workbook.py`.
- **Done when:** the metric returns a 3-axis breakdown; at least one
  axis fires when the same pipeline is run twice (a "no change"
  baseline → 0, but a deliberate test-fixture that modifies a source
  table reports ≥ 0.5 on axis 2).

---

### Phase 3 — Proving the substrate

**P3.N4  Real LLM-driven Growth Agent (Anthropic SDK)**
- [ ] Add `anthropic` to `requirements.txt`.
- [ ] New `agent/llm_growth_agent.py`:
    - Reads `ANTHROPIC_API_KEY` from env or `.env`.
    - Model: `claude-sonnet-4-6`.
    - Tool-use loop: each tool in `mcp/tools.TOOLS` exposed as an
      Anthropic tool with the metric's docstring as description.
    - Answers Q01 (ghost rate), Q09 (dark fraction), Q10 (counterfactual
      lift) — three questions that exercise different agent skills:
      pull-a-number, surface-uncertainty, refuse-when-unknowable.
    - Prints rule-based-agent answer next to LLM-agent answer for
      side-by-side comparison.
- [ ] Prompt caching: per `core/confidence.py` CLAUDE.md rules, every
      tool description + the system prompt go in the cache (mark
      with `cache_control: ephemeral` on the second-to-last block).
- [ ] New `make llm-demo` target.
- [ ] Eval extension: add `--llm` flag to `eval/run_eval.py` that
      runs the LLM agent against all 11 questions and produces a
      separate scorecard PNG (`assets/eval_scorecard_llm.png`).
- [ ] Add FM12 (optional): assert the LLM agent's answers to Q01/Q09
      agree with the rule-based agent within tolerance — proves the
      substrate produces consistent answers across agent
      implementations.
- **Done when:** `make llm-demo` prints both agents' answers side by
  side; the LLM agent uses the typed `MetricResult` tools; `make
  eval --llm` produces a scorecard with the LLM agent's
  per-question scores.

**P3.N6  Tests for layers J–M**
- [ ] `metrics/test_trace.py`:
    - Every tool returns `trace` with exactly 3 non-empty strings.
    - Trace step 1 mentions the metric's value or a relevant count.
    - Trace step 3 mentions confidence or sample-size rationale.
- [ ] `agent/test_critic_agent.py`:
    - 12pp-lift proposal → severity = high.
    - 3pp-lift proposal → severity = medium.
    - `alternative_proposal` is non-empty for every supported metric.
    - Confounders list is non-empty.
- [ ] `metrics/test_gameability.py`:
    - When metric_versions has all single-hash rows → index = 0.
    - When a metric has 2 hashes → drift_signal = 1, score = 0.5.
    - `flagged_count` matches the number of metrics with > 1 hash.
- [ ] `eval/test_run_eval.py`:
    - Question with numeric ground truth + agent within tolerance →
      accuracy = 1.
    - Question with numeric ground truth + agent off by > tolerance
      → accuracy = 0.
    - `ground_truth_kind: unknowable` + agent value = None →
      accuracy = 1.
    - `ground_truth_kind: unknowable` + agent value = 0.5 →
      accuracy = 0.
- [ ] `make test` runs all four new files alongside `metrics/test_metrics.py`.
- **Done when:** total test count ≥ 25 (was 12); all pass.

**P3.N9  agent_actions audit summary**
- [ ] `agent/audit_summary.py`:
    - Tool-call counts in the last 7 days by name, sorted.
    - Mean `result_confidence` per tool.
    - Proposals by status (pending / approved / executed / rejected).
    - Critique severity distribution.
    - Top 3 tool-calls by frequency, plus their median latency.
- [ ] `make audit` target → prints summary to stdout.
- [ ] DEMO.md gets a 30-second mention at the very end ("here's the
      shape of agent activity from this session").
- **Done when:** `make audit` produces a multi-section summary
  against the live `agent_actions` table; the numbers are sensible
  (tool counts > 0, mean confidences in [0,1], proposal counts
  match the directory listing).

---

### Phase 3.5 — Streamlit UI ("mother of dashboard", decided 2026-05-18)

Decision: 8 tabs, Streamlit, built after Pass D so it can include the
real LLM-driven agent chat and the live audit summary.

**P3.5  Streamlit dashboard at `ui/app.py`**
- [ ] `ui/app.py` — multi-tab Streamlit app. Reads DuckDB read-only.
- [ ] Tab 1 — **Overview**: 4 KPIs (eval score, identity high-conf %,
      ghost_rate(unstop), dark_channel_fraction) + the calibration
      curve hero + the eval scorecard heatmap inline.
- [ ] Tab 2 — **Metric explorer**: dropdown for all 12 tools, slider
      for params, renders trace + provenance + value live. Show
      definition_hash and link to current `metric_versions` row.
- [ ] Tab 3 — **Identity explorer**: search by user_id or email,
      display edges with confidence + provenance, browse the 170
      blocked-device pairs.
- [ ] Tab 4 — **Eval scorecard**: interactive heatmap; click a cell
      to see agent answer, ground truth, calibration string, action.
- [ ] Tab 5 — **Proposals + critiques inbox**: pending / approved /
      executed / rejected lists. Each card shows the Critic Agent's
      counter-argument + confounders + alternative inline. Approve
      / Reject buttons that hit DuckDB live and refresh the page.
- [ ] Tab 6 — **CS interventions feed**: 10 cards with personalized
      text, grounding facts, ticker pulls. Approve buttons.
- [ ] Tab 7 — **Live agent chat**: text input that hits the LLM
      Growth Agent (Pass D.N4). Tool calls visible in a side panel
      as they happen. Limit to 10 calls per session for cost.
- [ ] Tab 8 — **Audit trail**: agent_actions table browser, filter
      by tool_name / session_id / downstream_proposal_id. Last 7
      days by default. Charts: tool-call frequency, mean confidence,
      proposal status histogram (driven by P3.N9 audit_summary).
- [ ] `make ui` target → `streamlit run ui/app.py`.
- [ ] `requirements.txt` adds `streamlit`, `plotly`.
- [ ] Screenshot the 8 tabs into `assets/ui_*.png` and embed the
      Overview tab in the README as a second hero image.
- **Done when:** `streamlit run ui/app.py` opens, all 8 tabs render
  without errors, and approve/reject buttons in Tab 5 actually
  mutate DuckDB.

### Phase 4 — Verification & demo polish

- [ ] Full clean `make all` from scratch with the new data signal.
- [ ] Regenerate all three visualizations from the new (signal-bearing)
      data — calibration curve should now bend slightly; mosaic + scorecard
      reflect new eval (probably 28/33 with Q11 added).
- [ ] Update README hero captions to reference the new numbers.
- [ ] Update DEMO.md to fit the new score and Q11; mention the LLM
      agent demo.
- [ ] Scaffold sync: `progress.md` entry; `lessons.md` adds the
      lessons from this hardening pass (Glicko-2 worked-example
      verification, TZ parameter encoding caveats, real-signal
      synthetic data as a debugging multiplier).
- [ ] Commit + push.
- [ ] Remind user about cross-model verification — still pending on
      the position paper's 5 CLAIMs.

## Files likely touched

- `metrics/definitions.py` (P1.N2, P2.N1 side-effect, P2.N8)
- `metrics/skill.py` (P1.N7, P2.N1)
- `agent/cs_agent.py` (P1.N7)
- `agent/critic_agent.py` (P2.N5)
- `agent/llm_growth_agent.py` (NEW — P3.N4)
- `agent/audit_summary.py` (NEW — P3.N9)
- `core/data_quality.py` (NEW — P1.N3)
- `eval/canonical_questions.yaml` (P1.N2 Q11)
- `eval/run_eval.py` (P3.N4 --llm flag)
- `schema/workbook.py` (P2.N8 source_table_versions)
- `generate.py` (P2.N1)
- `identity/resolve.py` (P1.N3 hook)
- `verify_failure_modes.py` (P1.N2 FM6 threshold, P1.N3 FM11)
- `requirements.txt` (P3.N4 anthropic)
- `Makefile` (multiple targets)
- New test files: `agent/test_critic_agent.py`, `metrics/test_trace.py`,
  `metrics/test_gameability.py`, `eval/test_run_eval.py`
- `assets/eval_scorecard.py` (regenerates after Q11)
- `assets/calibration_curve.py` (re-renders after signal addition)
- `README.md`, `DEMO.md`, `POSITION_PAPER.md` (regenerate after data)
- `.claude/tasks/progress.md`, `.claude/tasks/lessons.md` (scaffold sync)

## Errors Encountered

| Phase | Error | Resolution |
|---|---|---|
|   |   |   |

## Adversarial review (three counterarguments)

**1. Adding real signal to the data is a mistake — the substrate is
honest BECAUSE the data has no signal.** Today the position paper
proudly notes that engagement-vs-skill correlation is 0.020 because
outcomes are random; adding signal turns the substrate from a
demonstrated honest-architecture story into "look, the agent works."
**Counter to the counter:** real signal lets the substrate
demonstrate its load-bearing claims (calibration curve bending,
skill curve clustering, Critic Agent firing real confounders). The
honesty story doesn't go away — it shifts from "we surfaced the
limitation" to "we surfaced both the limitation AND the working
mechanism."

**2. The LLM-agent addition (N4) is real spend with marginal
demonstration value.** Three API calls cost ₹2–3 but the rule-based
agent already proves the substrate is structured for an LLM. The
substantive engineering is the typed-confidence + tool-result
contract, which the LLM-agent demos *use* but don't *prove*.
**Counter to the counter:** every reviewer who sees a rule-based agent
asks "but does it work with a real LLM?" Closing that question with
3 calls + 1 PNG is the cheapest possible way to remove the doubt.

**3. Phase 2 (substance upgrades) is too much work for marginal
reviewer impact relative to the simpler Phase 1.** Fixing Q03/Q04,
Glicko-2 volatility, and Klaviyo data-quality together get to "no
known unfixed bugs." That's already a strong outcome; spending the
extra day on signal-injection + critic reasoning is over-engineering
for a weekend submission. **Counter to the counter:** the user said
"we have time." If we have time, Phase 2 closes the gap between
"impressive prototype" and "would survive its own first month in
production." The signal-bearing data unblocks the calibration curve
and skill-distribution stories that the README currently has to
caveat.

## Open questions

- After N1 (real signal), will the Critic Agent severity logic still
  work without modification, or do the thresholds need adjustment?
  (Anticipated: thresholds will need a one-line tune.)
- The new Q11 (TrueSkill counterfactual) might be too contrived — if
  it's obviously bad, swap for a more natural unknowable. Defer the
  exact wording to draft time.
- Cross-model verification on the position paper's 5 CLAIMs remains
  the user's call to make.
