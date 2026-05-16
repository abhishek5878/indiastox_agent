"""Seed the IndiaStox Weekly Metabase dashboard via the Metabase API.

Idempotent: re-running checks for existing assets by name and skips them
rather than duplicating. Operates on a Metabase you've already brought
up via `docker compose up -d`.

Configure via env vars (or .env at repo root):

  METABASE_URL=http://localhost:3000
  METABASE_USER=<admin email>
  METABASE_PASS=<admin password>
  METABASE_DUCKDB_PATH=/warehouse/indiastox.duckdb    # path INSIDE the container

The four cards read from `metric_results` for the typed-confidence
metrics (Q2 channel attribution) and the underlying facts for the funnel
(Q1) and identity-quality (Q4). This enforces the "metric defined once"
contract: the dashboard never re-computes the metric values that the
metric layer is authoritative for; it queries the materialization.

If Metabase isn't running, this script reports a connection error and
exits non-zero. That's deliberate — no silent failures.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: `requests` not installed. Run: pip install requests", file=sys.stderr)
    sys.exit(2)

from dotenv import load_dotenv

_REPO = Path(__file__).resolve().parents[1]
load_dotenv(_REPO / ".env")

MB_URL = os.environ.get("METABASE_URL", "http://localhost:3000").rstrip("/")
MB_USER = os.environ.get("METABASE_USER")
MB_PASS = os.environ.get("METABASE_PASS")
DUCKDB_PATH_IN_CONTAINER = os.environ.get("METABASE_DUCKDB_PATH", "/warehouse/indiastox.duckdb")

DB_NAME = "IndiaStox DuckDB"
DASHBOARD_NAME = "IndiaStox Weekly"

CARDS = [
    dict(
        name="Q1 — Weekly Challenge Funnel (Unstop cohort, strict-subset)",
        sql="""
WITH unstop_users AS (
  SELECT DISTINCT user_id FROM fact_acquisition WHERE touchpoint_source = 'unstop'
),
signed_up AS (
  SELECT DISTINCT user_id FROM fact_engagement
  WHERE event_type = 'challenge_signup' AND user_id IN (SELECT user_id FROM unstop_users)
),
predicted AS (
  SELECT DISTINCT user_id FROM fact_prediction
  WHERE user_id IN (SELECT user_id FROM signed_up)
),
outcome AS (
  SELECT DISTINCT user_id FROM fact_prediction
  WHERE is_outcome_resolved AND user_id IN (SELECT user_id FROM predicted)
)
SELECT 'unstop_registered' AS step, (SELECT COUNT(*) FROM unstop_users) AS n
UNION ALL SELECT 'challenge_signed_up', (SELECT COUNT(*) FROM signed_up)
UNION ALL SELECT 'made_a_prediction',  (SELECT COUNT(*) FROM predicted)
UNION ALL SELECT 'outcome_resolved',   (SELECT COUNT(*) FROM outcome)
""".strip(),
        display="bar",
    ),
    dict(
        name="Q2 — Channel Attribution (reads metric_results)",
        sql="""
SELECT
  SPLIT_PART(breakdown_key, '=', 2) AS acquisition_source,
  ROUND(value * 100, 1) AS ghost_rate_pct,
  sample_n AS cohort_size
FROM metric_results
WHERE metric_name = 'ghost_rate' AND breakdown_key LIKE 'by_source=%'
ORDER BY value DESC
""".strip(),
        display="table",
    ),
    dict(
        name="Q3 — Cohort Retention (W01 cohort, day-by-day activity)",
        sql="""
WITH cohort AS (
  SELECT user_id FROM dim_user
  WHERE signup_time >= TIMESTAMP '2024-01-01' AND signup_time < TIMESTAMP '2024-01-08'
),
active_day AS (
  SELECT user_id,
         date_diff('day', TIMESTAMP '2024-01-01', made_at) AS day_index
  FROM fact_prediction
  WHERE user_id IN (SELECT user_id FROM cohort)
)
SELECT day_index,
       COUNT(DISTINCT user_id) AS active_users,
       ROUND(COUNT(DISTINCT user_id) * 100.0 / (SELECT COUNT(*) FROM cohort), 1) AS pct_of_cohort
FROM active_day
WHERE day_index BETWEEN 0 AND 6
GROUP BY day_index
ORDER BY day_index
""".strip(),
        display="bar",
    ),
    dict(
        name="Q4 — Identity Resolution Quality",
        sql="""
SELECT
  ROUND(SUM(CASE WHEN identity_confidence >= 0.85 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1)
    AS high_confidence_pct,
  ROUND(SUM(CASE WHEN identity_confidence BETWEEN 0.60 AND 0.8499 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1)
    AS medium_confidence_pct,
  ROUND(SUM(CASE WHEN identity_confidence < 0.60 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1)
    AS low_confidence_pct,
  ROUND(SUM(CASE WHEN list_contains(identity_flags, 'blocked_shared_device') THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1)
    AS blocked_pct
FROM dim_user
""".strip(),
        display="scalar",
    ),
]


# ---------------------------------------------------------------------------
# Metabase API client
# ---------------------------------------------------------------------------

class MB:
    def __init__(self, url: str, user: str, password: str):
        self.url = url
        self.session = requests.Session()
        r = self.session.post(f"{url}/api/session", json={"username": user, "password": password}, timeout=10)
        r.raise_for_status()
        self.session.headers["X-Metabase-Session"] = r.json()["id"]

    def get_json(self, path: str):
        r = self.session.get(f"{self.url}{path}", timeout=10)
        r.raise_for_status()
        return r.json()

    def post_json(self, path: str, payload: dict):
        r = self.session.post(f"{self.url}{path}", json=payload, timeout=30)
        r.raise_for_status()
        return r.json()


def ensure_database(mb: MB) -> int:
    dbs = mb.get_json("/api/database")
    dbs = dbs.get("data", dbs)  # newer Metabase wraps in {"data": [...]}
    for db in dbs:
        if db["name"] == DB_NAME and db["engine"].lower().startswith("duck"):
            print(f"  database '{DB_NAME}' already registered (id={db['id']})", file=sys.stderr)
            return db["id"]
    payload = dict(
        name=DB_NAME,
        engine="duckdb",
        details=dict(database_file=DUCKDB_PATH_IN_CONTAINER, read_only=True),
    )
    out = mb.post_json("/api/database", payload)
    print(f"  registered database '{DB_NAME}' (id={out['id']})", file=sys.stderr)
    return out["id"]


def ensure_card(mb: MB, db_id: int, card: dict) -> int:
    existing = mb.get_json("/api/card")
    existing = existing.get("data", existing)
    for c in existing:
        if c["name"] == card["name"]:
            print(f"  card '{card['name']}' already exists (id={c['id']})", file=sys.stderr)
            return c["id"]
    payload = dict(
        name=card["name"],
        dataset_query=dict(type="native", native=dict(query=card["sql"]), database=db_id),
        display=card.get("display", "table"),
        visualization_settings={},
    )
    out = mb.post_json("/api/card", payload)
    print(f"  created card '{card['name']}' (id={out['id']})", file=sys.stderr)
    return out["id"]


def ensure_dashboard(mb: MB, card_ids: list[int]) -> int:
    existing = mb.get_json("/api/dashboard")
    existing = existing.get("data", existing)
    for d in existing:
        if d["name"] == DASHBOARD_NAME:
            print(f"  dashboard '{DASHBOARD_NAME}' already exists (id={d['id']})", file=sys.stderr)
            return d["id"]
    payload = dict(name=DASHBOARD_NAME, description="Generated by dashboard/seed.py — 4 panels from the brief")
    out = mb.post_json("/api/dashboard", payload)
    dash_id = out["id"]
    print(f"  created dashboard '{DASHBOARD_NAME}' (id={dash_id})", file=sys.stderr)
    # Attach cards in a 2×2 grid.
    layouts = [(0, 0, 12, 6), (12, 0, 12, 6), (0, 6, 12, 6), (12, 6, 12, 6)]
    for card_id, (x, y, w, h) in zip(card_ids, layouts):
        mb.post_json(
            f"/api/dashboard/{dash_id}/cards",
            dict(cardId=card_id, parameter_mappings=[], visualization_settings={},
                 size_x=w, size_y=h, col=x, row=y),
        )
    print(f"  attached {len(card_ids)} cards to dashboard", file=sys.stderr)
    return dash_id


def main() -> None:
    if not MB_USER or not MB_PASS:
        print("ERROR: set METABASE_USER and METABASE_PASS (env or .env at repo root).", file=sys.stderr)
        print("Quick start:", file=sys.stderr)
        print("  docker compose up -d", file=sys.stderr)
        print("  # complete first-run setup at http://localhost:3000", file=sys.stderr)
        print("  export METABASE_URL=http://localhost:3000", file=sys.stderr)
        print("  export METABASE_USER=you@example.com", file=sys.stderr)
        print("  export METABASE_PASS=<your password>", file=sys.stderr)
        print("  python3 -m dashboard.seed", file=sys.stderr)
        sys.exit(2)

    print(f"Connecting to Metabase at {MB_URL} ...", file=sys.stderr)
    try:
        mb = MB(MB_URL, MB_USER, MB_PASS)
    except requests.exceptions.ConnectionError as e:
        print(f"ERROR: cannot reach Metabase at {MB_URL}. Is it running?", file=sys.stderr)
        print("       docker compose up -d", file=sys.stderr)
        sys.exit(2)
    except requests.exceptions.HTTPError as e:
        print(f"ERROR: authentication failed: {e}", file=sys.stderr)
        sys.exit(2)

    db_id = ensure_database(mb)
    card_ids = [ensure_card(mb, db_id, c) for c in CARDS]
    dash_id = ensure_dashboard(mb, card_ids)
    print(f"\nDashboard ready: {MB_URL}/dashboard/{dash_id}", file=sys.stderr)


if __name__ == "__main__":
    main()
