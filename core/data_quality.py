"""Data-quality scanner — surfaces what the pipeline deliberately injects.

The brief calls out "data quality issue the pipeline must flag, not
silently accept" as a failure mode. The synthetic generator injects
three known anomalies; this module finds them and writes alert rows
to `audit_log` so a downstream agent (or human) can react.

Checks:

  1. Klaviyo clock-skew — `email_opened` events whose timestamp
     precedes the corresponding `email_sent`. Generator injects 5%.
  2. Future-dated events — any event with timestamp > now().
     Should be zero in this dataset; non-zero means a clock-skew
     bug at the producer side.
  3. Orphan clicks — `email_clicked` rows whose email never appears
     in `email_sent`. Should be zero; non-zero means a join
     attribution gap.

Each function returns a structured summary; the top-level
`scan_and_audit()` writes each finding as a row in `audit_log`
with `pipeline_stage='data_quality'` and a `notes` string the
agent can read.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

WAREHOUSE_DB = _REPO / "warehouse" / "indiastox.duckdb"
RAW_KLAVIYO = _REPO / "raw" / "klaviyo_events.ndjson"


def find_klaviyo_clock_skew() -> dict[str, Any]:
    """email_opened.timestamp < paired email_sent.timestamp.

    The Klaviyo stream doesn't carry an explicit (sent, opened) link;
    we pair by (email, campaign_id) — the first send and the first
    open per pair. If the open is timestamped earlier than the send,
    that's a producer-side clock-skew anomaly.
    """
    if not RAW_KLAVIYO.exists():
        return dict(found=0, total=0, rate=0.0, sample=[], detail="raw/klaviyo_events.ndjson missing")

    sql = f"""
        WITH events AS (
          SELECT * FROM read_json_auto('{RAW_KLAVIYO}')
        ),
        sent AS (
          SELECT email, campaign_id, MIN(timestamp::TIMESTAMP) AS sent_at
          FROM events WHERE event_type = 'email_sent'
          GROUP BY email, campaign_id
        ),
        opened AS (
          SELECT email, campaign_id, MIN(timestamp::TIMESTAMP) AS opened_at
          FROM events WHERE event_type = 'email_opened'
          GROUP BY email, campaign_id
        ),
        paired AS (
          SELECT s.email, s.campaign_id, s.sent_at, o.opened_at,
                 date_diff('second', s.sent_at, o.opened_at) AS gap_seconds
          FROM sent s JOIN opened o ON s.email = o.email AND s.campaign_id = o.campaign_id
        )
        SELECT
          (SELECT COUNT(*) FROM paired) AS total_pairs,
          (SELECT COUNT(*) FROM paired WHERE gap_seconds < 0) AS skew_count,
          (SELECT json_group_array(json_object('email', email, 'gap_seconds', gap_seconds))
             FROM (SELECT email, gap_seconds FROM paired WHERE gap_seconds < 0 LIMIT 5)) AS sample
    """
    con = duckdb.connect(":memory:")
    try:
        total, found, sample_json = con.execute(sql).fetchone()
    finally:
        con.close()
    total = int(total or 0)
    found = int(found or 0)
    return dict(
        found=found,
        total=total,
        rate=(found / total) if total else 0.0,
        sample=json.loads(sample_json or "[]"),
    )


def find_future_dated_events() -> dict[str, Any]:
    """Any fact event with timestamp > now."""
    if not WAREHOUSE_DB.exists():
        return dict(found=0, detail="warehouse not built")
    sql = """
        SELECT 'fact_prediction.made_at' AS where_field, COUNT(*)
        FROM fact_prediction WHERE made_at > now()
        UNION ALL
        SELECT 'fact_engagement.event_at', COUNT(*)
        FROM fact_engagement WHERE event_at > now()
        UNION ALL
        SELECT 'fact_acquisition.touchpoint_at', COUNT(*)
        FROM fact_acquisition WHERE touchpoint_at > now()
    """
    con = duckdb.connect(str(WAREHOUSE_DB), read_only=False)
    try:
        rows = con.execute(sql).fetchall()
    finally:
        con.close()
    total = sum(int(r[1] or 0) for r in rows)
    return dict(found=total, by_field={r[0]: int(r[1] or 0) for r in rows if int(r[1] or 0) > 0})


def find_orphan_clicks() -> dict[str, Any]:
    """email_clicked rows whose email never appears in email_sent."""
    if not RAW_KLAVIYO.exists():
        return dict(found=0, detail="raw/klaviyo_events.ndjson missing")
    sql = f"""
        WITH events AS (
          SELECT * FROM read_json_auto('{RAW_KLAVIYO}')
        ),
        sent_emails AS (
          SELECT DISTINCT email FROM events WHERE event_type = 'email_sent'
        )
        SELECT COUNT(DISTINCT email) FROM events
        WHERE event_type = 'email_clicked'
          AND email NOT IN (SELECT email FROM sent_emails)
    """
    con = duckdb.connect(":memory:")
    try:
        n = int(con.execute(sql).fetchone()[0] or 0)
    finally:
        con.close()
    return dict(found=n)


def _write_audit_row(con, kind: str, payload: dict, notes: str) -> str:
    rid = f"dq-{uuid.uuid4().hex[:12]}"
    con.execute(
        """INSERT INTO audit_log
           (run_id, run_at, pipeline_stage, input_row_count, output_row_count,
            identity_stats, notes, _source_system)
           VALUES (?, ?, 'data_quality', NULL, ?, ?, ?, 'core.data_quality')""",
        [rid, datetime.now(timezone.utc).replace(tzinfo=None),
         int(payload.get("found", 0)), json.dumps(payload, default=str), notes],
    )
    return rid


def scan_and_audit(*, verbose: bool = True) -> dict[str, Any]:
    """Run all three checks. Write an audit_log row per finding.

    Returns a summary dict. Idempotent: an existing data_quality row for
    the same kind on the same calendar day is left alone (we'd produce
    duplicates on every pipeline run otherwise).
    """
    skew = find_klaviyo_clock_skew()
    future = find_future_dated_events()
    orphan = find_orphan_clicks()

    con = duckdb.connect(str(WAREHOUSE_DB), read_only=False)
    try:
        # Skip duplicates from earlier today.
        existing = con.execute(
            """SELECT notes FROM audit_log
               WHERE pipeline_stage = 'data_quality'
                 AND date_trunc('day', run_at) = date_trunc('day', now())"""
        ).fetchall()
        today_notes = {r[0] for r in existing}

        for kind, payload, note in [
            ("klaviyo_clock_skew", skew,
             f"klaviyo_clock_skew: {skew['found']}/{skew['total']} pairs ({skew['rate']:.1%}) have email_opened.ts < email_sent.ts"),
            ("future_dated_events", future,
             f"future_dated_events: {future['found']} fact rows with timestamp > now"),
            ("orphan_clicks", orphan,
             f"orphan_clicks: {orphan['found']} email_clicked rows with no matching email_sent"),
        ]:
            if note in today_notes:
                if verbose:
                    print(f"  skip (already logged today): {note}", file=sys.stderr)
                continue
            rid = _write_audit_row(con, kind, payload, note)
            if verbose:
                print(f"  wrote audit_log row {rid}: {note}", file=sys.stderr)
    finally:
        con.close()

    return dict(klaviyo_clock_skew=skew, future_dated_events=future, orphan_clicks=orphan)


if __name__ == "__main__":
    print("Scanning for data-quality anomalies …", file=sys.stderr)
    summary = scan_and_audit()
    print(json.dumps(summary, indent=2, default=str))
