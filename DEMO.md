# 5-minute Loom script

Run from the repo root. Each segment is a concrete sequence of commands.
Times are wall-clock targets for the recording.

---

## 0:00 — 0:30  ·  The problem in one sentence

```bash
duckdb -c "SELECT COUNT(*) FROM read_parquet('data/personas.parquet')"
# → 2000

# Show one raw Nemotron persona — gives the demo a face.
python3 -c "import pandas; print(pandas.read_parquet('data/personas.parquet').iloc[0])"

# The five raw sources have NO shared id between them:
ls raw/
head -1 raw/unstop_week01.csv          # college_email + browser_fingerprint
head -1 raw/backend_events.ndjson       # personal_email + device_fingerprint
```

> "2,000 synthetic Indian personas. Five sources. No shared key. The
> question this whole repo answers: how do we resolve identity across
> these in a way an agent can reason about probabilistically — and how
> do we evaluate the agent that does the reasoning?"

---

## 0:30 — 1:30  ·  Three-pass identity resolution, with typed confidence

```bash
make resolve
```

While the resolve report prints:

> "Pass 1 deterministic email match — 1,333 matches at confidence 1.0.
> Pass 2 fuzzy name+device — 344 matches, confidence band 0.50 to 0.84.
> Pass 3 anti-merge — 170 blocked pairs."

Then drill into one each:

```bash
# A high-confidence Pass 1 edge.
duckdb identity/edges.duckdb -c "
  SELECT entity_id, source_system, source_key, confidence, resolution_method, provenance
  FROM identity_edge WHERE resolution_method = 'deterministic_email_exact' LIMIT 1"

# A Pass 2 fuzzy edge — name typo bridged by device fingerprint.
duckdb identity/edges.duckdb -c "
  SELECT confidence, provenance FROM identity_edge
  WHERE resolution_method = 'fuzzy_name_device' ORDER BY confidence DESC LIMIT 1"

# An anti-merge — same device, sessions overlap, correctly NOT merged.
duckdb identity/edges.duckdb -c "
  SELECT entity_id, source_key, confidence, provenance FROM identity_edge
  WHERE resolution_method = 'blocked_shared_device' LIMIT 2"
```

---

## 1:30 — 2:30  ·  Growth Agent answers a question, with calibration

```bash
make load        # materialize metrics → metric_results
python3 -c "
from agent.growth_agent import GrowthAgent
a = GrowthAgent()
ans = a.answer('Q04', 'What is the week-1 Gyaani graduation rate?')
print('value:', ans.value)
print()
print('calibration:', ans.calibration)
print()
print('action:', ans.action)
"
```

Then show the MetricResult contract being enforced:

```bash
python3 -c "
from core.confidence import tool_result
@tool_result
def bad(): return 0.5
try: bad()
except TypeError as e: print(e)
"
# → 'Tool 'bad' returned float, expected MetricResult. ...'
```

> "Every tool returns typed confidence. Bare floats are rejected at the
> runtime layer — not a code review convention, an enforced contract."

---

## 2:30 — 3:30  ·  The eval scorecard — honest about what we got right and wrong

```bash
make eval
```

While it prints:

> "Ten canonical questions. Each scored on accuracy, calibration, action —
> max 3, total 30. Watch Q03 and Q04 — those are within-1pp definition
> drift between the metric function and the SQL ground truth. The eval
> caught what code review missed."

> "Q10 asks: 'if we double Unstop spend, what's the week-4 retention lift'.
> The agent answers 'insufficient data, CI [-10pp, +25pp], run a 4-week
> incrementality test.' That's the right answer. With 1 week of data,
> any confident point estimate would be wrong. Eval rewards the
> uncertainty."

Highlight: total 27/30. Below the FM6 sanity-check threshold of 28.

---

## 3:30 — 4:30  ·  The agent finds the ghost-rate spike and writes a proposal

```bash
make bonus
ls proposals/pending/
```

Open the YAML:

```bash
cat proposals/pending/PROP-*.yaml | head -40
```

Then show the audit trail in DuckDB:

```bash
duckdb warehouse/indiastox.duckdb -c "
  SELECT proposal_id, status, hypothesis FROM proposals;
  SELECT action_id, tool_name, downstream_proposal_id
  FROM agent_actions WHERE downstream_proposal_id IS NOT NULL"
```

Approve it:

```bash
PROP=$(ls proposals/pending/ | head -1 | sed 's/.yaml//')
make approve PROPOSAL_ID=$PROP
ls proposals/approved/
duckdb warehouse/indiastox.duckdb -c "SELECT proposal_id, status FROM proposals"
duckdb warehouse/indiastox.duckdb -c "
  SELECT tool_name, downstream_proposal_id FROM agent_actions
  WHERE tool_name LIKE 'proposal_%'"
```

> "Three artifacts. YAML on disk for the human to read. DuckDB row for
> programmatic queries. An audit-log entry for every agent or human
> action. The proposal pipeline is not cosmetic — every step is
> observable."

---

## 4:30 — 5:00  ·  The scorecard, one sentence on what it means

```bash
ls eval/results/
cat eval/results/run_*.json | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f\"Total: {data['total_score']}/{data['max_total']}\")
print(f\"Q10 (counterfactual): {data['results'][9]['scores']}\")
"
```

> "27 out of 30 on the first run. The 3 lost points are: one accuracy
> mismatch on a 1pp definition drift, one missed calibration marker, one
> generic action. We didn't tune to the eval. The eval told us what to
> tune. That's the loop the brief asked for: 'what does this agent is
> performing look like as a number?' This. 27/30. With audited tool
> calls, typed confidence, and a proposal-pipeline that actually moves
> bits."

---

## Cheat sheet — full reset and re-run

```bash
make clean
make all     # personas + generate + resolve + skill + load + test + eval
make bonus
make approve PROPOSAL_ID=$(ls proposals/pending/ | head -1 | sed 's/.yaml//')
make verify  # the 7 failure-mode checks
```
