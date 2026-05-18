# IndiaStox — agent-native analytics substrate

> **Live demo:** [indiastox.vercel.app](https://indiastox.vercel.app) ·
> **API:** [indiastox-api.onrender.com](https://indiastox-api.onrender.com/api/health) ·
> **Team onboarding:** [ONBOARDING.md](ONBOARDING.md)

![call calibration on W01 synthetic data](assets/calibration_curve.png)

*Call calibration on the W01 synthetic data. Realized accuracy **bends
upward** with confidence_stars (1-star ~ 36% → 5-star ~ 57%) but stays
well below the perfect-calibration diagonal. The pipeline carries a real
signal: every persona has a latent `true_skill ~ N(0, 1)` that biases
both their BULL/BEAR outcomes and their confidence_stars. The
stars→probability mapping is overconfident — the right calibration story
for a young product. `make calibration` regenerates against the live warehouse.*

A working miniature of the production analytics platform behind
IndiaStox — a consumer prediction product where every user action is
"Make a Call" (BULL or BEAR), and every call is also a market bet the
platform scores. The Gyaani reputation system collapses call accuracy
into social capital, feed weight, and discovery.

This repo is the **agent-native substrate** that backs it: one week of
synthetic IndiaStox traffic across five mock sources, end-to-end identity
resolution with typed confidence, a metric semantic layer defined exactly
once, a closed-loop proposal pipeline paired with an adversarial Critic,
an at-risk-user CS agent, and an 11-question agent eval that breaks the
build if the agent scores too high on its own work.

If you remember nothing else: **every number you see on the live console
was returned by a tool call. The same tool the LLM agent calls. The same
tool the Critic checks proposals with. The same tool the CS agent runs
interventions through.** Dashboards are a degraded read of the substrate,
not the product.

## Stack

**Python 3.9+ · Pydantic 2 · DuckDB (single-file warehouse) · FastAPI ·
Next.js 16 (App Router) · rapidfuzz (identity stitching) · pytest ·
Anthropic Claude (sonnet-4-6 for tool-use chat) · Vercel + Render free
tier.**

Decision rationale + the migration story to a warehouse-plus-serving
architecture is argued in [POSITION_PAPER §Q1](POSITION_PAPER.md). Switch
trigger: > 50M events, > 3 concurrent engineers daily, or > 5s p95 on
agent tool calls. Today: 8ms p95 on `ghost_rate`, ~85K events, one laptop.

## The live demo, in 90 seconds

1. Open **[indiastox.vercel.app](https://indiastox.vercel.app)** — the
   world is alive on arrival, sim time advances every 2.5s, KPIs auto-
   refresh, the event stream prepends new rows via WebSocket.
2. Click **"Ask the agent a real question" → /chat** — the page auto-fires
   a preset prompt on first visit. Watch Claude pick tools, parse typed
   confidence, and answer with a real number. Every tool call is audit-
   logged and visible inline.
3. Click **"See the Critic block a bad idea" → /proposals** — the pending
   proposal with the most fired confounders is elevated as a featured
   critique. Each confounder is human-labelled, hover-explained, and shown
   with live evidence. Below it: the Critic's alternative proposal.

That's the wow path. The other 6 pages are depth.

## Run it locally

```bash
pip install -r requirements.txt
make all          # personas → events → resolve → skill → load → test → eval → cs-run → position-paper
make api          # FastAPI on :8000
make ui-next      # Next.js dev on :3000 (Turbopack)
make bonus        # detects ghost-rate spike, writes a proposal
make verify       # 11/11 failure-mode checks
```

End-to-end takes ~30 seconds on a laptop. ANTHROPIC_API_KEY in `.env`
unlocks the live LLM chat surface.

## The four brief-mandated metrics (defined exactly once in `metrics/definitions.py`)

```bash
make metric M=weekly_active_posters        # weekly active callers (renamed in UI; function name stays)
make metric M=time_to_first_action         # time-to-first-call
make metric M=unstop_to_participation_rate
make metric M=ghost_rate                   # signed up but never made a call
```

Each prints a typed `MetricResult` carrying `value`, `confidence`,
`sample_n`, `provenance`, `window_open`, `interpretation`, `trace`,
`metric_version`, and `definition_hash`. The agent reads the same struct;
the audit trail records the same struct; the eval grades the same struct.
**Bare floats from tools are rejected at runtime by `@tool_result`.**

The UI surfaces all 12 metrics with humanized labels alongside their raw
function names — so a reviewer who sees "Weekly active callers" on
/proposals can read `(weekly_active_posters)` right next to it and run
`make metric M=weekly_active_posters` without ambiguity.

## "Why this number?" — every metric is a calibrated explanation

```bash
make trace M=ghost_rate
```

```
ghost_rate = 0.2867  (v1.0.0 | confidence 0.73 | n=1660)

  [1] ghost_rate = 0.2867 because 476 of 1660 users in the all cohort
      made zero calls through the W01 + 7-day window.
  [2] biggest contributor: unstop (391/476 ghosts; per-source rate
      28.6% over 1368 users).
  [3] confidence = 0.73 because the identity layer carries 1632
      deterministic / 344 probabilistic / 24 low-confidence matches
      (probabilistic share is down-weighted 0.5× in the propagation chain).
```

This is the brief's "agents must reason about confidence, not hallucinate
certainty" made operational. Every metric returns a 3-step natural-language
trace alongside the number.

## What's in the box

| Concern | Where it lives | Key contract |
|---|---|---|
| Synthetic data (5 sources + deferred outcomes) | [generate.py](generate.py) | Deterministic by `SEED=42`. Bakes in 70/20/10 identity fuzz + 15% WhatsApp-dark + 5% Klaviyo clock-skew. |
| Schema as code | [schema/workbook.py](schema/workbook.py) | Pydantic-2 models generate DuckDB DDL. `SCHEMA_VERSION` + `SCHEMA_CHANGELOG`. |
| Identity resolution (3 passes) | [identity/resolve.py](identity/resolve.py) | confidence ∈ [-1, 1], **never a boolean**. 81.6% deterministic / 17.2% probabilistic / 1.2% low / 170 blocked shared-device pairs. |
| Metric semantic layer | [metrics/definitions.py](metrics/definitions.py), [metrics/skill.py](metrics/skill.py) | 12 metrics, every one `@versioned("1.0.0")`. Glicko-2 over closed outcomes (Step 5 Illinois iteration; paper-verified). |
| Tool-callable surface | [mcp/tools.py](mcp/tools.py) | `ToolSession.call(...)` audit-logs every invocation to `agent_actions`. |
| FastAPI gateway | [api/](api/) | 14 routes across metrics / sim / proposals / identity / eval / interventions / audit / llm. SSE chat + WebSocket sim. |
| Next.js console | [frontend/](frontend/) | 9 pages mirror the API surface. Dark mode default. shadcn-style primitives. Glossary lookup humanizes every term. |
| Living World sim | [sim/world.py](sim/world.py), [sim/watchers.py](sim/watchers.py) | Process-singleton WorldState. Tick advances synthetic time; watchers fire on signal moves. |
| LLM Growth Agent | [agent/llm_growth_agent.py](agent/llm_growth_agent.py) | `claude-sonnet-4-6` with prompt-cache + tool-use. System prompt enforces "Call / Make a Call" lexicon. |
| CS Agent | [agent/cs_agent.py](agent/cs_agent.py) | 10 personalised nudges grounded in the user's actual last BULL/BEAR call. Four variants per archetype, picked by stable per-user seed. |
| Critic v2.0.0 | [agent/critic_agent.py](agent/critic_agent.py) | Runs 5 confounder checks against live data on every proposal. Each either fires with evidence or doesn't. Featured critique surfaces the worst proposal in /proposals. |
| Eval harness | [eval/canonical_questions.yaml](eval/canonical_questions.yaml), [eval/run_eval.py](eval/run_eval.py) | 11 questions, SQL ground truth, scored 0–33. FM6 fails the build if the agent scores ≥ 31. |
| Reproducibility | [bonus/reproduce.py](bonus/reproduce.py) | `make reproduce PROPOSAL_ID=...` replays every tool call from a proposal's session and verifies result hashes. |
| Proposal pipeline | [bonus/experiment_loop.py](bonus/experiment_loop.py), [bonus/approve.py](bonus/approve.py) | Closed loop: dashboard finding → YAML + DuckDB → critique → human approve → audit row. |
| Anti-Goodhart watchdog | [`metric_gameability_index`](metrics/definitions.py) | 12th metric. Three axes: definition-hash drift, source-table drift, value-outlier drift. `make gameability` |
| Calibration curve (hero) | [assets/calibration_curve.png](assets/calibration_curve.png) | Predicted P(BULL/BEAR win) vs realized accuracy by confidence bucket. `make calibration` regenerates. |
| Failure-mode harness | [verify_failure_modes.py](verify_failure_modes.py) | 11 checks. Run via `make verify`; must be 11/11 green to commit. |
| Position paper | [POSITION_PAPER.md](POSITION_PAPER.md) | Agent-written, evidence-based, with 5 FALSIFIABLE-BY claims. |
| Team onboarding | [ONBOARDING.md](ONBOARDING.md) | 12-minute read covering the 90-second tour, repo layout, the five load-bearing rules, how to add a metric, how to add an agent, deployment + free-tier caveats, complete glossary. |

## Demo

```bash
make api               # FastAPI on :8000
make ui-next           # Next.js on :3000
make llm-demo          # Real Anthropic SDK call against Q01 / Q09 / Q10
make audit             # 20-second summary of the agent_actions audit log
```

[DEMO.md](DEMO.md) is the 5-minute Loom script. It opens on the Living
World, walks the three-pass identity resolver, runs the LLM agent against
the canonical questions, fires the proposal pipeline pending→approved,
and ends on the failure-mode harness.

### The four panels — rendered, not described

![four-panel dashboard mosaic](assets/dashboard_mosaic.png)

*`make dashboard-mosaic` rebuilds this from the live warehouse. Panel 2
(channel attribution) reads from the `metric_results` materialization;
the other three read fact_* tables directly.*

### The agent's scorecard — every miss visible

![agent eval scorecard](assets/eval_scorecard.png)

*`make eval-scorecard` re-renders this from the latest run in
[`eval/results/`](eval/results/). FM6 fails the build if this score
reaches 31/33 — a system that breaks itself when it looks too good is
the worldview the brief is hiring for.*

## Deployment

Frontend deploys to Vercel (`vercel deploy --prod` from `frontend/`).
Backend deploys to Render via [`render.yaml`](render.yaml) — auto-redeploys
on push to `main`. A GitHub Actions cron in
[`.github/workflows/keep-warm.yml`](.github/workflows/keep-warm.yml) pings
`/api/health` every 12 minutes so the Render free-tier dyno never sleeps.

Free-tier caveats and the deployment recipe in full:
[ONBOARDING.md §8](ONBOARDING.md).

## Product terminology — "Make a Call"

The IndiaStox product calls the user-action surface **"Make a Call"**
with **BULL / BEAR** as the two directions. The console reflects this
everywhere a user sees a label.

The data layer (`fact_prediction`, `direction`, `prediction_made` event
kind) still uses the legacy `prediction` lexicon — a wire-protocol
decision we'll revisit at v2 to avoid breaking 41 metric tests. The LLM
agent's system prompt explicitly rewrites the legacy word to "call" in
any user-facing reply. If you're adding a new user-facing string and you
write "prediction", you're wrong.

## For the next maintainer

This repo runs under a Claude-Code-disciplined setup: there's a
`.claude/` directory carrying CLAUDE.md (rules), skills, hooks,
sub-agents, and working-memory files (`task_plan.md`, `lessons.md`,
`progress.md`). It is also the SETUP.md scaffold from the original
brief, instantiated.

That layer is the operating manual for the *next* engineer (human or
agent) who works on this. If you're just reviewing the substrate, you
can skip it. If you're going to extend the substrate, read
[`.claude/CLAUDE.md`](.claude/CLAUDE.md) and the latest entries in
[`.claude/tasks/progress.md`](.claude/tasks/progress.md).

[ONBOARDING.md](ONBOARDING.md) is the team-facing version — start there
if you've just been added to this repo.

## License

Internal. Not for redistribution.
