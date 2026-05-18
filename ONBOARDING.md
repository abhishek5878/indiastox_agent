# IndiaStox — Team Onboarding

> One doc, no slides. Read top-to-bottom in 12 minutes and you'll know what
> this is, why it's shaped this way, where every piece lives, and how to
> evolve it without breaking the spell.

---

## 0. What this actually is

This repo is the **agent-native analytics substrate** behind IndiaStox.

The bet, in one sentence: in a product where every user action ("Make a Call",
BULL/BEAR) is also a market bet the platform scores, the analytics layer has to
be a place that agents — Growth, CS, Critic, Eval — can act through, not just a
place humans look at. So we built:

- an **event taxonomy** (append-only, schema-typed),
- an **identity graph** where confidence is a number-with-provenance (never a
  boolean),
- a **versioned metric semantic layer** (every number, one definition, one
  hash),
- a **tool surface** that exposes every metric as a function the agents call.

Dashboards are a **degraded read** of that substrate. Not the product.

If you remember nothing else from this doc: **every number you see in the
console was returned by a tool call. The same tool the LLM agent calls. The
same tool the Critic checks proposals with. The same tool the CS agent runs
interventions through.**

---

## 1. The live demo

| Surface     | URL                                          | What it shows                                                                                          |
| ----------- | -------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Frontend    | https://indiastox.vercel.app                 | Next.js console (9 pages, dark mode default). Auto-live world on `/`.                                  |
| Backend API | https://indiastox-api.onrender.com           | FastAPI gateway. `/api/health`, `/api/metrics`, `/api/sim/*`, `/api/llm/chat` SSE, `/api/sim/ws` WS.   |
| GitHub      | https://github.com/abhishek5878/indiastox_agent | Source. CI runs a keep-warm cron every 12 min so Render free-tier never sleeps.                         |

The 9-page console is grouped in the sidebar by intent:

- **See it move** — `/` Living World, `/overview`
- **Explore the substrate** — `/metrics`, `/identity`, `/audit`
- **Evaluate** — `/eval`, `/proposals`
- **Take action** — `/cs`, `/chat`

---

## 2. A 90-second tour you can give a colleague

1. **Land on `/`.** The world is alive on arrival — sim time advances every
   2.5s, KPIs auto-refresh every 4s, the event stream prepends new rows via
   WebSocket. Three orientation cards under the hero tell the visitor where to
   look next.
2. **Click "Ask the agent a real question" → `/chat`.** On first visit the
   page auto-fires "What is the week-1 ghost rate for the Unstop cohort?"
   You see Claude pick tools, parse the typed confidence, and answer with a
   real number. Every tool call is audit-logged.
3. **Click "See the Critic block a bad idea" → `/proposals`.** The pending
   proposal with the most fired confounders gets elevated as a featured
   critique. Each confounder is human-labelled, hover-explained, and shown
   with live evidence. Below it: the Critic's alternative proposal.

That's the wow path. Everything else is depth.

---

## 3. Stack at a glance

| Layer            | Tech                                | Why                                                                  |
| ---------------- | ----------------------------------- | -------------------------------------------------------------------- |
| Language         | Python 3.9+                          | `from __future__ import annotations` everywhere; system Python is 3.9.6. |
| Schema           | Pydantic 2.x                         | Single source of truth. DDL generated from models.                   |
| Warehouse        | DuckDB (file-based)                  | Phase-1 prototype. Migration story in `POSITION_PAPER.md`.           |
| Identity         | rapidfuzz                            | Name similarity; confidence is always a typed float.                 |
| Tests            | pytest                               | Mandatory for substrate logic (parsers, joins, identity, metrics).   |
| Backend          | FastAPI + uvicorn                    | REST + WebSocket + SSE gateway over the tool layer.                  |
| Frontend         | Next.js 16 (App Router, Turbopack)   | Static-prerendered pages, fetches over `NEXT_PUBLIC_API_BASE`.       |
| UI primitives    | Tailwind v4 + shadcn-style custom    | Hand-rolled; no Radix dependency on the leaf primitives.             |
| Hosting          | Vercel (frontend) + Render (backend) | Free tier; keep-warm cron keeps Render off the 15-min sleep.         |
| Anthropic SDK    | `anthropic>=0.85`                    | `claude-sonnet-4-6` with prompt-cache for the SSE chat route.        |

---

## 4. Repository layout

```
indiastox/
├── api/                  # FastAPI gateway (this is the only entry point in prod)
│   ├── main.py           # CORS, route includes, startup scrub of sim.world rows
│   ├── deps.py           # path constants, .env load
│   └── routes/           # one module per concern
│       ├── metrics.py    # GET /api/metrics + POST /api/metrics/{name}
│       ├── sim.py        # /tick /reset /state /events /kpis /ws  (Living World)
│       ├── proposals.py  # CRUD + approve/reject/execute
│       ├── identity.py   # search, edges, blocked shared-device pairs
│       ├── eval_route.py # latest eval run
│       ├── interventions.py # CS queue
│       ├── audit.py      # tool-call frequency summary
│       └── llm.py        # /api/llm/status + /api/llm/chat (SSE)
│
├── frontend/             # Next.js console (9 pages mirror the API surfaces)
│   ├── app/              # one folder per route (App Router)
│   ├── components/       # ui.tsx (Button/Card/Badge/Tooltip/HintIcon/WowCallout), sidebar.tsx
│   ├── lib/
│   │   ├── api.ts        # typed fetch wrappers + WS opener
│   │   ├── glossary.ts   # humanized labels + short/long explanations for every term
│   │   └── utils.ts      # cn() helper
│   └── public/, package.json, ...
│
├── core/                 # contracts — change carefully
│   ├── confidence.py     # MetricResult Pydantic model (typed confidence, version, trace)
│   ├── source_table_registry.py
│   └── version_registry.py
│
├── metrics/              # the semantic layer — every metric exactly once
│   ├── definitions.py    # ghost_rate, brier_score, dark_channel_fraction, ...
│   ├── skill.py          # Glicko-2 rating engine (paper-verified, Step 5 Illinois)
│   └── test_metrics.py
│
├── mcp/
│   └── tools.py          # @versioned + @tool_result wrappers + ToolSession (audit-logged)
│
├── agent/                # the agent archetypes
│   ├── llm_growth_agent.py  # Claude with tool-use, used by /api/llm/chat
│   ├── critic_agent.py      # Critic v2.0.0 — runs 5 confounder checks against live data
│   ├── cs_agent.py          # generates personalised nudges for at-risk users
│   ├── audit_summary.py     # backs /audit
│   └── position_paper_generator.py
│
├── sim/                  # the Living World — synthetic users joining/calling/ghosting
│   ├── world.py          # tick(WorldState, advance_minutes) — deterministic per seed
│   ├── watchers.py       # growth_watcher_tick + cs_watcher_tick
│   └── baseline.py       # snapshot + restore the warehouse
│
├── eval/                 # 11-question scorecard with FM6 PASS/FAIL threshold
├── identity/             # graph builder + edges.duckdb
├── bonus/                # experiment_loop, approve workflow, reproduce
├── proposals/, interventions/  # YAML inboxes (pending/approved/executed/rejected)
├── raw/                  # source NDJSONs (klaviyo, posthog, ga4, unstop, outcomes)
├── warehouse/            # indiastox.duckdb — the prototype warehouse
├── assets/               # PNG charts the /overview page embeds
├── .github/workflows/    # keep-warm.yml (cron pings /api/health every 12 min)
├── Dockerfile, render.yaml  # backend deploy
└── ONBOARDING.md         # ← you are here
```

---

## 5. The five rules everyone codes by

These are not style preferences. They are load-bearing.

### 5.1 Identity confidence is never a boolean

Every user-touchpoint match carries a confidence score AND a provenance
string. If you find yourself writing `is_match: true`, stop and write
`confidence: float, method: str` instead. The whole identity graph (see
`identity/`) is built on this — collapsing to a boolean discards the signal
that lets downstream metrics know how much to trust a join.

### 5.2 Metric definitions live in exactly one place

`metrics/definitions.py`. Dashboards call those functions; they do not
redefine them. A metric that gets redefined in a SQL snippet on the
dashboard is a bug, not a feature.

### 5.3 Modeled numbers carry the model version

Every number that came from a model (attribution, retention forecast,
identity stitching) carries the version of the model that produced it.
`MetricResult` (in `core/confidence.py`) enforces this at the type
boundary. Reasoning over a number later — was this from skill model
v1.0.0 or v1.1.0? — should be answerable without git archaeology.

### 5.4 Events are append-only and schema-typed

Including agent actions. There is **no** agent action in this codebase
that isn't also a logged event. The `agent_actions` table is the
single audit log for the LLM growth agent, the Critic, the CS agent,
and the Living World sim alike.

### 5.5 Three similar lines is better than a premature abstraction

If you're tempted to factor three near-identical functions into one
parameterised function, don't — at least not yet. The product is too
young; the cost of locking in the wrong abstraction is higher than
the cost of duplicating three lines. Revisit at five.

---

## 6. The agents — what each one does, where to find it

| Agent         | File                                | Trigger                            | What it produces                                                        |
| ------------- | ----------------------------------- | ---------------------------------- | ----------------------------------------------------------------------- |
| Growth (LLM)  | `agent/llm_growth_agent.py`         | `POST /api/llm/chat` (SSE)         | Plain-English answers grounded in tool calls. Cached prompt prefix.    |
| Critic v2.0.0 | `agent/critic_agent.py`             | Per-proposal, async                | A critique YAML with severity, counter-argument, 5 confounder checks, alternative proposal. |
| CS agent      | `agent/cs_agent.py`                 | `make cs-run`                      | One personalised intervention YAML per at-risk user (top-10 by risk_score). |
| Living World  | `sim/world.py` + `sim/watchers.py`  | Process-singleton, tick on demand  | New personas, new BULL/BEAR calls, outcome resolutions, watcher fires. |
| Eval          | `eval/run_eval.py`                  | `make eval`                        | An 11-question scorecard JSON in `data/eval/run_*.json`.               |

**Common contract:** every agent reads and writes via `mcp.tools.ToolSession`.
That session's `call(tool_name, **kwargs)` is the audit-logged entry point.
There is no other way to touch a metric.

### 6.1 The Critic's five confounders

These run as real tool calls against live data on every proposal. Each
either fires (with evidence) or doesn't:

1. **klaviyo_deliverability_drop** — scans email-pairs for opened_at <
   sent_at. Fires above 1% inversion. Catches clock-drift masquerading as
   engagement lift.
2. **prediction_market_noise_floor** — compares brier_score against the
   random-guess baseline of 0.25. Fires when the substrate is near the
   floor — any channel-side proposal is fitting noise.
3. **identity_resolution_drift** — checks metric_gameability_index. Fires
   if a metric definition or source-table hash changed mid-experiment.
4. **dark_channel_dominance** — fires when dark_channel_fraction is high
   enough to bound the proposal's reach. Attribution-side fixes are
   capped by this floor.
5. **exam_season_seasonality** — fires when the proposal's readout window
   overlaps a structural seasonal effect.

Every fired confounder gets attached to the proposal's `critique.confounder_checks`
list. The `/proposals` page renders the highest-fired-count pending proposal
as the **featured critique** at the top.

---

## 7. Local development

### 7.1 Bootstrapping

```bash
# Python deps
pip install -r requirements.txt

# Front-end deps
cd frontend && bun install && cd ..

# Bake the warehouse (one-time; ~3 min)
make personas generate resolve skill load

# .env (just one secret)
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
```

### 7.2 Running

| Command            | What it does                                                  |
| ------------------ | ------------------------------------------------------------- |
| `make api`         | uvicorn on :8000 with --reload                                |
| `make ui-next`     | Next.js dev on :3000 (Turbopack)                              |
| `make ui-build`    | Production build of the Next.js app                            |
| `make cs-run`      | Regenerate the 10 pending CS interventions                    |
| `make eval`        | Run the 11-question agent eval                                |
| `make audit ARGS="--days 7"` | Render the audit summary                              |
| `make critique PROPOSAL_ID=<id>` | Re-critique an existing proposal                |
| `make trace M=<metric>` | Print the 3-step "why this number?" trace               |
| `make verify`      | Full failure-mode verification (must pass 11/11 before commit) |
| `make baseline`    | Snapshot the warehouse to `indiastox.baseline.duckdb`         |
| `make baseline-restore` | Restore the warehouse from baseline                      |
| `make clean`       | Wipe regeneratable artifacts                                  |

### 7.3 Tests

```bash
make test                          # all metric tests (currently 41+ passing)
pytest -k brier_score              # one slice
pytest metrics/ -v --tb=short      # full metric layer
```

The discipline: **mandatory tests for substrate logic** (parsers, joins,
attribution math, identity resolution, metric definitions). **Optional for
orchestration glue.** And — never mock the database in tests that assert
join behaviour, identity resolution, or metric computation. Use a real
local DuckDB.

---

## 8. Deployment

### 8.1 Frontend (Vercel)

```bash
cd frontend
vercel deploy --prod --yes
vercel alias set <new-deployment> indiastox.vercel.app
```

`NEXT_PUBLIC_API_BASE` is baked at build time (set once via
`vercel env add NEXT_PUBLIC_API_BASE production`). Default falls back to
`http://localhost:8000` if unset.

### 8.2 Backend (Render)

Render auto-deploys on push to `main` via `render.yaml`. The Dockerfile is
a single stage: `python:3.11-slim` + `pip install -r requirements.txt` +
copy the entire repo (warehouse, raw NDJSONs, proposals, interventions
are all force-added to git for the demo build).

**Free tier caveats:**
- Sleeps after 15 min idle. The `.github/workflows/keep-warm.yml` cron
  pings `/api/health` every 12 min so this never happens.
- No persistent disk. Audit-log writes and any sim.world mutations
  are wiped on container restart — by design, see §8.4.
- 512 MB RAM, 0.1 vCPU. Watch memory on the kpis endpoint if you add
  expensive joins.

### 8.3 Vercel deployment-protection

Hobby projects default to SSO-required deployments. Disable for the
demo URL via:

```bash
curl -X PATCH "https://api.vercel.com/v9/projects/<projectId>?teamId=<teamId>" \
  -H "Authorization: Bearer $VERCEL_TOKEN" \
  -d '{"ssoProtection":null}'
```

### 8.4 Sim state is intentionally ephemeral

`api/main.py` has a `@app.on_event("startup")` hook that scrubs all
`sim.world`-sourced rows from `dim_user`, `fact_acquisition`,
`fact_prediction`, and truncates `sim_events`. This means every cold-start
gives a pristine demo world — and avoids the deterministic per-tick UUID
seeds colliding with previously-inserted rows.

---

## 9. Adding a new metric

Single source of truth: `metrics/definitions.py`. The shape is fixed.

```python
@versioned("1.0.0")
@tool_result
def my_new_metric(*, week_of: str, acquisition_source: str = "all") -> MetricResult:
    """Why this metric exists, in one sentence (the WHY, not the WHAT)."""
    con = duckdb.connect(str(WAREHOUSE), read_only=False)
    try:
        # ... your SQL ...
        return MetricResult(
            metric_name="my_new_metric",
            metric_version="my_new_metric@1.0.0",
            value=value,
            confidence=confidence,       # always a float; never a bool
            sample_n=sample_n,
            interpretation=f"{n}/{total} ({pct:.1%}) ... — explain in plain English",
            provenance=["cohort_filter:...", "cohort_size:..."],
            trace=["step1", "step2", "step3"],
        )
    finally:
        con.close()
```

Then:

1. Register the tool in `mcp/tools.py` so the LLM can call it (and the
   audit log captures it).
2. Add a glossary entry to `frontend/lib/glossary.ts` so the UI can
   humanize the metric name on hover.
3. Write a test in `metrics/test_metrics.py` that pins the value against
   the W01 baseline. **No mocks.**
4. Update the `humanizeMetric` lookups if it should appear in dashboards.

---

## 10. Adding a new agent

The contract is light: take a `ToolSession`, call tools through it, write
the resulting artefact (a YAML, a JSON, an event) to disk under the
appropriate folder (`proposals/`, `interventions/`, `eval/`). Every call
on the session is audit-logged automatically.

Skeleton:

```python
from mcp.tools import ToolSession

def run_my_agent() -> None:
    session = ToolSession()
    result = session.call("ghost_rate", week_of="2024-W01")
    # ... reason over result.value, result.confidence, result.trace ...
    # ... emit a YAML to proposals/pending/PROP-...yaml ...
```

The LLM Growth Agent (`agent/llm_growth_agent.py`) is the reference
implementation that wires this up to Anthropic tool-use. The CS Agent
(`agent/cs_agent.py`) is the reference for a deterministic, templated
agent that writes interventions.

---

## 11. The "Make a Call" terminology

The IndiaStox product uses **"Make a Call"** with **BULL / BEAR** as the
two directions. The console reflects this everywhere a user sees a
label. The data layer still uses `fact_prediction` and `direction` —
that's a wire-protocol decision we'll revisit at v2 when we have time
to migrate without rewriting tests.

Specifically:
- Sidebar nav, KPI tile labels, page headers, glossary entries, CS
  nudge templates: **call / Make a Call / BULL / BEAR**.
- Database tables, internal Python variables, event-kind strings: the
  legacy `prediction` lexicon is still there.

If you're adding a new user-facing string and you write "prediction",
you're wrong.

---

## 12. Things that are intentionally not done

These are not bugs. They are deliberate scope cuts for the Phase-1
prototype. We will revisit each in order.

- **No multi-user sessions.** The Living World sim is a process
  singleton. Two visitors share one world. Adding session-keyed worlds
  is a 1-day change but not what the demo is about.
- **No real auth.** The Vercel project disables SSO protection so the
  link is public. There is no per-user persistence.
- **No persistent disk on Render.** The warehouse is rebuilt from the
  image on every cold start. Moving to a $7/mo Starter plan + a 1GB
  disk gives us persistence without code changes.
- **No sentiment-divergence metric and no AI-content detector.** Both
  appear in the Critic's confounder-check vocabulary but no live
  implementation yet. The infrastructure for both is one metric file
  away.
- **No streaming-style chat reply.** The SSE chat returns the final
  answer in one frame after all tool calls have resolved. Token-streaming
  is an Anthropic SDK config change away.

---

## 13. The position paper

`POSITION_PAPER.md` argues the architectural bets in long-form. Read it
when you find yourself wanting to ask "why DuckDB and not BigQuery?",
"why typed confidence rather than ML-derived?", "why an in-process
semantic layer rather than dbt?". The paper answers all three.

The short version: at IndiaStox-Phase-1 scale (<10M events) and given
that the product is an agent-native consumer prediction platform, the
local-first, type-strict, version-tagged substrate makes 1-week
iteration cycles cheap. The migration story is real (Postgres + dbt +
warehouse split at ~50M events) but premature now.

---

## 14. Glossary — the words this codebase uses

| Term                       | What it means                                                                 |
| -------------------------- | ----------------------------------------------------------------------------- |
| **Make a Call**            | A user submits a BULL or BEAR forecast on a ticker. The only first-class user action. |
| **BULL / BEAR**            | The two directions a call can take. The `direction` column.                   |
| **Gyaani score**           | The user's rating; output of the Glicko-2 engine in `metrics/skill.py`.       |
| **mu / phi**               | Glicko-2 internals: mu = rating mean, phi = uncertainty. Lower phi = more confidence in mu. |
| **Identity confidence**    | A float 0–1 attached to every cross-system identity match. Never a boolean.   |
| **MetricResult**           | The Pydantic contract every metric tool returns. Carries value + confidence + version + trace. |
| **Ghost**                  | A user who signs up and never makes a call. Tracked weekly per cohort.        |
| **Dark channel**           | An acquisition path with no UTM / no consented identifier — typically WhatsApp forwards, Telegram shares. |
| **Gameability index**      | Three-axis watchdog (definition-hash drift, source-table drift, value drift) over the metric layer itself. |
| **Audit log**              | The `agent_actions` table. Every tool call lands here. Append-only, schema-typed. |
| **Tool call / ToolSession** | The only way to read or compute a metric. The audit log is keyed off this surface. |
| **Critic v2.0.0**          | The proposal-review agent that runs five confounder checks against live data before approval. |
| **FM6**                    | The pass/fail threshold on the 11-question agent eval (currently <31 of 33 points = FAIL). |

---

## 15. Who to ping

Repo owner: Abhishek Vyas — github.com/abhishek5878
For substrate / metric questions, prefer reading `POSITION_PAPER.md`
first; for "how does the Critic decide X" questions, read the actual
critique payload on `/proposals` — it's verbose by design.

---

*Last refreshed: 2026-05-19. The repo is the source of truth; if this
doc disagrees with the code, the code wins. PRs welcome.*
