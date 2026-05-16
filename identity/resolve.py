"""Identity resolution — 3-pass pipeline.

Pass 1 (deterministic, confidence = 1.0): exact local-part match between
        Unstop college_email and backend personal_email.

Pass 2 (fuzzy, confidence in [0.50, 0.84]): rapidfuzz token_sort_ratio
        on full_name, gated on device_fingerprint match.
        confidence = 0.50 + (name_sim - 0.80) * 1.5 + (0.10 if device else 0)
        capped at 0.84. Confidence is NEVER a boolean; we surface the
        score and provenance for every merge.

Pass 3 (anti-merge, confidence = -1.0): when two already-resolved
        entities share device_fingerprint AND have overlapping sessions
        within 30 minutes, write a blocked_shared_device edge that
        prevents any future merge. They stay distinct entities.

The output is identity/edges.duckdb (the raw audit trail) plus
warehouse/indiastox.duckdb (the loaded dim_user / dim_challenge / fact_*
tables). Both stay in sync via this single pass.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
from rapidfuzz import fuzz

REPO = Path(__file__).resolve().parents[1]
# Allow running this file directly (`python identity/resolve.py`) — without
# this, the `schema` package import fails because sys.path[0] is the script
# directory, not the repo root.
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
RAW_DIR = REPO / "raw"
EDGES_DB = REPO / "identity" / "edges.duckdb"
WAREHOUSE_DB = REPO / "warehouse" / "indiastox.duckdb"

MODEL_VERSION = "v1.0.0"
WEEK_OF = "2024-W01"
WEEKLY_CHALLENGE_ID = "WC-2024-W01"

# 30-minute window for session-overlap anti-merge.
OVERLAP_WINDOW = timedelta(minutes=30)


def _local_part(email: str) -> str:
    return email.split("@", 1)[0].lower() if "@" in email else email.lower()


def _parse_dt(s: str) -> datetime:
    # Tolerate the trailing Z form.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def load_unstop() -> list[dict]:
    rows = []
    with (RAW_DIR / "unstop_week01.csv").open() as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def load_backend() -> tuple[list[dict], list[dict], list[dict]]:
    """Return (signups, challenge_signups, predictions)."""
    signups, challenge_signups, predictions = [], [], []
    for line in (RAW_DIR / "backend_events.ndjson").open():
        e = json.loads(line)
        t = e["event_type"]
        if t == "user_signup":
            signups.append(e)
        elif t == "challenge_signup":
            challenge_signups.append(e)
        elif t == "prediction_made":
            predictions.append(e)
    return signups, challenge_signups, predictions


def load_outcomes() -> list[dict]:
    out = []
    p = RAW_DIR / "outcomes_week01.ndjson"
    if not p.exists():
        return out
    for line in p.open():
        out.append(json.loads(line))
    return out


def load_posthog_sessions() -> dict[str, list[datetime]]:
    """user_id → list of timestamps (from events whose distinct_id == user_id)."""
    by_user: dict[str, list[datetime]] = defaultdict(list)
    for line in (RAW_DIR / "posthog_events.ndjson").open():
        e = json.loads(line)
        did = e.get("distinct_id")
        ts = e.get("timestamp")
        if not did or not ts:
            continue
        # PostHog's distinct_id is sometimes an anonymous UUID and sometimes
        # the canonical user_id; either way we collect them as the
        # session-bearing key for that observable identity.
        try:
            by_user[did].append(_parse_dt(ts))
        except Exception:
            continue
    return by_user


# ---------------------------------------------------------------------------
# Pass 1 — deterministic
# ---------------------------------------------------------------------------

def pass1_deterministic(unstop: list[dict], signups: list[dict]) -> tuple[list[dict], set[str], set[str]]:
    """Match Unstop college_email to backend personal_email when local-parts equal.

    Returns (edges, matched_unstop_ids, matched_signup_user_ids).
    """
    signup_by_localpart: dict[str, dict] = {}
    for s in signups:
        signup_by_localpart[_local_part(s["personal_email"])] = s

    edges: list[dict] = []
    matched_unstop_ids: set[str] = set()
    matched_signup_user_ids: set[str] = set()

    for u in unstop:
        local = _local_part(u["college_email"])
        if local in signup_by_localpart and signup_by_localpart[local]["user_id"] not in matched_signup_user_ids:
            sig = signup_by_localpart[local]
            entity_id = sig["user_id"]  # canonical = backend user_id

            edges.append(dict(
                edge_id=_edge_id("p1", u["unstop_id"]),
                entity_id=entity_id,
                source_system="unstop",
                source_key=u["college_email"],
                key_type="email",
                confidence=1.0,
                resolution_method="deterministic_email_exact",
                provenance=dict(
                    email_local_part=local,
                    name_similarity=None,
                    device_match=None,
                    matched_personal_email=sig["personal_email"],
                ),
                model_version=MODEL_VERSION,
            ))
            edges.append(dict(
                edge_id=_edge_id("p1", sig["user_id"]),
                entity_id=entity_id,
                source_system="backend",
                source_key=sig["personal_email"],
                key_type="email",
                confidence=1.0,
                resolution_method="deterministic_email_exact",
                provenance=dict(
                    email_local_part=local,
                    name_similarity=None,
                    device_match=None,
                    matched_college_email=u["college_email"],
                ),
                model_version=MODEL_VERSION,
            ))
            matched_unstop_ids.add(u["unstop_id"])
            matched_signup_user_ids.add(sig["user_id"])

    return edges, matched_unstop_ids, matched_signup_user_ids


def _edge_id(prefix: str, key: str) -> str:
    return f"{prefix}-{hashlib.sha1(key.encode()).hexdigest()[:16]}"


# ---------------------------------------------------------------------------
# Pass 2 — fuzzy
# ---------------------------------------------------------------------------

def pass2_fuzzy(
    unstop: list[dict],
    signups: list[dict],
    matched_unstop_ids: set[str],
    matched_signup_user_ids: set[str],
) -> list[dict]:
    """For unresolved unstop rows, fuzzy-match on name+device against unresolved signups."""
    unresolved_unstop = [u for u in unstop if u["unstop_id"] not in matched_unstop_ids]
    unresolved_signups = [s for s in signups if s["user_id"] not in matched_signup_user_ids]

    # Bucket unresolved signups by device for cheap lookup.
    sig_by_device: dict[str, list[dict]] = defaultdict(list)
    for s in unresolved_signups:
        sig_by_device[s["device_fingerprint"]].append(s)

    edges: list[dict] = []
    used_signup_user_ids: set[str] = set()

    for u in unresolved_unstop:
        candidates = sig_by_device.get(u.get("browser_fingerprint", ""), [])
        best: tuple[float, dict] | None = None
        for c in candidates:
            if c["user_id"] in used_signup_user_ids:
                continue
            sim = fuzz.token_sort_ratio(u["full_name"], c["full_name"]) / 100.0
            if sim >= 0.80:
                if best is None or sim > best[0]:
                    best = (sim, c)

        if best is None:
            continue

        sim, sig = best
        device_match = True
        confidence = 0.50 + (sim - 0.80) * 1.5 + (0.10 if device_match else 0.0)
        confidence = min(confidence, 0.84)

        entity_id = sig["user_id"]
        used_signup_user_ids.add(sig["user_id"])

        edges.append(dict(
            edge_id=_edge_id("p2u", u["unstop_id"]),
            entity_id=entity_id,
            source_system="unstop",
            source_key=u["college_email"],
            key_type="email",
            confidence=confidence,
            resolution_method="fuzzy_name_device",
            provenance=dict(
                name_similarity=round(sim, 4),
                device_match=device_match,
                matched_personal_email=sig["personal_email"],
                rapidfuzz_algorithm="token_sort_ratio",
            ),
            model_version=MODEL_VERSION,
        ))
        edges.append(dict(
            edge_id=_edge_id("p2b", sig["user_id"]),
            entity_id=entity_id,
            source_system="backend",
            source_key=sig["personal_email"],
            key_type="email",
            confidence=confidence,
            resolution_method="fuzzy_name_device",
            provenance=dict(
                name_similarity=round(sim, 4),
                device_match=device_match,
                matched_college_email=u["college_email"],
                rapidfuzz_algorithm="token_sort_ratio",
            ),
            model_version=MODEL_VERSION,
        ))

    return edges


# ---------------------------------------------------------------------------
# Pass 3 — anti-merge for shared device with session overlap
# ---------------------------------------------------------------------------

def pass3_anti_merge(
    signups: list[dict],
    posthog_sessions_by_user: dict[str, list[datetime]],
) -> list[dict]:
    """For each pair of distinct entities sharing a device_fingerprint, if their
    PostHog sessions overlap within OVERLAP_WINDOW, write an anti-merge edge
    on each side.
    """
    by_device: dict[str, list[dict]] = defaultdict(list)
    for s in signups:
        by_device[s["device_fingerprint"]].append(s)

    edges: list[dict] = []
    for device_fp, group in by_device.items():
        if len(group) < 2:
            continue
        # Compare each pair.
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a = group[i]
                b = group[j]
                ts_a = sorted(posthog_sessions_by_user.get(a["user_id"], []))
                ts_b = sorted(posthog_sessions_by_user.get(b["user_id"], []))
                if not ts_a or not ts_b:
                    continue
                overlapping = _has_overlap(ts_a, ts_b, OVERLAP_WINDOW)
                if not overlapping:
                    continue
                gap_hours = _min_gap(ts_a, ts_b).total_seconds() / 3600.0

                provenance = dict(
                    shared_device_fingerprint=device_fp,
                    session_gap_hours=round(gap_hours, 4),
                    overlap_window_minutes=int(OVERLAP_WINDOW.total_seconds() / 60),
                    paired_user_id=b["user_id"],
                )
                edges.append(dict(
                    edge_id=_edge_id("p3", f"{a['user_id']}|{b['user_id']}"),
                    entity_id=a["user_id"],
                    source_system="backend",
                    source_key=device_fp,
                    key_type="device_fingerprint",
                    confidence=-1.0,
                    resolution_method="blocked_shared_device",
                    provenance=provenance,
                    model_version=MODEL_VERSION,
                ))
                # And symmetrically on the other side.
                edges.append(dict(
                    edge_id=_edge_id("p3", f"{b['user_id']}|{a['user_id']}"),
                    entity_id=b["user_id"],
                    source_system="backend",
                    source_key=device_fp,
                    key_type="device_fingerprint",
                    confidence=-1.0,
                    resolution_method="blocked_shared_device",
                    provenance=dict(provenance, paired_user_id=a["user_id"]),
                    model_version=MODEL_VERSION,
                ))
    return edges


def _has_overlap(a: list[datetime], b: list[datetime], window: timedelta) -> bool:
    """O(n+m) two-pointer scan over sorted lists."""
    i = j = 0
    while i < len(a) and j < len(b):
        if abs(a[i] - b[j]) <= window:
            return True
        if a[i] < b[j]:
            i += 1
        else:
            j += 1
    return False


def _min_gap(a: list[datetime], b: list[datetime]) -> timedelta:
    """Minimum |a - b| over the cross product, in O(n+m) over sorted lists."""
    i = j = 0
    best = timedelta.max
    while i < len(a) and j < len(b):
        gap = abs(a[i] - b[j])
        if gap < best:
            best = gap
        if a[i] < b[j]:
            i += 1
        else:
            j += 1
    return best


# ---------------------------------------------------------------------------
# DDL + load
# ---------------------------------------------------------------------------

EDGES_DDL = """
CREATE TABLE IF NOT EXISTS identity_edge (
  edge_id TEXT PRIMARY KEY,
  entity_id TEXT NOT NULL,
  source_system TEXT NOT NULL,
  source_key TEXT NOT NULL,
  key_type TEXT NOT NULL,
  confidence DOUBLE NOT NULL,
  resolution_method TEXT NOT NULL,
  provenance JSON,
  model_version TEXT NOT NULL,
  _loaded_at TIMESTAMP DEFAULT now()
);
"""


def write_edges(edges: list[dict]) -> None:
    EDGES_DB.parent.mkdir(parents=True, exist_ok=True)
    EDGES_DB.unlink(missing_ok=True)
    con = duckdb.connect(str(EDGES_DB))
    try:
        con.execute(EDGES_DDL)
        con.execute("DELETE FROM identity_edge;")
        con.executemany(
            """INSERT INTO identity_edge
               (edge_id, entity_id, source_system, source_key, key_type,
                confidence, resolution_method, provenance, model_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    e["edge_id"], e["entity_id"], e["source_system"], e["source_key"],
                    e["key_type"], e["confidence"], e["resolution_method"],
                    json.dumps(e["provenance"]), e["model_version"],
                ) for e in edges
            ],
        )
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Build dim_user + facts in the warehouse
# ---------------------------------------------------------------------------

def build_dim_user(unstop, signups, edges) -> list[dict]:
    """Resolve each backend signup into a canonical dim_user row.

    identity_confidence = MIN over all merge edges (anti-merge edges with
    confidence -1.0 are recorded but do not lower the resolution confidence;
    they flag a constraint, not a stitching weakness — we surface that via
    identity_flags instead).
    """
    edges_by_entity: dict[str, list[dict]] = defaultdict(list)
    for e in edges:
        edges_by_entity[e["entity_id"]].append(e)

    unstop_by_local: dict[str, dict] = {_local_part(u["college_email"]): u for u in unstop}

    rows = []
    for s in signups:
        entity_id = s["user_id"]
        entity_edges = edges_by_entity.get(entity_id, [])
        merge_edges = [e for e in entity_edges if e["confidence"] >= 0]
        anti = [e for e in entity_edges if e["confidence"] < 0]

        if merge_edges:
            min_conf = min(e["confidence"] for e in merge_edges)
        else:
            # No edges — the backend signup wasn't matched to any Unstop row.
            min_conf = 0.30  # low-confidence unresolved
        flags = sorted({e["resolution_method"] for e in entity_edges})

        # Best-effort college_email lookup (from the matching Unstop row).
        college_email = None
        ll = _local_part(s["personal_email"])
        if ll in unstop_by_local:
            college_email = unstop_by_local[ll]["college_email"]

        rows.append(dict(
            user_id=entity_id,
            full_name=s["full_name"],
            personal_email=s["personal_email"],
            college_email=college_email,
            phone_hash=s.get("phone_hash"),
            device_fingerprint=s["device_fingerprint"],
            # City/tier are not on backend signups in our generator; left null
            # — the metric layer surfaces this as a data-quality gap.
            city="",
            city_tier="Tier-2",
            device_type="mobile" if s.get("platform") in ("android", "ios") else "desktop",
            occupation=None,
            age=None,
            college=None,
            identity_confidence=min_conf,
            identity_flags=flags,
            model_version=MODEL_VERSION,
            acquisition_source="unstop",  # universe is Unstop-only in v1
            signup_time=_parse_dt(s["signup_time"]),
        ))
    return rows


def load_warehouse(
    dim_user_rows: list[dict],
    unstop: list[dict],
    signups: list[dict],
    challenge_signups: list[dict],
    predictions: list[dict],
    outcomes: list[dict],
) -> None:
    from schema.workbook import apply_ddl, generate_all_ddl, SCHEMA_VERSION  # local to keep CLI import time low

    WAREHOUSE_DB.parent.mkdir(parents=True, exist_ok=True)
    WAREHOUSE_DB.unlink(missing_ok=True)
    con = duckdb.connect(str(WAREHOUSE_DB))

    con.execute(generate_all_ddl())

    # dim_challenge — single row.
    con.execute(
        "INSERT INTO dim_challenge "
        "(weekly_challenge_id, week_of, challenge_name, start_date, end_date, _source_system) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [WEEKLY_CHALLENGE_ID, WEEK_OF, "Weekly Challenge — Jan W1", "2024-01-01", "2024-01-07", "static"],
    )

    # dim_user
    con.executemany(
        """INSERT INTO dim_user
           (user_id, full_name, personal_email, college_email, phone_hash,
            device_fingerprint, city, city_tier, device_type, occupation, age,
            college, identity_confidence, identity_flags, model_version,
            acquisition_source, signup_time, _source_system)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (
                r["user_id"], r["full_name"], r["personal_email"], r["college_email"], r["phone_hash"],
                r["device_fingerprint"], r["city"], r["city_tier"], r["device_type"], r["occupation"], r["age"],
                r["college"], r["identity_confidence"], r["identity_flags"], r["model_version"],
                r["acquisition_source"], r["signup_time"], "resolve.py",
            ) for r in dim_user_rows
        ],
    )

    # fact_acquisition — one row per Unstop registration (the only source
    # we hardwire to a user in v1; broader attribution lives in a later pass).
    unstop_by_local = {_local_part(u["college_email"]): u for u in unstop}
    acq_rows = []
    for s in signups:
        local = _local_part(s["personal_email"])
        u = unstop_by_local.get(local)
        if not u:
            continue
        acq_rows.append((
            f"AQ-{s['user_id'][:12]}",
            s["user_id"],
            WEEKLY_CHALLENGE_ID,
            "unstop",
            u.get("utm_source"),
            u.get("utm_campaign"),
            _parse_dt(u["registration_time"]),
            "unstop_csv",
        ))
    con.executemany(
        """INSERT INTO fact_acquisition
           (acquisition_id, user_id, weekly_challenge_id, touchpoint_source,
            utm_source, utm_campaign, touchpoint_at, _source_system)
           VALUES (?,?,?,?,?,?,?,?)""",
        acq_rows,
    )

    # fact_engagement — challenge_signups (the rest of the engagement spectrum
    # is captured in fact_prediction; participation = made >= 1 prediction).
    eng_rows = []
    for c in challenge_signups:
        eng_rows.append((
            f"EN-CS-{c['user_id'][:12]}",
            c["user_id"],
            c["weekly_challenge_id"],
            "challenge_signup",
            _parse_dt(c["signup_time"]),
            json.dumps({}),
            "backend.ndjson",
        ))
    con.executemany(
        """INSERT INTO fact_engagement
           (engagement_id, user_id, weekly_challenge_id, event_type, event_at, properties, _source_system)
           VALUES (?,?,?,?,?,?,?)""",
        eng_rows,
    )

    # fact_prediction — load made events, then UPDATE in place with the
    # deferred outcomes file. This models the deferred-join semantically.
    pred_rows = []
    for p in predictions:
        pred_rows.append((
            p["prediction_id"], p["user_id"], p["stock_symbol"], p["direction"],
            p["confidence_stars"], _parse_dt(p["made_at"]),
            None, None, None, None, False, "backend.ndjson",
        ))
    con.executemany(
        """INSERT INTO fact_prediction
           (prediction_id, user_id, stock_symbol, direction, confidence_stars,
            made_at, outcome, pnl_points, accuracy_delta, resolved_at,
            is_outcome_resolved, _source_system)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        pred_rows,
    )
    # Apply outcomes (deferred join).
    for o in outcomes:
        con.execute(
            """UPDATE fact_prediction
               SET outcome = ?, pnl_points = ?, accuracy_delta = ?,
                   resolved_at = ?, is_outcome_resolved = TRUE
               WHERE prediction_id = ?""",
            [o["outcome"], o["pnl_points"], o["accuracy_delta"], _parse_dt(o["resolved_at"]), o["prediction_id"]],
        )

    # audit_log
    con.execute(
        """INSERT INTO audit_log
           (run_id, run_at, pipeline_stage, input_row_count, output_row_count,
            identity_stats, notes, _source_system)
           VALUES (?, now(), 'resolve', ?, ?, ?, ?, 'resolve.py')""",
        [
            str(uuid.uuid4()),
            len(unstop) + len(signups),
            len(dim_user_rows),
            json.dumps(_resolution_stats(dim_user_rows)),
            f"schema_version={SCHEMA_VERSION}",
        ],
    )

    con.close()


def _resolution_stats(dim_user_rows: list[dict]) -> dict:
    high = mid = low = blocked_flag = 0
    for r in dim_user_rows:
        if "blocked_shared_device" in r["identity_flags"]:
            blocked_flag += 1
        c = r["identity_confidence"]
        if c >= 0.85:
            high += 1
        elif c >= 0.60:
            mid += 1
        else:
            low += 1
    total = len(dim_user_rows) or 1
    return dict(
        total=total,
        high_confidence=high,
        medium_confidence=mid,
        low_confidence=low,
        blocked_shared_device=blocked_flag,
        high_confidence_pct=round(100 * high / total, 2),
        medium_confidence_pct=round(100 * mid / total, 2),
        low_confidence_pct=round(100 * low / total, 2),
    )


def print_report(dim_user_rows: list[dict], edges: list[dict], unresolved: int) -> None:
    stats = _resolution_stats(dim_user_rows)
    total_edges = len(edges)
    by_method: dict[str, int] = defaultdict(int)
    for e in edges:
        by_method[e["resolution_method"]] += 1

    print(f"\nIdentity Resolution Report — {MODEL_VERSION}")
    print(f"Total source records:     {stats['total']}")
    print(f"Entities resolved:        {stats['total']}")
    print(f"  High confidence (>=0.85): {stats['high_confidence']} ({stats['high_confidence_pct']}%)")
    print(f"  Medium confidence (0.60-0.84): {stats['medium_confidence']} ({stats['medium_confidence_pct']}%)")
    print(f"  Low confidence (<0.60): {stats['low_confidence']} ({stats['low_confidence_pct']}%)")
    print(f"  Blocked (shared device): {stats['blocked_shared_device']}")
    print(f"Unresolved signals:       {unresolved}")
    print(f"Total edges:              {total_edges}")
    for method, count in sorted(by_method.items()):
        print(f"  {method}: {count}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    print("Loading raw data ...", file=sys.stderr)
    unstop = load_unstop()
    signups, challenge_signups, predictions = load_backend()
    outcomes = load_outcomes()
    posthog_by_user = load_posthog_sessions()
    print(f"  unstop={len(unstop)}  signups={len(signups)}  predictions={len(predictions)}  outcomes={len(outcomes)}", file=sys.stderr)

    print("Pass 1 — deterministic email match ...", file=sys.stderr)
    p1_edges, matched_u, matched_s = pass1_deterministic(unstop, signups)
    print(f"  pass1 matched: {len(matched_u)} unstop rows / {len(matched_s)} backend signups", file=sys.stderr)

    print("Pass 2 — fuzzy name+device ...", file=sys.stderr)
    p2_edges = pass2_fuzzy(unstop, signups, matched_u, matched_s)
    print(f"  pass2 produced: {len(p2_edges)} edges", file=sys.stderr)

    print("Pass 3 — anti-merge for shared-device with session overlap ...", file=sys.stderr)
    p3_edges = pass3_anti_merge(signups, posthog_by_user)
    print(f"  pass3 produced: {len(p3_edges)} anti-merge edges", file=sys.stderr)

    edges = p1_edges + p2_edges + p3_edges
    write_edges(edges)
    print(f"wrote {EDGES_DB} edges={len(edges)}", file=sys.stderr)

    dim_user_rows = build_dim_user(unstop, signups, edges)

    # Unresolved Unstop rows: those whose college_email is in NO edge.
    edge_keys = {e["source_key"] for e in edges if e["source_system"] == "unstop"}
    unresolved = sum(1 for u in unstop if u["college_email"] not in edge_keys)

    load_warehouse(dim_user_rows, unstop, signups, challenge_signups, predictions, outcomes)
    print(f"wrote {WAREHOUSE_DB}", file=sys.stderr)

    print_report(dim_user_rows, edges, unresolved)


if __name__ == "__main__":
    main()
