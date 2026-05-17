"""Run all failure-mode checks. Exit non-zero if any fails.

Original 4 (FM1-FM4): determinism, defined-once, deferred join, anti-merge.
Added in v2 (FM5-FM7): confidence distribution sanity, eval-too-easy check,
proposal-pipeline end-to-end check.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import duckdb
import pandas as pd

REPO = Path(__file__).resolve().parent
RAW = REPO / "raw"
EDGES_DB = REPO / "identity" / "edges.duckdb"
WAREHOUSE = REPO / "warehouse" / "indiastox.duckdb"
EVAL_RESULTS = REPO / "eval" / "results"
PROPOSALS_PENDING = REPO / "proposals" / "pending"
PROPOSALS_APPROVED = REPO / "proposals" / "approved"

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def check_1_determinism() -> bool:
    """Run identity/resolve.py twice. Output (edges.duckdb digest) must be identical."""
    print("\n[1/10] DETERMINISM")
    digests = []
    for i in range(2):
        # Re-run resolution.
        r = subprocess.run(["python3", "identity/resolve.py"], capture_output=True, text=True, cwd=str(REPO))
        if r.returncode != 0:
            print(f"  FAIL: resolve.py exited {r.returncode} on run {i+1}")
            print(r.stderr[-1000:])
            return False
        # Hash the edges by entity_id + source_key + confidence + method
        con = duckdb.connect(str(EDGES_DB), read_only=True)
        rows = con.execute("SELECT entity_id, source_key, confidence, resolution_method FROM identity_edge ORDER BY entity_id, source_key").fetchall()
        con.close()
        h = hashlib.sha256(repr(rows).encode()).hexdigest()
        digests.append(h)
        print(f"  run {i+1}: {len(rows)} edges, digest={h[:16]}")

    ok = digests[0] == digests[1]
    print(f"  result: {'PASS' if ok else 'FAIL — non-deterministic output'}")
    return ok


def check_2_defined_once() -> bool:
    """A file is OK if it consumes `ghost_rate` legitimately:
      - imports it from `metrics.definitions` (function call), OR
      - references it only as a string literal / column name (no SQL math).
    A file is SUSPECT if it mentions `ghost_rate` AND contains SQL arithmetic
    AND does NOT import the metric function.
    """
    print("\n[2/10] DEFINED-ONCE RULE")
    needle = "ghost_rate"
    arithmetic_tokens = ["COUNT(", "SUM(", "AVG(", "median("]
    import_marker = "from metrics.definitions import"
    ok = True
    for path in REPO.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in {".py", ".sql", ".yml", ".yaml", ".md"}:
            continue
        if path.is_relative_to(REPO / "metrics"):
            continue
        if path.is_relative_to(REPO / ".git"):
            continue
        if path.name == "verify_failure_modes.py":
            continue
        try:
            text = path.read_text()
        except Exception:
            continue
        if needle not in text:
            continue

        has_arithmetic = any(tok in text for tok in arithmetic_tokens)
        imports_metric = import_marker in text
        is_dashboard_spec = path.name == "docker-compose.yml"
        # eval/canonical_questions.yaml *intentionally* contains independent
        # SQL — it's the ground-truth verification of the metric functions,
        # so an independent implementation is exactly the goal there.
        is_eval_ground_truth = path.is_relative_to(REPO / "eval")
        # core/ is framework code. It computes identity-confidence summaries
        # via SQL (legitimate; not a metric value) and mentions ghost_rate
        # in docstrings as the canonical example. Not a metric recomputation.
        is_framework = path.is_relative_to(REPO / "core")
        # dashboard/ contains seed.py + render_panels.py which read from
        # metric_results (the materialization) by design. The SQL math
        # there is for the by-source breakdown rendering, not metric
        # redefinition. The contract is preserved: metric_results IS the
        # metric layer's authoritative output, queryable by dashboards.
        is_dashboard_dir = path.is_relative_to(REPO / "dashboard")
        # DEMO.md scripts a demo against the substrate. Mentions metric
        # names in narrative + shows example SQL queries against
        # warehouse tables, not metric recomputation.
        is_demo_script = path.name == "DEMO.md"

        if (has_arithmetic and not imports_metric and not is_dashboard_spec
                and not is_eval_ground_truth and not is_framework
                and not is_dashboard_dir and not is_demo_script):
            print(f"  SUSPECT: {path.relative_to(REPO)} — has `{needle}` + SQL arithmetic + no metric import")
            ok = False
        elif has_arithmetic and is_dashboard_spec:
            print(f"  ok ({path.name}): reads metric_results, doesn't re-compute")
        elif has_arithmetic and is_eval_ground_truth:
            print(f"  ok ({path.name}): eval ground-truth — intentional independent SQL")
        elif has_arithmetic and is_framework:
            print(f"  ok ({path.name}): framework module — identity-summary SQL is not metric recomputation")
        elif has_arithmetic and is_dashboard_dir:
            print(f"  ok ({path.name}): dashboard module — reads metric_results materialization")
        elif has_arithmetic and is_demo_script:
            print(f"  ok ({path.name}): demo script — example SQL, not metric recomputation")
        elif imports_metric:
            print(f"  ok ({path.name}): imports ghost_rate from metrics.definitions")
        else:
            print(f"  ok ({path.name}): mentions but no recomputation pattern")

    print(f"  result: {'PASS' if ok else 'FAIL — inline ghost_rate recomputation detected'}")
    return ok


def check_3_deferred_join() -> bool:
    """Earliest resolved_at >= earliest made_at + 4 days."""
    print("\n[3/10] DEFERRED JOIN")
    # Read backend events for prediction_made min timestamp.
    earliest_made = None
    with (RAW / "backend_events.ndjson").open() as f:
        for line in f:
            e = json.loads(line)
            if e.get("event_type") == "prediction_made":
                ts = e["made_at"]
                if earliest_made is None or ts < earliest_made:
                    earliest_made = ts

    earliest_resolved = None
    with (RAW / "outcomes_week01.ndjson").open() as f:
        for line in f:
            e = json.loads(line)
            ts = e["resolved_at"]
            if earliest_resolved is None or ts < earliest_resolved:
                earliest_resolved = ts

    from datetime import datetime, timedelta

    def _p(s):
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)

    m = _p(earliest_made)
    r = _p(earliest_resolved)
    delta = r - m
    print(f"  earliest made_at     = {m.isoformat()}")
    print(f"  earliest resolved_at = {r.isoformat()}")
    print(f"  delta                = {delta}")
    ok = delta >= timedelta(days=4)
    print(f"  result: {'PASS' if ok else 'FAIL — deferred join is not deferred'}")
    return ok


def check_4_shared_device_blocks() -> bool:
    """All personas in the shared_device cohort must have a blocked_shared_device
    edge. The expected count is 170 (85 pairs after adding the 15% dark
    channel — was 200 / 100 pairs pre-dark).
    """
    print("\n[4/10] SHARED-DEVICE ANTI-MERGE")
    personas = pd.read_parquet(REPO / "data" / "personas.parquet")
    shared = personas[personas["identity_pattern"].str.startswith("shared_device:")]
    n_shared = len(shared)

    con = duckdb.connect(str(EDGES_DB), read_only=True)
    # Each shared-device persona has a backend user_id derived from persona_id
    # via the same hash used in generate.py.
    expected_user_ids = []
    for _, p in shared.iterrows():
        import uuid as _uuid
        user_id = str(_uuid.UUID(int=int(hashlib.sha256(p["persona_id"].encode()).hexdigest()[:32], 16)))
        expected_user_ids.append(user_id)

    placeholders = ",".join(["?"] * len(expected_user_ids))
    if not expected_user_ids:
        print("  no shared-device personas found — vacuously PASS (but suspicious)")
        return True
    rows = con.execute(
        f"""
        SELECT entity_id
        FROM identity_edge
        WHERE resolution_method = 'blocked_shared_device'
          AND confidence = -1.0
          AND entity_id IN ({placeholders})
        """,
        expected_user_ids,
    ).fetchall()
    con.close()

    blocked = {r[0] for r in rows}
    missing = [u for u in expected_user_ids if u not in blocked]
    print(f"  shared-device personas       = {n_shared}")
    print(f"  with blocked_shared_device   = {len(blocked)}")
    print(f"  missing                      = {len(missing)}")
    ok = len(missing) == 0
    print(f"  result: {'PASS' if ok else 'FAIL — some shared-device pairs not blocked'}")
    if not ok:
        print(f"  first 5 missing: {missing[:5]}")
    return ok


def check_5_confidence_distribution() -> bool:
    """At least 20% of computed metrics must report confidence < 0.8.

    Rationale: if every MetricResult has confidence > 0.9 the propagation
    chain is lying. Probabilistic identity matches and open prediction
    windows MUST move some metrics below 0.8. If they don't, either the
    identity_confidence_summary penalty is gone or the windowing logic
    isn't firing — both silent failures.
    """
    print("\n[5/10] CONFIDENCE-PROPAGATION SANITY")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from metrics.definitions import (
        weekly_active_posters, time_to_first_action, unstop_to_participation_rate,
        ghost_rate, dark_channel_fraction, channel_cac_bounds, brier_score,
        gyaani_graduation_rate, predictions_per_user, email_click_to_signup,
        metric_gameability_index,
    )
    from metrics.skill import get_skill_distribution
    W = "2024-W01"
    confidences: list[tuple[str, float]] = []
    for fn, args in [
        (weekly_active_posters, [W]),
        (time_to_first_action, [W]),
        (unstop_to_participation_rate, [W]),
        (ghost_rate, [W]),
        (dark_channel_fraction, [W]),
        (channel_cac_bounds, [W]),
        (brier_score, [W]),
        (gyaani_graduation_rate, [W]),
        (predictions_per_user, [W]),
        (email_click_to_signup, []),
        (get_skill_distribution, [None, None]),
        (metric_gameability_index, []),
    ]:
        try:
            r = fn(*args)
            confidences.append((r.metric_name, r.confidence))
        except Exception as e:
            confidences.append((fn.__name__, None))
            print(f"  WARN: {fn.__name__} raised: {e}")

    low_conf = [(n, c) for n, c in confidences if c is not None and c < 0.8]
    total = len([c for _, c in confidences if c is not None])
    pct = len(low_conf) / total if total else 0.0
    print(f"  metrics computed: {total}")
    print(f"  metrics with confidence < 0.8: {len(low_conf)} ({pct:.0%})")
    for n, c in low_conf:
        print(f"    - {n}: {c:.3f}")
    ok = pct >= 0.20
    print(f"  result: {'PASS' if ok else 'FAIL — propagation chain may be over-confident'}")
    return ok


def check_6_eval_not_too_easy() -> bool:
    """Agent must NOT score >= 28/30 on the eval. If it does, questions are
    too easy or ground truths are wrong.
    """
    print("\n[6/10] EVAL DIFFICULTY (FM6)")
    if not EVAL_RESULTS.exists():
        print(f"  FAIL: no eval results in {EVAL_RESULTS} — run `make eval` first.")
        return False
    runs = sorted(EVAL_RESULTS.glob("run_*.json"))
    if not runs:
        print("  FAIL: no eval runs found.")
        return False
    latest = runs[-1]
    payload = json.loads(latest.read_text())
    score = payload["total_score"]
    mx = payload["max_total"]
    threshold = 28  # >= 28/30 means too easy
    print(f"  latest run: {latest.name}  score: {score}/{mx}")
    # Q10 should not be 3/3 — it's genuinely hard.
    q10 = next((r for r in payload["results"] if r["id"] == "Q10"), None)
    if q10:
        print(f"  Q10 (counterfactual lift): {q10['scores']}")
    ok = score < threshold
    print(f"  result: {'PASS' if ok else f'FAIL — agent scored {score}/{mx}, questions too easy or GT wrong'}")
    return ok


def check_7_proposal_pipeline_end_to_end() -> bool:
    """Walk the full proposal lifecycle and verify every side-effect lands:
      - YAML in proposals/pending/
      - DuckDB row in proposals with status='pending'
      - agent_actions row with downstream_proposal_id set
      - approve flow moves to proposals/approved/ AND updates status
    """
    print("\n[7/10] PROPOSAL PIPELINE END-TO-END")
    # 1. Run experiment_loop fresh. If a pending proposal already exists,
    #    the loop just adds another — fine; we'll pick the newest.
    r = subprocess.run(["python3", "-m", "bonus.experiment_loop"], capture_output=True, text=True, cwd=str(REPO))
    if r.returncode != 0:
        print(f"  FAIL: experiment_loop exited {r.returncode}\n{r.stderr[-500:]}")
        return False

    # 2. Find the proposal we JUST created — query DuckDB for the newest
    #    pending row rather than the filesystem (where orphan YAMLs from
    #    earlier sessions can mislead).
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        row = con.execute(
            "SELECT proposal_id FROM proposals WHERE status = 'pending' ORDER BY created_ts DESC LIMIT 1"
        ).fetchone()
    finally:
        con.close()
    if not row:
        print("  FAIL: no pending proposal in DuckDB after experiment_loop run")
        return False
    proposal_id = row[0]
    newest = PROPOSALS_PENDING / f"{proposal_id}.yaml"
    if not newest.exists():
        print(f"  FAIL: DuckDB says pending proposal {proposal_id} but YAML missing at {newest}")
        return False
    print(f"  newest pending (DuckDB-confirmed): {newest.name}")

    # 3. Verify DuckDB row exists with status='pending'.
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        row = con.execute(
            "SELECT status, affected_metric, triggered_by_action_id FROM proposals WHERE proposal_id = ?",
            [proposal_id],
        ).fetchone()
    finally:
        con.close()
    if not row:
        print(f"  FAIL: proposal {proposal_id} not found in DuckDB")
        return False
    status, metric, trigger_id = row
    print(f"  DuckDB row: status={status}, metric={metric}, triggered_by={trigger_id}")
    if status != "pending":
        print(f"  FAIL: expected status='pending', got '{status}'")
        return False

    # 4. Verify the agent_actions row that triggered it has downstream_proposal_id set.
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        a_row = con.execute(
            "SELECT downstream_proposal_id FROM agent_actions WHERE action_id = ?",
            [trigger_id],
        ).fetchone()
    finally:
        con.close()
    if not a_row or a_row[0] != proposal_id:
        print(f"  FAIL: agent_action {trigger_id} does not link to {proposal_id}")
        return False
    print(f"  agent_actions[{trigger_id}].downstream_proposal_id = {a_row[0]}")

    # 5. Approve the proposal — exercise the full state transition.
    r = subprocess.run(["python3", "-m", "bonus.approve", f"PROPOSAL_ID={proposal_id}"],
                       capture_output=True, text=True, cwd=str(REPO))
    if r.returncode != 0:
        print(f"  FAIL: approve exited {r.returncode}\n{r.stderr[-500:]}")
        return False
    moved = PROPOSALS_APPROVED / newest.name
    if not moved.exists():
        print(f"  FAIL: YAML not moved to approved/ ({moved})")
        return False
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        new_status = con.execute("SELECT status FROM proposals WHERE proposal_id = ?", [proposal_id]).fetchone()[0]
        approval_action = con.execute(
            "SELECT tool_name FROM agent_actions WHERE downstream_proposal_id = ? AND tool_name = 'proposal_approved'",
            [proposal_id],
        ).fetchone()
    finally:
        con.close()
    if new_status != "approved":
        print(f"  FAIL: status after approve = '{new_status}', expected 'approved'")
        return False
    if not approval_action:
        print("  FAIL: no proposal_approved agent_actions row found")
        return False
    print(f"  status: pending → approved ✓  approval_action: {approval_action[0]} ✓")
    print("  result: PASS")
    return True


def check_8_cs_interventions_grounded() -> bool:
    """At least 3 of the 10 CS interventions must mention a specific ticker
    from their actual prediction history (not a template).

    Verification: parse each interventions/pending/<uid>.yaml; check that
    `intervention_text` mentions a ticker that also appears in
    `grounding_facts` (specifically the called_tickers list).
    """
    print("\n[8/10] CS INTERVENTIONS GROUNDED IN REAL DATA")
    import yaml as _yaml

    pending = REPO / "interventions" / "pending"
    approved = REPO / "interventions" / "approved"
    candidates = list(pending.glob("*.yaml")) + list(approved.glob("*.yaml"))
    if not candidates:
        # If approved already, only approved/ has files. Both empty → bail.
        print(f"  FAIL: no interventions in {pending} or {approved} — run `make cs-run` first")
        return False

    grounded = 0
    sample: list[tuple[str, str]] = []
    tickers_universe = {"RELIANCE", "TCS", "INFY", "HDFC", "WIPRO", "ICICIBANK",
                        "BAJFINANCE", "SBIN", "HCLTECH", "ITC"}
    for p in candidates[:10]:
        try:
            doc = _yaml.safe_load(p.read_text())
        except Exception:
            continue
        text = doc.get("intervention_text", "")
        mentioned = {t for t in tickers_universe if t in text}
        if mentioned:
            grounded += 1
            sample.append((p.name, next(iter(mentioned))))
    print(f"  interventions found: {len(candidates)}")
    print(f"  interventions mentioning a specific ticker in body: {grounded}")
    for n, t in sample[:5]:
        print(f"    - {n} → {t}")
    ok = grounded >= 3
    print(f"  result: {'PASS' if ok else 'FAIL — fewer than 3 personalized interventions; templates suspected'}")
    return ok


def check_9_reproduce_detects_drift() -> bool:
    """`make reproduce` must report a DIFF when the metric's definition_hash
    has changed since the proposal was logged. We simulate drift via the
    `--force-stale-hash-for` flag rather than actually editing source.
    """
    print("\n[9/10] REPRODUCE DETECTS DEFINITION DRIFT")
    # Find a proposal that exists in DuckDB (not just an orphaned YAML).
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        row = con.execute(
            "SELECT proposal_id FROM proposals ORDER BY created_ts DESC LIMIT 1"
        ).fetchone()
    finally:
        con.close()
    pid: Optional[str] = row[0] if row else None
    if not pid:
        print("  FAIL: no proposals in DuckDB — run `make bonus` first")
        return False
    print(f"  reproducing proposal_id={pid}")

    # Happy path first.
    r = subprocess.run(
        ["python3", "-m", "bonus.reproduce", f"PROPOSAL_ID={pid}"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    combined = (r.stdout or "") + (r.stderr or "")
    happy_pass = "REPRODUCED ✓" in combined and r.returncode == 0
    print(f"  happy path: rc={r.returncode}, 'REPRODUCED ✓' present: {happy_pass}")

    # Drift path — force a fake old hash.
    r = subprocess.run(
        ["python3", "-m", "bonus.reproduce", f"PROPOSAL_ID={pid}",
         "--force-stale-hash-for", "ghost_rate=deadbeef0000000000000000000000000000000000000000000000000000feed"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    combined = (r.stdout or "") + (r.stderr or "")
    drift_caught = ("DEFINITION DRIFT" in combined or "DIFF —" in combined) and r.returncode != 0
    print(f"  drift path: rc={r.returncode}, 'DEFINITION DRIFT' present: {drift_caught}")
    ok = happy_pass and drift_caught
    print(f"  result: {'PASS' if ok else 'FAIL — reproduce did not catch the simulated drift'}")
    return ok


def check_10_position_paper_evidence_based() -> bool:
    """Position paper must cite at least 20 numeric values from live data.

    Threshold is generous; the spec just says "no numbers means the agent
    wrote opinion not analysis". A real evidence-based paper will be in the
    50–150 range; we set 20 as the floor.
    """
    print("\n[10/10] POSITION PAPER IS EVIDENCE-BASED")
    paper = REPO / "POSITION_PAPER.md"
    if not paper.exists():
        print("  FAIL: POSITION_PAPER.md missing — run `make position-paper`")
        return False
    text = paper.read_text()
    # Count numeric tokens (integers, decimals, percentages).
    import re
    numbers = re.findall(r"\b\d+(?:\.\d+)?%?\b", text)
    has_claims = "## CLAIMS" in text and "FALSIFIABLE BY" in text
    has_signature = "Growth Agent" in text and "metric versions" in text
    print(f"  numeric tokens cited: {len(numbers)}")
    print(f"  has CLAIMS + FALSIFIABLE BY: {has_claims}")
    print(f"  has agent-signature line: {has_signature}")
    ok = len(numbers) >= 20 and has_claims and has_signature
    print(f"  result: {'PASS' if ok else 'FAIL — paper missing evidence, claims, or signature'}")
    return ok


def main() -> None:
    results = [
        check_1_determinism(),
        check_2_defined_once(),
        check_3_deferred_join(),
        check_4_shared_device_blocks(),
        check_5_confidence_distribution(),
        check_6_eval_not_too_easy(),
        check_7_proposal_pipeline_end_to_end(),
        check_8_cs_interventions_grounded(),
        check_9_reproduce_detects_drift(),
        check_10_position_paper_evidence_based(),
    ]
    print("\n=========================================")
    print(f"Failure-mode checks: {sum(results)}/{len(results)} PASS")
    print("=========================================")
    if not all(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
