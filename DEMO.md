# 5-minute Loom script

Run from the repo root. Each segment is a concrete sequence. Times are
wall-clock targets for the recording — adjust as you breathe.

> **Open on this file in the editor for the first 5 seconds.** Then run
> `make all` in a second pane so the pipeline can warm in the background
> while you talk.

---

## 0:00 — 0:25  ·  Frame the substrate in one sentence

```bash
duckdb -c "SELECT COUNT(*) FROM read_parquet('data/personas.parquet')"
# → 2000
head -1 raw/unstop_week01.csv          # college_email + browser_fingerprint
head -1 raw/backend_events.ndjson       # personal_email + device_fingerprint
```

> "Two thousand synthetic Indian personas, five raw sources, no shared
> key between them. The repo answers: how do we resolve identity across
> those, how does an agent reason about the result probabilistically,
> and how do we evaluate the agent that does the reasoning."

---

## 0:25 — 1:15  ·  The four brief-mandated metrics, one command each

```bash
make metric M=weekly_active_posters
make metric M=time_to_first_action
make metric M=unstop_to_participation_rate
make metric M=ghost_rate ARGS="--acquisition_source unstop"
```

> "Every metric in the layer returns a typed MetricResult — value,
> confidence, sample_n, provenance, window_open, interpretation, plus a
> sha256 definition_hash. Bare floats from tools raise TypeError at
> runtime — the contract is enforced, not documented. Same struct the
> agent reads, the audit trail records, and the eval grades against."

---

## 1:15 — 2:00  ·  Three-pass identity resolution

```bash
make resolve
```

While the report prints:

> "Pass 1 deterministic email match — 1,333 at confidence 1.0. Pass 2
> fuzzy name+device — 344 in the 0.50–0.84 band. Pass 3 anti-merge —
> 170 pairs blocked because they share a device fingerprint with
> overlapping sessions."

Then show one each:

```bash
# A Pass 2 fuzzy edge — name typo bridged by device fingerprint.
duckdb identity/edges.duckdb -c "
  SELECT confidence, provenance FROM identity_edge
  WHERE resolution_method = 'fuzzy_name_device' ORDER BY confidence DESC LIMIT 1"

# An anti-merge — same device, sessions overlap, correctly NOT merged.
duckdb identity/edges.duckdb -c "
  SELECT source_key, confidence, provenance FROM identity_edge
  WHERE resolution_method = 'blocked_shared_device' LIMIT 1"
```

---

## 2:00 — 2:45  ·  Dashboard — four panels, real numbers

```bash
make dashboard-panels
```

Pan over the four panels printed (or pre-render them and have the
markdown open):

```
### Panel 1 — Weekly Challenge Funnel (Unstop cohort, strict-subset)
unstop_registered  → 1368 (100%)
challenge_signed_up → 1258 (92%)
made_a_prediction  →  901 (66%)
outcome_resolved   →  901 (66%)

### Panel 2 — Channel Attribution
whatsapp_dark: ghost_rate 32.5%, signup_rate 94.2%, ttfa 28.9h
unstop:        ghost_rate 32.4%, signup_rate 92.0%, ttfa 33.4h

### Panel 3 — Cohort Retention (W01 day-by-day)
day 0 →  51 (2.5%) ... day 6 → 539 (27.0%)

### Panel 4 — Identity Resolution Quality
high (≥0.85) 81.6% | medium 17.2% | low 1.2% | blocked 8.5%
```

> "The same four panels seed Metabase via `make dashboard-seed` — the
> API path creates the dashboard programmatically once you `docker
> compose up`. Either way: same numbers, same provenance."

---

## 2:45 — 3:30  ·  The agent answers, the eval grades, the loop closes

```bash
make eval
```

While the scorecard prints:

> "Ten canonical questions, max 3 per question, 30 total. The agent
> scored 27 of 30. Q03 and Q04 — one-point-something off, a real
> definition drift between the metric function and the ground-truth SQL.
> The eval caught what code review missed. Q10, can we estimate week-4
> retention from one week — the agent says insufficient data, wide CI,
> propose an incrementality test. That's the right answer, and the eval
> rewards it."

Then point to the auto-generated improvement file:

```bash
head -25 PROPOSED_IMPROVEMENTS.md
```

> "After every eval, the improvement agent identifies each lost point
> and proposes a concrete fix. `make promote-improvement LINE=N` logs
> the human decision to `agent_actions` with `tool_name=self_improvement`.
> The eval loop closes on itself."

---

## 3:30 — 4:20  ·  Proposal pipeline — finding to action, audited

```bash
make bonus
cat proposals/pending/PROP-*.yaml | head -25
```

> "Ghost-rate spike of +11pp on the Unstop cohort. The agent wrote a
> proposal — to YAML, to DuckDB, to the same raw event stream the
> finding came from. Audit by construction."

```bash
PROP=$(ls proposals/pending/ | grep -v gitkeep | head -1 | sed 's/.yaml//')
make approve PROPOSAL_ID=$PROP
duckdb warehouse/indiastox.duckdb -c "SELECT proposal_id, status FROM proposals"
duckdb warehouse/indiastox.duckdb -c "
  SELECT tool_name FROM agent_actions WHERE downstream_proposal_id = '$PROP'"
```

> "Pending → approved. Both the YAML and the DuckDB row updated, and a
> `proposal_approved` agent_action recording who decided what."

Now reproducibility:

```bash
make reproduce PROPOSAL_ID=$PROP
# Then simulate definition drift:
python3 -m bonus.reproduce PROPOSAL_ID=$PROP \
  --force-stale-hash-for ghost_rate=deadbeef0000000000000000000000000000000000000000000000000000feed
```

> "Six months from now an auditor asks: did the agent really see what
> it reported? `make reproduce` replays every tool call from the
> proposal's session and compares result hashes. Bit-exact if nothing
> changed; a clear diff if the definition has shifted. This is the
> audit primitive the brief asked for."

---

## 4:20 — 4:50  ·  The CS Agent — the substrate isn't Growth-only

```bash
make cs-run
head -20 interventions/pending/$(ls interventions/pending/ | grep -v gitkeep | head -1)
```

> "Same metric layer, same identity graph, same proposal pipeline — now
> serving a different agent archetype. Ten at-risk users, each
> intervention grounded in their actual tickers and prediction history.
> Zero re-architecture. The substrate generalizes."

---

## 4:50 — 5:00  ·  Failure-mode harness — the safety net

```bash
make verify
# → Failure-mode checks: 10/10 PASS
```

> "Ten checks. Two of them break the build if the system looks too
> good — FM6 fails if the agent scores 28+/30 on its own eval, FM9
> fails if `make reproduce` can't detect simulated drift. A system that
> breaks itself when it looks too good is the worldview the brief is
> hiring for."

---

## Bonus mention (10 seconds at the end)

> "Everything you just saw is also the SETUP.md scaffold from the brief
> — `.claude/CLAUDE.md` carries the rules, `tasks/lessons.md` accumulates
> corrections, hooks fire on each edit. That's how I'd hand this to the
> next engineer."

---

## Full reset / re-run

```bash
make clean
make all                      # all 8 steps incl. eval + cs-run + position-paper
make bonus
make approve PROPOSAL_ID=$(ls proposals/pending/ | grep -v gitkeep | head -1 | sed 's/.yaml//')
make reproduce PROPOSAL_ID=<same>
make dashboard-panels
make verify                   # 10/10
```
