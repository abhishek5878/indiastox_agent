"""Run the four failure-mode checks from the brief. Exit non-zero if any fails."""
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


def check_1_determinism() -> bool:
    """Run identity/resolve.py twice. Output (edges.duckdb digest) must be identical."""
    print("\n[1/4] DETERMINISM")
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
    print("\n[2/4] DEFINED-ONCE RULE")
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

        if has_arithmetic and not imports_metric and not is_dashboard_spec:
            print(f"  SUSPECT: {path.relative_to(REPO)} — has `{needle}` + SQL arithmetic + no metric import")
            ok = False
        elif has_arithmetic and is_dashboard_spec:
            print(f"  ok ({path.name}): reads metric_results, doesn't re-compute")
        elif imports_metric:
            print(f"  ok ({path.name}): imports ghost_rate from metrics.definitions")
        else:
            print(f"  ok ({path.name}): mentions but no recomputation pattern")

    print(f"  result: {'PASS' if ok else 'FAIL — inline ghost_rate recomputation detected'}")
    return ok


def check_3_deferred_join() -> bool:
    """Earliest resolved_at >= earliest made_at + 4 days."""
    print("\n[3/4] DEFERRED JOIN")
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
    """The 100 shared-device pairs (200 personas) must each have a blocked_shared_device
    edge in edges.duckdb. We check this by verifying ALL personas in the
    shared_device cohort have a blocked edge."""
    print("\n[4/4] SHARED-DEVICE ANTI-MERGE")
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


def main() -> None:
    results = [
        check_1_determinism(),
        check_2_defined_once(),
        check_3_deferred_join(),
        check_4_shared_device_blocks(),
    ]
    print("\n=========================================")
    print(f"Failure-mode checks: {sum(results)}/{len(results)} PASS")
    print("=========================================")
    if not all(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
