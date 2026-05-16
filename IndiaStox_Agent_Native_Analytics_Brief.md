# IndiaStox Analytics 2.0 — A Problem Brief for an Agent-Native Engineering Lead

*Audience: a senior engineer joining IndiaStox to own the analytics substrate. This is not a JD. It's the problem space, the worldview, and the engineering bets we want you to take a position on.*

---

## 1\. The frame: analytics as a substrate, not a deliverable

Most analytics orgs at consumer companies — even at Meta, Google, LinkedIn, Reddit — were built for a world where the consumer of data was a human: a PM scanning a dashboard on Monday, a growth marketer reading an attribution report, a CS lead pulling a churn cohort. The data warehouse, the BI tool, the experimentation platform, the CDP — all of them were optimized for *human latency, human cognition, and human throughput*. That world is ending. The next decade of consumer analytics will be defined by data systems whose primary consumer is an agent — a Growth Agent that proposes and runs campaign experiments, a Product Agent that reads roadmap context from Notion and product telemetry from the warehouse and writes the next PRD, a Customer Success Agent that intervenes the moment a high-reputation user's behavior bends toward churn.

We are not retrofitting an agent layer onto a dashboard stack. We are designing the dashboard stack as the I/O surface of an agent stack. Everything you build — the event taxonomy, the identity graph, the metric semantic layer, the experimentation primitives — must be **tool-callable, semantically typed, and decision-auditable** by an LLM-driven agent harness. If a metric exists only inside a Tableau workbook, it does not exist. If an event has a human-readable name but no schema contract, it does not exist. If an action — a paid campaign budget change, a Notion page update, a Slack DM to an at-risk user — cannot be both executed and logged through the same substrate, that action does not exist.

This inversion is the assignment. Build the analytics layer such that the natural next step — wiring agents on top — is a configuration problem, not a re-architecture.

---

## 2\. The IndiaStox specificity: predictions as labeled ground truth

IndiaStox is not a typical social product. On a feed app, "engagement" is the terminal signal — a like, a share, a watch-time-second. There is no further verdict; engagement is what it is. On IndiaStox, every meaningful user action is *also a prediction*, and every prediction has a future ground-truth event that the market itself supplies. A user calls a stock. The market either agrees or disagrees. The Gyaani reputation system collapses this stream of labeled bets into a single signal — accuracy — that we then surface as social capital, gamify with coins and ranks, and use to weight feed curation and discovery.

This changes the analytics problem in three ways, and you should let it warp the entire design.

**First**, every user has a *latent skill curve* the platform can estimate, refine, and act on. The data model is not "user → events → cohort." It is "user → events → predictions → outcomes → calibrated skill estimate → reputation trajectory." The right primitive is closer to a player rating system (Glicko, TrueSkill) than a marketing funnel. The implication: your event schema must carry, for every prediction-class event, a deferred join to the outcome event. Most CDPs cannot natively express this. Design for it.

**Second**, accuracy *is* a leading indicator of retention, virality, and LTV — but in a non-obvious way. Early high accuracy creates social proof, which creates feed prominence, which creates engagement, which creates more predictions, which creates more accuracy data. Early low accuracy creates a quieter doom loop. The analytics layer needs to surface where on this curve each user sits, and the agent layer needs to be able to act on it (a CS Agent nudges a stalled mid-accuracy user; a Growth Agent learns that ad creatives bringing in users who reach 5 predictions in week one have 4× the LTV of those who don't).

**Third**, the platform has an unusually rich *truth signal* for agents to learn against. Most growth experiments suffer because outcomes are noisy and slow. Here, every prediction is closing the loop in days or weeks against a market that does not lie. This is one of the most fertile substrates for closed-loop, agent-driven experimentation that exists in Indian consumer tech today. Treat that as the design center.

---

## 3\. The acquisition reality you are inheriting

Today, the acquisition graph is small and stitched by hand: Unstop drops a weekly cohort, our backend records sign-ups and posts, PostHog records clicks, Klaviyo records opens, GA records organic landings. None of these systems share a key. The Monday narrative is glued together in a workbook because nothing else works yet. You are inheriting that. You are also inheriting the eighteen-month roadmap behind it: Meta, Google, LinkedIn, YouTube, programmatic, creator partnerships, and India-specific surfaces (ShareChat, Moj, KuKu FM ad reads). The number of acquisition surfaces will go from one to twenty inside a year. The funnel cannot continue to be stitched by hand and it cannot be stitched by yet another off-the-shelf attribution vendor whose model is opaque to the agent layer that has to act on it.

The hard problems compound. Email is a fragile join key — users sign up on Unstop with a college address, install the app with a personal one, and never reconcile. iOS 14+ has destroyed deterministic ad attribution at the platform edge; Meta and Google now return aggregated, noised, modeled conversions that your agent has to reason about probabilistically rather than treat as fact. Indian users transact across multiple devices and frequently share them. WhatsApp, the dominant referral surface, is essentially dark to traditional UTM analytics. And the metric that matters — does this user become a high-Gyaani contributor who retains and refers — sits eight to twelve weeks downstream of the click, far past the attribution window any ad network gives you for free.

Your job is not to solve attribution perfectly. It is to build an attribution and identity system whose uncertainty is *typed and exposed* — every user-touchpoint edge carries a confidence, every conversion carries a provenance, every modeled number carries a model version — so that an agent reading this layer can reason about its own confidence rather than hallucinate certainty.

---

## 4\. The engineering problem, stated precisely

Build, in this order:

The weekend brief asks the candidate to ship a working miniature of the production analytics platform in 48 hours, on synthetic data they generate themselves: a one-week slice of Indiastox traffic — roughly 2,000 users — across all five mock sources (Unstop CSV, backend Postgres stream, PostHog frontend events, Klaviyo email events, GA4 sessions) with deliberate identity-graph fuzz baked in (70% clean deterministic email matches, 30% needing fuzzy stitching because the user signed up on Unstop with a college email and on Indiastox with a personal Gmail), plus the weekly-challenge-signup-to-challenge-participation deferred-join pattern that is the unique Indiastox primitive. On top of that data they ship five artifacts — a versioned workbook schema as code (the six-tab structure from the PRD, defined once and reused), an identity-resolution step that emits confidence-scored matches with provenance rather than collapsing everything to a boolean, a metric semantic layer with `weekly_active_posters`, `time_to_first_action`, `unstop_to_participation_rate`, and `ghost_rate` defined exactly once as pure functions, a Metabase (or Superset) dashboard wired to those metrics that renders the Weekly Challenge funnel, channel attribution, and cohort retention end-to-end against the populated data, and a one-page position paper taking a written stance on three of the open questions from the PRD (Excel vs Google Sheets for Phase 1 storage, what counts as "engagement," how far back to backfill, who owns the weekly Unstop drop). Deliverable shape is concrete: a public GitHub repo plus a five-minute Loom walking through the dataset, the architecture, one full ad-hoc query answered via the natural-language layer, and the position paper. The section calls out the specific failure modes the team will look for — synthetic data too clean to test identity resolution, identity confidence collapsed to a yes/no, metric definitions silently disagreeing between the dashboard and the ad-hoc query, dashboards that look pretty but tell no story — so the candidate self-selects on whether they understood the brief. The bonus round closes the loop: take a finding from the dashboard, have the candidate's setup propose a follow-up experiment (e.g. "ghost rate jumped 15% this week — recommend A/B testing the Unstop landing page UTM"), write that proposal back to a synthetic Notion page, and log the proposal itself as an event in the same workbook — production architecture in miniature, end-to-end, in a weekend.

---

## 5\. The agent layer this substrate has to support

You are not building these agents in month one. But you are designing the data layer such that they fit on top without re-architecture. Three archetypes to plan against.

**The Growth Agent** reads the unified event stream, the identity graph, the attribution model, and the metric layer. It asks questions like: which ad creative on Meta is bringing in users who reach five predictions in their first week? Which Unstop college cohort has the highest week-four Gyaani-graduation rate? Which LinkedIn campaign should we double, and which should we kill? It can open a new experiment, propose a creative variant, draft the copy, and — gated by a human approval primitive you will also build — push the budget change to the ad network. The substrate must expose channel APIs as tools, not just as data sources.

**The Product Agent** reads the event stream plus *Notion*. Notion is not a passive doc store in this architecture; it is the canonical roadmap, the PRD library, the spec graph. The Product Agent correlates a sudden drop in time-to-first-prediction with a ranking change shipped on Tuesday (it reads the deploy log, also an event), drafts the rollback proposal, and posts it as a Notion comment tagged to the relevant PRD owner. It identifies feature-level friction the team has not noticed and writes the PRD draft for the next sprint. The substrate must expose Notion as both a readable graph and a writable surface.

**The Customer Success Agent** reads user-level state — reputation trajectory, prediction cadence, social-graph health, last-session recency — and intervenes before churn. For a high-Gyaani user whose prediction cadence has fallen 60% week-over-week, it drafts a personalized Slack/email/in-app message, references the user's specific accuracy track record, and routes the draft to a human for the first hundred sends and autonomously after the eval bar is cleared. The substrate must expose messaging surfaces (email, Slack, in-app) as tools, and must expose user-level state with enough specificity that the agent's message is *true and personal* rather than a generic nudge.

The common thread: agents are functions over (event stream, identity graph, metric layer, external doc graphs, action surfaces). Everything you build is either one of those inputs or one of those outputs. If something does not fit that model, ask whether the model is wrong, or whether the thing you are building is.

---

## 6\. The engineering bets we want your position on

These are the questions where reasonable senior engineers disagree, and where your answer becomes the architecture. We expect a written position on each in your first thirty days.

What is the storage shape that lets us query a 500M-event stream cheaply *and* serve typed tool calls to agents with sub-second latency? (Warehouse \+ serving layer? Iceberg \+ DuckDB? ClickHouse? Single Postgres with aggressive denormalization until we can't?)

How do we represent identity-graph confidence in a way that an LLM agent can actually reason about, rather than collapse to a boolean?

How do we version the metric semantic layer such that an agent's answer six months from now is reproducible against the definition that was current when the question was asked?

What is the eval harness for the Growth/PM/CS agents? What does "this agent is performing" look like as a number? How do we avoid the trap where agents generate motion without generating outcomes?

How do we keep humans in the loop without making humans the bottleneck — what is the approval/auto-promotion ladder for agent actions of escalating consequence (CS DM → ad budget change → feed ranking change)?

How do we treat WhatsApp, the single most important Indian referral surface and the single darkest one to attribution, as something better than a black box?

How do we make the prediction-outcome join — the unique IndiaStox asset — a first-class primitive that agents can reason about, rather than an SQL pattern that re-emerges in twenty places?

---

## 7\. First principles to anchor on

Data is a substrate for agents, not a deliverable for humans. Every dashboard is a degraded read of the underlying tool surface; if the tool surface is right, dashboards become a generated artifact, not a built one.

Every metric must be defined exactly once and callable as a tool. The number of times the team has argued about what "active user" means is the number of failures of this principle.

Every action an agent takes must be itself an event in the same stream that produced the data the action was based on. Agents that are not auditable are not deployable.

Uncertainty must be typed and exposed, never hidden. An identity edge has a confidence. A modeled conversion has a provenance. A retention forecast has a confidence interval. Agents that consume hidden-uncertainty data hallucinate; agents that consume typed-uncertainty data reason.

The IndiaStox prediction-outcome loop is a rare gift. Most consumer platforms wait quarters for ground truth on whether a product decision was correct. We wait days, against a market that cannot be argued with. Build the substrate that lets agents learn from that loop at the pace the loop allows.

---

## 8\. What "done" looks like in twelve months

A Growth Agent that can be asked, in a Slack channel, "should we double LinkedIn paid spend this week?" — and that responds with the segment-level CAC, the predicted Gyaani-graduation lift, the confidence interval, the proposed experiment design, and a one-click approval that, when granted, both executes the budget change and writes the decision back into the experiment log. A Product Agent that drafts the rollback PRD on Tuesday afternoon before the PM on call has noticed the metric move. A CS Agent whose first-hundred-sends eval has cleared and whose interventions are now driving measurable lift on the at-risk-high-Gyaani cohort.

And under all of it, an analytics substrate whose existence is invisible — because the right architecture is the one nobody talks about after it ships.

---

*Written for the IndiaStox engineering org. Internal. Position welcomed, pushback expected.*