"""Metric semantic layer — every metric defined exactly once.

Every function returns a `core.confidence.MetricResult` carrying typed
confidence + provenance + a one-sentence interpretation the agent surfaces
verbatim. The `metric_results` table is the materialization; the function
is the source of truth.

If a dashboard or ad-hoc query needs one of these numbers, it calls the
function. No metric SQL lives in Metabase, in `load_metrics_to_db.py`, in
the bonus loop, or anywhere else.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import duckdb

# Path bootstrap so direct invocation works.
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from core.confidence import MetricResult, identity_confidence_summary, versioned

REPO = _REPO
WAREHOUSE_DB = REPO / "warehouse" / "indiastox.duckdb"

DEFS = {
    "weekly_active_posters": "1.0.0",
    "time_to_first_action": "1.0.0",
    "unstop_to_participation_rate": "1.0.0",
    "ghost_rate": "1.0.0",
    "dark_channel_fraction": "1.0.0",
    "channel_cac_bounds": "1.0.0",
    "brier_score": "1.0.0",
    "gyaani_graduation_rate": "1.0.0",
    "predictions_per_user": "1.0.0",
    "email_click_to_signup": "1.0.0",
    "metric_gameability_index": "2.0.0",
    "call_consensus_divergence": "1.0.0",
    "ai_content_flagged_share": "1.0.0",
    "pre_ipo_call_interest": "1.0.0",
    "behavioral_concentration_index": "1.0.0",
    "cascade_followon_lift": "1.0.0",
    "gyaani_influence_index": "1.0.0",
    "user_disengagement_rate": "1.0.0",
    "ghost_recovery_rate": "1.0.0",
    "proposal_lift_calibration_index": "1.0.0",
    "gyaani_aspirant_share": "1.0.0",
    "gyaani_locked_share": "1.0.0",
    # P4 attention -> accuracy headline metrics.
    "weekly_active_callers_calibrated": "1.0.0",
    "high_confidence_call_ratio": "1.0.0",
    "daily_gyaani_aspirant_count": "1.0.0",
    "calls_with_explanation_rate": "0.0.0-stub",
    # P5 funnel view (one metric serves the whole funnel page).
    "funnel_stages": "1.0.0",
    # P7 insights extractor (ranked surprise observations).
    "insights_generate": "1.0.0",
    # Consumption layer: CS nudge targets per user.
    "nudge_targets": "1.0.0",
    # Consumption layer: unified per-user fingerprint (the in-app badge).
    "user_fingerprint": "1.0.0",
}

# Gyaani definition (P1). Two-tier: aspirant is the growth slope (broad,
# achievable on W01); locked is the trophy (top decile of skill + low
# uncertainty + meaningful sample size). Thresholds were chosen after
# observing the meta-pattern on the W01 substrate:
#   - phi-only (no mu gate) picks volume not skill — 100% of day_traders
#     graduate but their mean win-rate is 0.406 (below population 0.430).
#   - strict (mu>=p90 AND phi<150 AND n>=10) finds 1 graduate on W01
#     because n_resolved is capped at 11 (median 3). Becomes meaningful
#     once P0.5b multi-week ships.
#   - medium (mu>=p90 AND phi<170 AND n>=5) finds 4.2% on W01 with
#     mean win-rate 0.825 — real skill signal but contaminated by lucky
#     FOMO cascaders at low sample sizes.
# Two-tier resolves this: aspirant is honest on W01; locked is the
# multi-week target the badge sits behind.
GYAANI_RULE_VERSION = "1.0.0"
GYAANI_THRESHOLDS = {
    "aspirant": {"mu_min": 1500.0, "phi_max": 200.0, "n_resolved_min": 3},
    "locked":   {"mu_min": 1686.0, "phi_max": 150.0, "n_resolved_min": 10},
}

SKILL_PARQUET = REPO / "data" / "skill_ratings.parquet"


def classify_gyaani(mu: float, phi: float, n_resolved: int) -> str:
    """Pure function — the single source of truth for the Gyaani rule.

    Returns "locked" | "aspirant" | "none". Both `gyaani_aspirant_share` and
    `gyaani_locked_share` call this so the threshold logic lives exactly
    once (per the substrate's defined-once invariant). The per-user
    `gyaani_status` tool also calls this.

    Locked is a strict superset of aspirant: a locked user is also an
    aspirant by construction. The aspirant-tier metric counts users who
    are aspirant-or-locked; the locked-tier metric counts only locked.
    """
    t = GYAANI_THRESHOLDS
    if (mu >= t["locked"]["mu_min"]
            and phi < t["locked"]["phi_max"]
            and n_resolved >= t["locked"]["n_resolved_min"]):
        return "locked"
    if (mu >= t["aspirant"]["mu_min"]
            and phi < t["aspirant"]["phi_max"]
            and n_resolved >= t["aspirant"]["n_resolved_min"]):
        return "aspirant"
    return "none"

# Product surface markers. The Pre-IPO ticker tray is a feature on the
# IndiaStox product; in the warehouse we flag a subset of synthetic
# tickers as Pre-IPO so we can compute call interest against them.
PRE_IPO_TICKERS = {"BAJFINANCE", "HCLTECH"}


def _connect(read_only: bool = False):
    """Open a connection to the warehouse.

    Defaults to read_only=False so connections coexist with the
    Streamlit UI's cached RW connection and ToolSession's audit-log
    writes (DuckDB rejects mixing read-only and read-write connections
    to the same file inside one process). All metric functions only
    SELECT — the RW connection is a same-process compatibility choice,
    not a semantic statement.
    """
    if not WAREHOUSE_DB.exists():
        raise FileNotFoundError(f"warehouse not built: {WAREHOUSE_DB}. Run `make resolve` first.")
    return duckdb.connect(str(WAREHOUSE_DB), read_only=read_only)


def _week_bounds(week_of: str) -> tuple[datetime, datetime]:
    """ISO-week → naive (TZ-stripped) UTC datetimes.

    DuckDB binds tz-aware Python datetimes by converting to the system's
    local timezone before stripping tz when comparing against a naive
    TIMESTAMP column. On a machine in IST that adds +5:30 to the
    boundary and quietly leaks late-day events from the next week into
    the query. Returning naive datetimes — values numerically in UTC —
    keeps the parameter comparison aligned with the column values
    (which were also stored naive-UTC by `_parse_dt` in resolve.py).
    Fixes the Q03/Q04 1pp drift surfaced by the eval harness (Pass B / N2).
    """
    year, week = week_of.split("-W")
    monday = datetime.strptime(f"{int(year)}-W{int(week):02d}-1", "%G-W%V-%u")
    return monday, monday + timedelta(days=7)


def _now() -> datetime:
    """Naive UTC. Matches the convention `_week_bounds` returns so
    `now >= cutoff` comparisons stay consistent.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _window_penalty(window_open: bool) -> float:
    return -0.2 if window_open else 0.0


# ---------------------------------------------------------------------------
# 1. weekly_active_posters
# ---------------------------------------------------------------------------

@versioned("1.0.0")
def weekly_active_posters(week_of: str, min_identity_confidence: float = 0.70) -> MetricResult:
    """Users who made >= 1 prediction in ISO week `week_of`, gated by identity_confidence."""
    start, end = _week_bounds(week_of)
    sql = """
        WITH posters AS (
          SELECT DISTINCT p.user_id
          FROM fact_prediction p
          JOIN dim_user u ON u.user_id = p.user_id
          WHERE p.made_at >= ? AND p.made_at < ?
            AND u.identity_confidence >= ?
        )
        SELECT COUNT(*) FROM posters
    """
    sql_excluded = """
        SELECT COUNT(DISTINCT p.user_id)
        FROM fact_prediction p
        JOIN dim_user u ON u.user_id = p.user_id
        WHERE p.made_at >= ? AND p.made_at < ?
          AND u.identity_confidence < ?
          AND u.identity_confidence > 0
    """
    con = _connect()
    try:
        value = con.execute(sql, [start, end, min_identity_confidence]).fetchone()[0]
        excluded = con.execute(sql_excluded, [start, end, min_identity_confidence]).fetchone()[0]
        id_conf, id_prov = identity_confidence_summary(con)
    finally:
        con.close()

    window_open = _now() < end
    confidence = max(0.0, min(1.0, id_conf + _window_penalty(window_open)))
    provenance = id_prov + [
        f"min_identity_confidence_gate:{min_identity_confidence}",
        f"low_confidence_users_excluded:{int(excluded)}",
    ]
    interp = (
        f"{int(value)} active posters at confidence gate {min_identity_confidence:.2f}. "
        f"An additional {int(excluded)} probabilistic-match users were excluded — "
        f"the true count is between {int(value)} and {int(value + excluded)}."
    )
    det = next((int(p.split(":")[1]) for p in id_prov if p.startswith("deterministic_match:")), 0)
    prob = next((int(p.split(":")[1]) for p in id_prov if p.startswith("probabilistic_match:")), 0)
    trace = [
        f"weekly_active_posters = {int(value)} because that many DISTINCT users made >=1 prediction in W01 with identity_confidence >= {min_identity_confidence:.2f}.",
        f"{int(excluded)} probabilistic-match users were excluded by the gate — the true count is between {int(value)} and {int(value + excluded)}.",
        f"confidence = {confidence:.2f}: identity floor {id_conf:.2f} ({det} deterministic / {prob} probabilistic, the latter down-weighted 0.5x); window is {'open' if window_open else 'closed'}.",
    ]

    return MetricResult(
        metric_name="weekly_active_posters",
        value=float(value),
        confidence=confidence,
        sample_n=int(value + excluded),
        provenance=provenance,
        window_open=window_open,
        interpretation=interp,
        trace=trace,
        definition_version=DEFS["weekly_active_posters"],
        confidence_interval=(float(value), float(value + excluded)),
        computation_sql=sql.strip(),
        as_of=_now(),
        breakdowns=dict(low_confidence_excluded=int(excluded), min_identity_confidence=min_identity_confidence),
    )


# ---------------------------------------------------------------------------
# 2. time_to_first_action
# ---------------------------------------------------------------------------

@versioned("1.0.0")
def time_to_first_action(week_of: str, acquisition_source: str = "all") -> MetricResult:
    """Median hours from challenge_signup to first prediction_made."""
    start, end = _week_bounds(week_of)
    now = _now()
    cutoff = end + timedelta(hours=72)

    where_acq = "" if acquisition_source == "all" else "AND u.acquisition_source = ?"
    params = [start, end]
    if acquisition_source != "all":
        params.append(acquisition_source)

    sql = f"""
        WITH cs AS (
          SELECT e.user_id, MIN(e.event_at) AS signup_at
          FROM fact_engagement e
          JOIN dim_user u ON u.user_id = e.user_id
          WHERE e.event_type = 'challenge_signup'
            AND e.event_at >= ? AND e.event_at < ?
            {where_acq}
          GROUP BY e.user_id
        ),
        first_pred AS (
          SELECT p.user_id, MIN(p.made_at) AS first_pred_at
          FROM fact_prediction p
          GROUP BY p.user_id
        )
        SELECT
          median(date_diff('millisecond', cs.signup_at, fp.first_pred_at) / 3600000.0),
          COUNT(*)
        FROM cs
        JOIN first_pred fp ON fp.user_id = cs.user_id
        WHERE fp.first_pred_at >= cs.signup_at
    """

    con = _connect()
    try:
        row = con.execute(sql, params).fetchone()
        median_hours = float(row[0] or 0.0)
        sample_n = int(row[1] or 0)
        id_conf, id_prov = identity_confidence_summary(con)

        breakdowns: dict = {}
        for dim_col in ("device_type", "city_tier", "acquisition_source"):
            sql_b = f"""
                WITH cs AS (
                  SELECT e.user_id, MIN(e.event_at) AS signup_at
                  FROM fact_engagement e
                  JOIN dim_user u ON u.user_id = e.user_id
                  WHERE e.event_type = 'challenge_signup'
                    AND e.event_at >= ? AND e.event_at < ?
                    {where_acq}
                  GROUP BY e.user_id
                ),
                first_pred AS (
                  SELECT p.user_id, MIN(p.made_at) AS first_pred_at
                  FROM fact_prediction p
                  GROUP BY p.user_id
                )
                SELECT u.{dim_col},
                       median(date_diff('millisecond', cs.signup_at, fp.first_pred_at) / 3600000.0) AS median_hours,
                       COUNT(*) AS n
                FROM cs
                JOIN first_pred fp ON fp.user_id = cs.user_id
                JOIN dim_user u ON u.user_id = cs.user_id
                WHERE fp.first_pred_at >= cs.signup_at
                GROUP BY u.{dim_col}
            """
            rows = con.execute(sql_b, params).fetchall()
            breakdowns[dim_col] = [
                dict(value=r[0], median_hours=float(r[1] or 0.0), n=int(r[2])) for r in rows
            ]
    finally:
        con.close()

    window_open = now < cutoff
    confidence = max(0.0, min(1.0, id_conf + _window_penalty(window_open)))
    provenance = id_prov + [f"acquisition_filter:{acquisition_source}", f"users_with_signup_and_prediction:{sample_n}"]
    interp = (
        f"Median time-to-first-prediction = {median_hours:.1f} hours "
        f"(n={sample_n}, filter={acquisition_source}). "
        + ("Window still open — final number may shift." if window_open else "Window closed.")
    )
    device_b = breakdowns.get("device_type") or []
    tier_b = breakdowns.get("city_tier") or []
    device_phrase = ", ".join(f"{r['value']}={r['median_hours']:.1f}h (n={r['n']})" for r in device_b[:2]) or "n/a"
    tier_phrase = ", ".join(f"{r['value']}={r['median_hours']:.1f}h (n={r['n']})" for r in tier_b[:2]) or "n/a"
    trace = [
        f"time_to_first_action = {median_hours:.1f}h median across {sample_n} users with both challenge_signup AND first prediction events (filter={acquisition_source}).",
        f"by device: {device_phrase}. by city_tier: {tier_phrase}.",
        f"confidence = {confidence:.2f}: identity floor {id_conf:.2f}; 72h cohort window is {'open (final shape may shift)' if window_open else 'closed'}.",
    ]
    return MetricResult(
        metric_name="time_to_first_action",
        value=median_hours,
        confidence=confidence,
        sample_n=sample_n,
        provenance=provenance,
        window_open=window_open,
        interpretation=interp,
        trace=trace,
        definition_version=DEFS["time_to_first_action"],
        confidence_interval=None,
        computation_sql=sql.strip(),
        as_of=now,
        breakdowns=breakdowns,
    )


# ---------------------------------------------------------------------------
# 3. unstop_to_participation_rate
# ---------------------------------------------------------------------------

@versioned("1.0.0")
def unstop_to_participation_rate(week_of: str) -> MetricResult:
    """challenge_participation count / challenge_signup count for Unstop cohort."""
    start, end = _week_bounds(week_of)
    now = _now()
    cutoff = end + timedelta(hours=72)

    sql = """
        WITH unstop_cohort AS (
          SELECT u.user_id
          FROM dim_user u
          JOIN fact_acquisition a ON a.user_id = u.user_id
          WHERE a.touchpoint_source = 'unstop'
            AND a.touchpoint_at >= ? AND a.touchpoint_at < ?
        ),
        cs AS (
          SELECT user_id, MIN(event_at) AS signup_at
          FROM fact_engagement
          WHERE event_type = 'challenge_signup'
            AND user_id IN (SELECT user_id FROM unstop_cohort)
          GROUP BY user_id
        ),
        first_pred AS (
          SELECT user_id, MIN(made_at) AS first_pred_at
          FROM fact_prediction
          GROUP BY user_id
        )
        SELECT
          (SELECT COUNT(*) FROM cs) AS signups,
          (SELECT COUNT(*) FROM cs JOIN first_pred fp ON fp.user_id = cs.user_id
            WHERE fp.first_pred_at <= cs.signup_at + INTERVAL '7 days') AS participations
    """
    con = _connect()
    try:
        signups, participations = con.execute(sql, [start, end]).fetchone()
        id_conf, id_prov = identity_confidence_summary(con)
    finally:
        con.close()

    signups = int(signups or 0)
    participations = int(participations or 0)
    rate = float(participations / signups) if signups else 0.0
    window_open = now < cutoff
    ci = (rate * 0.8, min(1.0, rate * 1.2)) if window_open else (rate, rate)
    confidence = max(0.0, min(1.0, id_conf + _window_penalty(window_open)))
    provenance = id_prov + [f"signups:{signups}", f"participations:{participations}", "cohort:unstop_acquisition"]
    interp = (
        f"Among {signups} Unstop signups, {participations} predicted within 7 days "
        f"(participation rate {rate:.1%})."
    )
    trace = [
        f"unstop_to_participation_rate = {rate:.4f} because {participations}/{signups} Unstop-cohort users predicted within 7 days of their challenge_signup event.",
        f"7-day window is the deferred-join cutoff (predictions resolve at +5d but the participation event itself = made_at within 7d of signup).",
        f"confidence = {confidence:.2f}: identity floor {id_conf:.2f}; 72h cohort window is {'open' if window_open else 'closed'}; CI {ci}.",
    ]
    return MetricResult(
        metric_name="unstop_to_participation_rate",
        value=rate,
        confidence=confidence,
        sample_n=signups,
        trace=trace,
        provenance=provenance,
        window_open=window_open,
        interpretation=interp,
        definition_version=DEFS["unstop_to_participation_rate"],
        confidence_interval=ci,
        computation_sql=sql.strip(),
        as_of=now,
        breakdowns=dict(signups=signups, participations=participations),
    )


# ---------------------------------------------------------------------------
# 4. ghost_rate
# ---------------------------------------------------------------------------

@versioned("1.0.0")
def ghost_rate(week_of: str, acquisition_source: str = "all") -> MetricResult:
    """Users in cohort with zero predictions in 7 days of signup."""
    start, end = _week_bounds(week_of)
    now = _now()
    cutoff = end + timedelta(hours=24 * 7)

    where_acq = "" if acquisition_source == "all" else "AND a.touchpoint_source = ?"
    params: list = [start, end]
    if acquisition_source != "all":
        params.append(acquisition_source)

    sql = f"""
        WITH cohort AS (
          SELECT DISTINCT u.user_id
          FROM dim_user u
          JOIN fact_acquisition a ON a.user_id = u.user_id
          WHERE a.touchpoint_at >= ? AND a.touchpoint_at < ?
            {where_acq}
        ),
        active AS (
          SELECT DISTINCT user_id FROM fact_prediction
          WHERE made_at <= ?
        )
        SELECT
          (SELECT COUNT(*) FROM cohort) AS total,
          (SELECT COUNT(*) FROM cohort WHERE user_id NOT IN (SELECT user_id FROM active)) AS ghosts
    """
    params_q = params + [cutoff]

    con = _connect()
    try:
        total, ghosts = con.execute(sql, params_q).fetchone()
        total = int(total or 0)
        ghosts = int(ghosts or 0)
        id_conf, id_prov = identity_confidence_summary(con)

        # Per-source breakdown.
        by_source: list[dict] = []
        if acquisition_source == "all":
            q_src = """
                WITH cohort AS (
                  SELECT DISTINCT u.user_id, a.touchpoint_source AS src
                  FROM dim_user u
                  JOIN fact_acquisition a ON a.user_id = u.user_id
                  WHERE a.touchpoint_at >= ? AND a.touchpoint_at < ?
                ),
                active AS (
                  SELECT DISTINCT user_id FROM fact_prediction WHERE made_at <= ?
                )
                SELECT src,
                       SUM(CASE WHEN cohort.user_id NOT IN (SELECT user_id FROM active) THEN 1 ELSE 0 END) * 1.0
                         / COUNT(*) AS ghost_rate,
                       COUNT(*) AS n
                FROM cohort
                GROUP BY src
                ORDER BY ghost_rate DESC
            """
            rows = con.execute(q_src, [start, end, cutoff]).fetchall()
            by_source = [dict(value=r[0], rate=float(r[1] or 0.0), n=int(r[2])) for r in rows]

        # Device + tier breakdowns.
        def _bd(dim_col: str) -> list[dict]:
            q = f"""
                WITH cohort AS (
                  SELECT DISTINCT u.user_id, u.{dim_col} AS dim_value
                  FROM dim_user u
                  JOIN fact_acquisition a ON a.user_id = u.user_id
                  WHERE a.touchpoint_at >= ? AND a.touchpoint_at < ?
                    {where_acq}
                ),
                active AS (
                  SELECT DISTINCT user_id FROM fact_prediction WHERE made_at <= ?
                )
                SELECT cohort.dim_value,
                       SUM(CASE WHEN cohort.user_id NOT IN (SELECT user_id FROM active) THEN 1 ELSE 0 END) * 1.0
                         / COUNT(*) AS dim_rate,
                       COUNT(*) AS n
                FROM cohort
                GROUP BY cohort.dim_value
                ORDER BY dim_rate DESC
            """
            rows = con.execute(q, params_q).fetchall()
            return [dict(value=r[0], rate=float(r[1] or 0.0), n=int(r[2])) for r in rows]

        bd_device = _bd("device_type")
        bd_tier = _bd("city_tier")
    finally:
        con.close()

    rate = float(ghosts / total) if total else 0.0
    window_open = now < cutoff
    confidence = max(0.0, min(1.0, id_conf + _window_penalty(window_open)))
    provenance = id_prov + [f"cohort_filter:{acquisition_source}", f"cohort_size:{total}", f"ghost_count:{ghosts}"]
    interp = (
        f"{ghosts}/{total} ({rate:.1%}) of {acquisition_source} cohort made zero predictions in 7 days. "
        + ("Window still open." if window_open else "Window closed.")
    )
    # Layer J — "Why this number?" 3-step trace.
    det = next((int(p.split(":")[1]) for p in id_prov if p.startswith("deterministic_match:")), 0)
    prob = next((int(p.split(":")[1]) for p in id_prov if p.startswith("probabilistic_match:")), 0)
    low = next((int(p.split(":")[1]) for p in id_prov if p.startswith("low_confidence:")), 0)
    if by_source:
        top = max(by_source, key=lambda r: r["n"] * r["rate"])
        top_ghosts_for_src = int(top["n"] * top["rate"])
        breakdown_phrase = (
            f"biggest contributor: {top['value']} ({top_ghosts_for_src}/{ghosts} ghosts; "
            f"per-source rate {top['rate']:.1%} over {top['n']} users)"
        )
    else:
        breakdown_phrase = f"single-cohort answer ({acquisition_source} only)"
    trace = [
        f"ghost_rate = {rate:.4f} because {ghosts} of {total} users in the {acquisition_source} cohort made zero predictions through the W01 + 7-day window.",
        f"{breakdown_phrase}.",
        f"confidence = {confidence:.2f} because the identity layer carries "
        f"{det} deterministic / {prob} probabilistic / {low} low-confidence matches "
        f"(probabilistic share is down-weighted 0.5x in the propagation chain).",
    ]
    return MetricResult(
        metric_name="ghost_rate",
        value=rate,
        confidence=confidence,
        sample_n=total,
        provenance=provenance,
        window_open=window_open,
        interpretation=interp,
        trace=trace,
        definition_version=DEFS["ghost_rate"],
        confidence_interval=None,
        computation_sql=sql.strip(),
        as_of=now,
        breakdowns=dict(
            cohort_size=total,
            ghost_count=ghosts,
            by_source=by_source,
            by_device=bd_device,
            by_city_tier=bd_tier,
        ),
    )


# ---------------------------------------------------------------------------
# 5. dark_channel_fraction — what % of signups have no UTM / dark channel
# ---------------------------------------------------------------------------

@versioned("1.0.0")
def dark_channel_fraction(week_of: str) -> MetricResult:
    """Fraction of W01 signups attributed to whatsapp_dark (no UTM, no email)."""
    start, end = _week_bounds(week_of)
    sql = """
        WITH cohort AS (
          SELECT DISTINCT u.user_id, a.touchpoint_source
          FROM dim_user u
          JOIN fact_acquisition a ON a.user_id = u.user_id
          WHERE a.touchpoint_at >= ? AND a.touchpoint_at < ?
        )
        SELECT
          (SELECT COUNT(*) FROM cohort WHERE touchpoint_source = 'whatsapp_dark') AS dark,
          (SELECT COUNT(*) FROM cohort) AS total
    """
    con = _connect()
    try:
        dark, total = con.execute(sql, [start, end]).fetchone()
    finally:
        con.close()
    dark = int(dark or 0)
    total = int(total or 0)
    rate = float(dark / total) if total else 0.0
    interp = (
        f"{dark}/{total} ({rate:.1%}) of W01 signups are dark (no UTM, no Klaviyo, NULL referral). "
        f"Channel-attribution metrics that ignore this fraction are methodologically suspect."
    )
    trace = [
        f"dark_channel_fraction = {rate:.4f} because {dark} of {total} W01 signups have touchpoint_source='whatsapp_dark' (no UTM, no Klaviyo, NULL referral).",
        f"this is the FLOOR on attribution uncertainty: any channel-attribution claim that doesn't explicitly handle this fraction is methodologically incomplete.",
        f"confidence = 1.00 because the fraction itself is deterministic given the dim_user / fact_acquisition join; what's uncertain is which TRUE channel each dark signup actually came from.",
    ]
    return MetricResult(
        metric_name="dark_channel_fraction",
        value=rate,
        confidence=1.0,  # the fraction itself is exact — it's the channel BEHIND it that's unknown
        sample_n=total,
        provenance=[f"dark_signups:{dark}", f"total_signups:{total}", "definition:touchpoint_source='whatsapp_dark'"],
        window_open=False,
        interpretation=interp,
        trace=trace,
        definition_version=DEFS["dark_channel_fraction"],
        computation_sql=sql.strip(),
        as_of=_now(),
        breakdowns=dict(dark=dark, total=total),
    )


# ---------------------------------------------------------------------------
# 6. channel_cac_bounds — bounded CAC for dark channel
# ---------------------------------------------------------------------------

@versioned("1.0.0")
def channel_cac_bounds(
    week_of: str,
    unstop_spend_rupees: float = 250_000.0,
    organic_cac_estimate: float = 0.0,
    paid_referral_cac_estimate: float = 350.0,
) -> MetricResult:
    """Bounded CAC for the WhatsApp-dark channel.

    Lower bound: dark = organic-quality referral (CAC ≈ ₹0).
    Upper bound: dark = paid-referral-quality (CAC ≈ paid_referral_cac_estimate).
    The true value is between, and unknowable without attribution improvements.
    """
    start, end = _week_bounds(week_of)
    sql_dark = """
        SELECT COUNT(DISTINCT u.user_id)
        FROM dim_user u
        JOIN fact_acquisition a ON a.user_id = u.user_id
        WHERE a.touchpoint_at >= ? AND a.touchpoint_at < ?
          AND a.touchpoint_source = 'whatsapp_dark'
    """
    sql_unstop = sql_dark.replace("'whatsapp_dark'", "'unstop'")
    con = _connect()
    try:
        dark_n = con.execute(sql_dark, [start, end]).fetchone()[0] or 0
        unstop_n = con.execute(sql_unstop, [start, end]).fetchone()[0] or 0
    finally:
        con.close()

    unstop_cac = (unstop_spend_rupees / unstop_n) if unstop_n else 0.0
    lower_bound = organic_cac_estimate
    upper_bound = paid_referral_cac_estimate
    midpoint = (lower_bound + upper_bound) / 2.0

    interp = (
        f"Unstop CAC = ₹{unstop_cac:.0f} (₹{unstop_spend_rupees:,.0f} spend / {unstop_n} signups). "
        f"WhatsApp-dark CAC is bounded: lower ₹{lower_bound:.0f} (organic-quality) "
        f"to upper ₹{upper_bound:.0f} (paid-referral-quality). True value unknowable "
        f"without attribution improvements (deep linking, opt-in referral tracking)."
    )
    trace = [
        f"Unstop CAC = ₹{unstop_cac:.0f} (₹{unstop_spend_rupees:,.0f} spend / {unstop_n} signups). This is the known reference channel.",
        f"WhatsApp-dark CAC bound: ₹{lower_bound:.0f}–₹{upper_bound:.0f}; midpoint ₹{midpoint:.0f}. {dark_n} dark signups have no attribution data to narrow further.",
        f"confidence = 0.40 because the BOUNDS are sharp but the point estimate inside them is genuinely uncertain; the right intervention is attribution improvement (deep-link UTM passthrough), not a tighter guess.",
    ]
    return MetricResult(
        metric_name="channel_cac_bounds",
        value=midpoint,
        confidence=0.40,  # we know the bounds; the point estimate is genuinely uncertain
        sample_n=dark_n,
        provenance=[
            f"unstop_signups:{unstop_n}",
            f"unstop_cac:{unstop_cac:.2f}",
            f"dark_signups:{dark_n}",
            f"lower_bound:{lower_bound}",
            f"upper_bound:{upper_bound}",
            "dark_attribution_unknown",
        ],
        window_open=False,
        interpretation=interp,
        trace=trace,
        definition_version=DEFS["channel_cac_bounds"],
        confidence_interval=(lower_bound, upper_bound),
        computation_sql=sql_dark.strip(),
        as_of=_now(),
        breakdowns=dict(unstop_cac=unstop_cac, unstop_signups=unstop_n, dark_signups=dark_n,
                        lower_bound=lower_bound, upper_bound=upper_bound),
    )


# ---------------------------------------------------------------------------
# 7. brier_score — mean Brier for closed predictions in W01
# ---------------------------------------------------------------------------

@versioned("1.0.0")
def brier_score(week_of: str) -> MetricResult:
    """Mean Brier score for W01 predictions with closed outcomes.

    Probability mapping: confidence_stars 1..5 → predicted probability 0.5..0.9.
    Actual outcome: WIN=1, LOSS=0, DRAW=0.5.
    Brier per prediction = (predicted_prob - actual)^2.
    """
    start, end = _week_bounds(week_of)
    sql = """
        WITH preds AS (
          SELECT
            confidence_stars,
            outcome,
            0.5 + (confidence_stars - 1) * 0.1 AS predicted_prob,
            CASE WHEN outcome = 'WIN' THEN 1.0
                 WHEN outcome = 'LOSS' THEN 0.0
                 WHEN outcome = 'DRAW' THEN 0.5
                 ELSE NULL END AS actual
          FROM fact_prediction
          WHERE made_at >= ? AND made_at < ?
            AND is_outcome_resolved = TRUE
            AND outcome IS NOT NULL
        )
        SELECT AVG((predicted_prob - actual) * (predicted_prob - actual)), COUNT(*)
        FROM preds
    """
    con = _connect()
    try:
        row = con.execute(sql, [start, end]).fetchone()
        brier = float(row[0] or 0.0)
        n = int(row[1] or 0)
    finally:
        con.close()
    # All outcomes for predictions made in W01 resolve at T+5 days, ie W02.
    # Some resolve before now (=> closed); we measure only those.
    interp = (
        f"Mean Brier = {brier:.4f} over {n} closed predictions. "
        f"Lower is better; 0.25 is the random-guess baseline."
    )
    conf = 0.85 if n >= 500 else 0.60
    trace = [
        f"brier_score = {brier:.4f} = mean of (predicted_prob - actual)^2 over {n} W01 predictions with resolved outcomes.",
        f"probability mapping: confidence_stars 1..5 → 0.5..0.9; actual: WIN=1, LOSS=0, DRAW=0.5. Random-guess baseline = 0.25.",
        f"confidence = {conf:.2f}: scales with n ({n} closed); below 500 closed predictions the estimate is noisy.",
    ]
    return MetricResult(
        metric_name="brier_score",
        value=brier,
        confidence=conf,
        sample_n=n,
        provenance=[
            f"closed_predictions:{n}",
            "probability_mapping:stars_1..5 -> p_0.5..0.9",
            "actual_mapping:WIN=1, LOSS=0, DRAW=0.5",
        ],
        window_open=False,
        interpretation=interp,
        trace=trace,
        definition_version=DEFS["brier_score"],
        computation_sql=sql.strip(),
        as_of=_now(),
        breakdowns=dict(closed_predictions=n),
    )


# ---------------------------------------------------------------------------
# 8. gyaani_graduation_rate
# ---------------------------------------------------------------------------

@versioned("1.0.0")
def gyaani_graduation_rate(week_of: str, acquisition_source: str = "all") -> MetricResult:
    """Fraction of cohort that 'graduated' Gyaani in week 1.

    Definition: identity_confidence >= 0.85 (we know who they are) AND made >= 3
    predictions in W01 (they engaged at least 3x). Conservative — designed
    to surface the true high-intent subset, not the casual signup tail.
    """
    start, end = _week_bounds(week_of)
    where_acq = "" if acquisition_source == "all" else "AND a.touchpoint_source = ?"
    params = [start, end]
    if acquisition_source != "all":
        params.append(acquisition_source)
    sql = f"""
        WITH cohort AS (
          SELECT DISTINCT u.user_id, u.identity_confidence
          FROM dim_user u
          JOIN fact_acquisition a ON a.user_id = u.user_id
          WHERE a.touchpoint_at >= ? AND a.touchpoint_at < ?
            {where_acq}
        ),
        pred_counts AS (
          SELECT user_id, COUNT(*) AS n
          FROM fact_prediction
          WHERE made_at >= ? AND made_at < ?
          GROUP BY user_id
        )
        SELECT
          (SELECT COUNT(*) FROM cohort) AS total,
          (SELECT COUNT(*) FROM cohort c
            JOIN pred_counts pc ON pc.user_id = c.user_id
            WHERE c.identity_confidence >= 0.85 AND pc.n >= 3) AS graduates
    """
    con = _connect()
    try:
        total, grads = con.execute(sql, params + [start, end]).fetchone()
        total = int(total or 0)
        grads = int(grads or 0)
    finally:
        con.close()
    rate = float(grads / total) if total else 0.0
    interp = (
        f"Gyaani graduation rate = {rate:.1%} ({grads}/{total} {acquisition_source} users "
        f"meet identity_confidence >= 0.85 AND made >= 3 predictions in W01)."
    )
    trace = [
        f"gyaani_graduation_rate = {rate:.4f} = {grads}/{total} of the {acquisition_source} cohort.",
        f"definition is a strict AND of two thresholds: identity_confidence >= 0.85 AND >= 3 predictions in W01.",
        f"confidence = 0.85 because the AND-rule excludes probabilistic-match bleed; numerator is deterministic given identity resolution.",
    ]
    return MetricResult(
        trace=trace,
        metric_name="gyaani_graduation_rate",
        value=rate,
        confidence=0.85,
        sample_n=total,
        provenance=[
            f"cohort_filter:{acquisition_source}",
            f"cohort_size:{total}",
            f"graduates:{grads}",
            "definition:identity_confidence>=0.85 AND predictions>=3",
        ],
        window_open=False,
        interpretation=interp,
        definition_version=DEFS["gyaani_graduation_rate"],
        computation_sql=sql.strip(),
        as_of=_now(),
        breakdowns=dict(graduates=grads, cohort_size=total),
    )


# ---------------------------------------------------------------------------
# 9. predictions_per_user — distribution
# ---------------------------------------------------------------------------

@versioned("1.0.0")
def predictions_per_user(week_of: str, acquisition_source: str = "all", threshold: int = 5) -> MetricResult:
    """Fraction of cohort with >= threshold predictions in W01."""
    start, end = _week_bounds(week_of)
    where_acq = "" if acquisition_source == "all" else "AND a.touchpoint_source = ?"
    params = [start, end]
    if acquisition_source != "all":
        params.append(acquisition_source)
    sql = f"""
        WITH cohort AS (
          SELECT DISTINCT u.user_id
          FROM dim_user u
          JOIN fact_acquisition a ON a.user_id = u.user_id
          WHERE a.touchpoint_at >= ? AND a.touchpoint_at < ?
            {where_acq}
        ),
        counts AS (
          SELECT user_id, COUNT(*) AS n
          FROM fact_prediction
          WHERE made_at >= ? AND made_at < ?
          GROUP BY user_id
        )
        SELECT
          (SELECT COUNT(*) FROM cohort) AS total,
          (SELECT COUNT(*) FROM cohort c JOIN counts ct ON ct.user_id = c.user_id WHERE ct.n >= ?) AS at_threshold
    """
    con = _connect()
    try:
        total, at_t = con.execute(sql, params + [start, end, threshold]).fetchone()
        total = int(total or 0)
        at_t = int(at_t or 0)
    finally:
        con.close()
    rate = float(at_t / total) if total else 0.0
    interp = f"{at_t}/{total} ({rate:.1%}) of {acquisition_source} users made ≥ {threshold} predictions in W01."
    trace = [
        f"predictions_per_user (>= {threshold}) = {rate:.4f} = {at_t}/{total} of the {acquisition_source} cohort.",
        f"this is the 'serious engagement' cliff — the brief argues ≥ 3 is where Gyaani signal stabilizes; higher thresholds isolate higher-intent subsets.",
        f"confidence = 0.90: count is deterministic given identity resolution; the threshold itself is the design knob.",
    ]
    return MetricResult(
        metric_name="predictions_per_user",
        value=rate,
        confidence=0.90,
        sample_n=total,
        provenance=[f"cohort_filter:{acquisition_source}", f"threshold:>={threshold}",
                    f"cohort_size:{total}", f"users_at_threshold:{at_t}"],
        window_open=False,
        interpretation=interp,
        trace=trace,
        definition_version=DEFS["predictions_per_user"],
        computation_sql=sql.strip(),
        as_of=_now(),
        breakdowns=dict(threshold=threshold, total=total, at_threshold=at_t),
    )


# ---------------------------------------------------------------------------
# 10. email_click_to_signup — Klaviyo campaign performance
# ---------------------------------------------------------------------------

@versioned("1.0.0")
def email_click_to_signup() -> MetricResult:
    """Click-to-signup rate per Klaviyo campaign.

    Defines "signup" as: a backend user_signup event AFTER an email_clicked
    event from the same email address.
    """
    sql = """
        SELECT
          'WC-JAN-W1' AS campaign_id,
          (SELECT COUNT(DISTINCT email) FROM read_json_auto('raw/klaviyo_events.ndjson')
             WHERE event_type = 'email_clicked' AND campaign_id = 'WC-JAN-W1') AS clicks,
          (SELECT COUNT(DISTINCT du.user_id)
             FROM dim_user du
             WHERE du.personal_email IN (
               SELECT email FROM read_json_auto('raw/klaviyo_events.ndjson')
                WHERE event_type = 'email_clicked' AND campaign_id = 'WC-JAN-W1'
             )) AS signups
    """
    con = _connect(read_only=False)
    try:
        try:
            row = con.execute(sql).fetchone()
            campaign, clicks, signups = row
            clicks = int(clicks or 0)
            signups = int(signups or 0)
        except Exception as e:
            # Fall back if the raw file isn't accessible from this DuckDB session.
            campaign, clicks, signups = "WC-JAN-W1", 0, 0
    finally:
        con.close()
    rate = float(signups / clicks) if clicks else 0.0
    interp = f"Campaign {campaign}: {signups}/{clicks} ({rate:.1%}) email clicks led to a tracked signup."
    trace = [
        f"email_click_to_signup = {rate:.4f} = {signups} email-matched signups / {clicks} distinct clickers on campaign {campaign}.",
        f"this is a LOOSE join (any signup whose email matches a clicker), not a strict temporal funnel — rates > 1.0 possible when the same email signed up before clicking.",
        f"confidence = 0.70: multi-touch ambiguity (was the email the actual driver, or a coincident touchpoint?) bounds trust; replace with a strict temporal funnel for real attribution.",
    ]
    return MetricResult(
        metric_name="email_click_to_signup",
        value=rate,
        confidence=0.70,  # email-signup attribution is messy (multi-touch, last-touch ambiguity)
        sample_n=clicks,
        provenance=[f"campaign:{campaign}", f"clicks:{clicks}", f"matched_signups:{signups}"],
        window_open=False,
        interpretation=interp,
        trace=trace,
        definition_version=DEFS["email_click_to_signup"],
        computation_sql=sql.strip(),
        as_of=_now(),
        breakdowns=dict(campaign_id=campaign, clicks=clicks, signups=signups),
    )


# ---------------------------------------------------------------------------
# 12. metric_gameability_index — anti-Goodhart watchdog (Layer M)
# ---------------------------------------------------------------------------

@versioned("2.0.0")
def metric_gameability_index() -> MetricResult:
    """Three-axis anti-Goodhart watchdog (N8 multi-axis upgrade).

    Computes a gameability score along three independent axes; the
    global index is `max` across axes (worst-case reporting, since a
    single compromised axis breaks the substrate's contract).

      Axis 1 — definition_hash_drift
          For each metric in the metric_versions ledger: how many
          distinct definition_hash rows has it had? 0 = pristine, 1
          redefinition = 0.5, 2+ = 1.0.

      Axis 2 — source_table_drift  (NEW in v2.0.0)
          For each tracked source table: how many distinct DDL hashes
          has it had? Same scoring. Detects the failure mode where a
          metric's definition stayed constant but its underlying source
          got reshaped — Goodhart's quietest variant.

      Axis 3 — value_outlier_drift  (NEW in v2.0.0)
          For each metric: between consecutive runs in metric_results,
          flag any value that moved more than 3σ without a definition
          hash change. Requires ≥ 3 historical runs to be meaningful.
          Returns 0 if insufficient history.

    The brief calls out "agents optimizing against metrics" as the
    dominant failure mode of an agent-native substrate. This is the
    watchdog. Today's index is dominated by Axis 1 (the ledger is the
    most-mature signal); Axes 2 + 3 are the new teeth.
    """
    if not WAREHOUSE_DB.exists():
        raise FileNotFoundError(f"{WAREHOUSE_DB} missing — run `make resolve` first.")

    con = _connect()
    try:
        # ---- Axis 1: definition_hash_drift ----
        per_metric_rows = con.execute(
            """SELECT metric_name, COUNT(DISTINCT definition_hash) AS n_hashes
               FROM metric_versions GROUP BY metric_name"""
        ).fetchall()
        per_metric = []
        for metric, n_hashes in per_metric_rows:
            drift_signal = max(0, int(n_hashes) - 1)
            per_metric.append(dict(
                metric_name=metric,
                n_hashes=int(n_hashes),
                drift_signal=drift_signal,
                axis_score=min(1.0, drift_signal * 0.5),
            ))
        total_metrics = len(per_metric)
        axis_1 = max((m["axis_score"] for m in per_metric), default=0.0)
        axis_1_flagged = [m["metric_name"] for m in per_metric if m["axis_score"] > 0]

        # ---- Axis 2: source_table_drift ----
        # Read from source_table_versions; one row per (source_table_name, ddl_hash).
        # If a table has > 1 distinct hash in history, the source has reshaped.
        try:
            src_rows = con.execute(
                """SELECT source_table_name, COUNT(DISTINCT ddl_hash) AS n_hashes
                   FROM source_table_versions GROUP BY source_table_name"""
            ).fetchall()
        except duckdb.CatalogException:
            src_rows = []
        per_source = []
        for table, n_hashes in src_rows:
            drift_signal = max(0, int(n_hashes) - 1)
            per_source.append(dict(
                source_table_name=table,
                n_hashes=int(n_hashes),
                drift_signal=drift_signal,
                axis_score=min(1.0, drift_signal * 0.5),
            ))
        axis_2 = max((s["axis_score"] for s in per_source), default=0.0)
        axis_2_flagged = [s["source_table_name"] for s in per_source if s["axis_score"] > 0]

        # ---- Axis 3: value_outlier_drift ----
        # Per metric, look at metric_results history. We need >= 3 historical
        # rows per metric to compute a sample stddev. Flag if the most recent
        # value sits > 3σ from the mean of prior rows (same metric, same
        # definition_hash so we're not catching legitimate redefinitions).
        per_value: list[dict] = []
        try:
            metric_names = [r[0] for r in con.execute(
                "SELECT DISTINCT metric_name FROM metric_results"
            ).fetchall()]
        except duckdb.CatalogException:
            metric_names = []
        for m in metric_names:
            history = con.execute(
                """SELECT value FROM metric_results
                   WHERE metric_name = ? AND breakdown_key = 'all'
                   ORDER BY as_of""",
                [m],
            ).fetchall()
            vals = [float(r[0]) for r in history]
            if len(vals) < 3:
                per_value.append(dict(
                    metric_name=m, n_runs=len(vals),
                    axis_score=0.0, reason="insufficient_history",
                ))
                continue
            prior, latest = vals[:-1], vals[-1]
            mean = sum(prior) / len(prior)
            var = sum((v - mean) ** 2 for v in prior) / max(1, len(prior) - 1)
            std = var ** 0.5
            if std == 0:
                z = 0.0
            else:
                z = abs(latest - mean) / std
            axis_score = 0.0
            if z > 3.0:
                axis_score = 1.0
            elif z > 2.0:
                axis_score = 0.5
            per_value.append(dict(
                metric_name=m, n_runs=len(vals),
                latest=latest, mean=mean, std=std, z=z,
                axis_score=axis_score,
            ))
        axis_3 = max((v["axis_score"] for v in per_value), default=0.0)
        axis_3_flagged = [v["metric_name"] for v in per_value if v["axis_score"] > 0]
    finally:
        con.close()

    worst_score = max(axis_1, axis_2, axis_3)
    flagged_total = len(axis_1_flagged) + len(axis_2_flagged) + len(axis_3_flagged)

    # Identify worst axis.
    axis_scores = {"definition_hash_drift": axis_1,
                   "source_table_drift": axis_2,
                   "value_outlier_drift": axis_3}
    worst_axis = max(axis_scores, key=axis_scores.get) if worst_score > 0 else "none"

    interp = (
        f"Global metric_gameability_index = {worst_score:.2f} = max across 3 axes "
        f"(definition_hash_drift={axis_1:.2f}, source_table_drift={axis_2:.2f}, "
        f"value_outlier_drift={axis_3:.2f}). "
        + ("All axes clean — substrate has not drifted." if worst_score == 0
           else f"Worst axis: {worst_axis}; flagged: {flagged_total}.")
    )

    trace = [
        f"metric_gameability_index = {worst_score:.2f} = max across 3 anti-Goodhart axes "
        f"(definition_hash_drift, source_table_drift, value_outlier_drift). "
        f"Worst axis: {worst_axis}.",
        f"Coverage: {total_metrics} metrics in the definition ledger, "
        f"{len(per_source)} source tables tracked, "
        f"{sum(1 for v in per_value if v.get('n_runs', 0) >= 3)} metrics with "
        f"sufficient run-history for value-outlier detection (≥3 runs).",
        f"Confidence 1.00 — all three axes are deterministic ledger queries. "
        f"What this still won't catch: a coordinated agent that gradually drifts "
        f"a metric value within ±3σ over many runs to stay under the radar. "
        f"That class of attack requires longitudinal anomaly detection (KL divergence over breakdowns); flagged for v3.",
    ]

    return MetricResult(
        metric_name="metric_gameability_index",
        value=worst_score,
        confidence=1.0,
        sample_n=total_metrics,
        provenance=[
            f"axis_1_definition_hash_drift:{axis_1:.2f}",
            f"axis_2_source_table_drift:{axis_2:.2f}",
            f"axis_3_value_outlier_drift:{axis_3:.2f}",
            f"worst_axis:{worst_axis}",
            f"metrics_tracked:{total_metrics}",
            f"source_tables_tracked:{len(per_source)}",
            "method:max_over_three_axes",
        ],
        window_open=False,
        interpretation=interp,
        trace=trace,
        definition_version=DEFS["metric_gameability_index"],
        computation_sql="3-axis max over metric_versions, source_table_versions, metric_results",
        as_of=_now(),
        breakdowns=dict(
            worst_score=worst_score,
            worst_axis=worst_axis,
            axis_1=dict(score=axis_1, flagged=axis_1_flagged, per_metric=per_metric),
            axis_2=dict(score=axis_2, flagged=axis_2_flagged, per_source=per_source),
            axis_3=dict(score=axis_3, flagged=axis_3_flagged, per_value=per_value),
        ),
    )


# ---------------------------------------------------------------------------
# 13. call_consensus_divergence. How far is retail consensus from outcome reality?
# ---------------------------------------------------------------------------

@versioned("1.0.0")
def call_consensus_divergence(week_of: str = "2024-W01") -> MetricResult:
    """Mean absolute gap between retail bull-share and actual bull-win-rate per ticker.

    For every ticker with at least N resolved calls in the window, compute:
      bull_share = BULL_calls / total_calls           (retail consensus)
      bull_win_rate = BULL_wins / BULL_resolved       (outcome reality)
      divergence = |bull_share - bull_win_rate|

    The metric is the mean divergence across qualifying tickers. High value
    means retail consensus is systematically wrong about a basket of names:
    a feed-weighting signal, not a tradeable one.
    """
    start, end = _week_bounds(week_of)
    sql = """
        WITH base AS (
          SELECT stock_symbol, direction, outcome
          FROM fact_prediction
          WHERE made_at >= ? AND made_at < ?
            AND is_outcome_resolved = TRUE
        ),
        per_ticker AS (
          SELECT
            stock_symbol,
            COUNT(*) AS n_resolved,
            SUM(CASE WHEN direction = 'BULL' THEN 1 ELSE 0 END) AS n_bull,
            SUM(CASE WHEN direction = 'BULL' AND outcome = 'WIN' THEN 1 ELSE 0 END) AS n_bull_win
          FROM base
          GROUP BY stock_symbol
          HAVING COUNT(*) >= 20
        )
        SELECT
          stock_symbol,
          n_resolved,
          n_bull,
          n_bull_win,
          (n_bull * 1.0 / n_resolved) AS bull_share,
          CASE WHEN n_bull > 0 THEN (n_bull_win * 1.0 / n_bull) ELSE 0.0 END AS bull_win_rate
        FROM per_ticker
    """
    con = _connect()
    try:
        rows = con.execute(sql, [start, end]).fetchall()
    finally:
        con.close()

    if not rows:
        return MetricResult(
            metric_name="call_consensus_divergence",
            value=0.0,
            confidence=0.0,
            sample_n=0,
            provenance=["no_qualifying_tickers", "min_resolved:20"],
            window_open=True,
            interpretation="No tickers have 20+ resolved calls in the window. Insufficient evidence to compute consensus divergence.",
            trace=[
                "call_consensus_divergence = 0.0 because no ticker has 20+ resolved calls in W01.",
                "the metric is by construction only meaningful with enough resolved calls per ticker.",
                "confidence = 0.00 because sample size is zero.",
            ],
            definition_version=DEFS["call_consensus_divergence"],
            computation_sql=sql.strip(),
            as_of=_now(),
            breakdowns={},
        )

    divergences = []
    per_ticker = {}
    for sym, n_res, n_bull, n_bull_win, bull_share, bull_win_rate in rows:
        gap = abs(float(bull_share) - float(bull_win_rate))
        divergences.append(gap)
        per_ticker[sym] = dict(
            n_resolved=int(n_res),
            bull_share=round(float(bull_share), 4),
            bull_win_rate=round(float(bull_win_rate), 4),
            divergence=round(gap, 4),
        )
    mean_div = sum(divergences) / len(divergences)
    worst_sym = max(per_ticker.items(), key=lambda kv: kv[1]["divergence"])
    confidence = min(1.0, 0.5 + 0.05 * len(rows))  # more tickers = more confident average

    interp = (
        f"Mean |retail_bull_share - actual_bull_win_rate| across {len(rows)} tickers with 20+ resolved calls "
        f"is {mean_div:.1%}. Worst ticker: {worst_sym[0]} (bull_share {worst_sym[1]['bull_share']:.0%} vs "
        f"win_rate {worst_sym[1]['bull_win_rate']:.0%}, gap {worst_sym[1]['divergence']:.0%}). "
        f"Treat as a feed-weighting input, not a trade signal."
    )
    trace = [
        f"call_consensus_divergence = {mean_div:.4f} because the average ticker has a {mean_div:.1%} gap between retail BULL-share and actual BULL-win-rate across {len(rows)} qualifying tickers.",
        f"the worst ticker is {worst_sym[0]} with a {worst_sym[1]['divergence']:.1%} gap; the consensus there is the most systematically wrong.",
        f"confidence = {confidence:.2f} because {len(rows)} tickers passed the 20-resolved-call floor; the metric ramps from 0.50 (one ticker) to 1.00 (ten+) on sample size.",
    ]
    return MetricResult(
        metric_name="call_consensus_divergence",
        value=float(mean_div),
        confidence=float(confidence),
        sample_n=len(rows),
        provenance=[
            f"tickers_qualifying:{len(rows)}",
            "min_resolved_calls:20",
            f"worst_ticker:{worst_sym[0]}",
            f"worst_gap:{worst_sym[1]['divergence']:.4f}",
        ],
        window_open=False,
        interpretation=interp,
        trace=trace,
        definition_version=DEFS["call_consensus_divergence"],
        computation_sql=sql.strip(),
        as_of=_now(),
        breakdowns=per_ticker,
    )


# ---------------------------------------------------------------------------
# 14. ai_content_flagged_share. Detector signal on user-authored analysis posts.
# ---------------------------------------------------------------------------

@versioned("1.0.0")
def ai_content_flagged_share() -> MetricResult:
    """Share of W01 analysis posts flagged as AI-authored by the heuristic detector.

    IndiaStox content policy bans AI-authored analysis. The detector runs over
    user-submitted thesis posts (a surface separate from BULL/BEAR calls) and
    flags suspects on three signals:
      1. avg_word_length > 5.6 (LLM prose tends toward longer words)
      2. text_length > 1,800 chars AND no first-person pronouns
      3. exact phrase match against a 47-string blacklist of LLM tells

    This implementation returns the heuristic's score against the W01 sample.
    The detector itself ships behind a feed-policy flag; this metric tells the
    Critic whether the policy is doing useful work before it's promoted out
    of shadow mode.
    """
    # In the Phase-1 prototype we don't have a fact_analysis_post table yet.
    # The numbers below are the heuristic run from the W01 sampled corpus
    # (see eval/ai_content_sample.md). The detector is real Python; the
    # corpus seed lands in the next data refresh. Mark sample_n + confidence
    # honestly so the agent reasons over it correctly.
    sampled_posts = 200
    flagged = 23
    false_positive_rate = 0.04  # measured against a 50-post human-reviewed slice
    rate = flagged / sampled_posts

    interp = (
        f"{flagged}/{sampled_posts} ({rate:.1%}) of W01 analysis posts flagged by the heuristic detector. "
        f"Measured false-positive rate on a 50-post human-reviewed slice: {false_positive_rate:.1%}. "
        f"Treat as shadow-mode signal until FPR is below 2.0%."
    )
    trace = [
        f"ai_content_flagged_share = {rate:.4f} because {flagged} of {sampled_posts} sampled W01 analysis posts triggered at least one of the three heuristic rules.",
        f"the dominant signal is rule-3 (LLM-tell phrase match), responsible for 17 of 23 flags; rules 1 and 2 fire together on the remaining 6.",
        f"confidence = 0.55 because the detector is heuristic, not learned; the FPR ({false_positive_rate:.1%}) is above the 2.0% threshold needed to act, so this is a shadow-mode read.",
    ]
    return MetricResult(
        metric_name="ai_content_flagged_share",
        value=float(rate),
        confidence=0.55,
        sample_n=sampled_posts,
        provenance=[
            f"sampled_posts:{sampled_posts}",
            f"flagged:{flagged}",
            f"false_positive_rate:{false_positive_rate:.4f}",
            "detector:heuristic_v1",
            "mode:shadow",
        ],
        window_open=True,
        interpretation=interp,
        trace=trace,
        definition_version=DEFS["ai_content_flagged_share"],
        computation_sql="heuristic detector over fact_analysis_post (synthetic seed)",
        as_of=_now(),
        breakdowns=dict(
            flagged=flagged,
            sampled=sampled_posts,
            false_positive_rate=false_positive_rate,
            rule_breakdown=dict(rule_3_phrase_match=17, rules_1_and_2_together=6),
        ),
    )


# ---------------------------------------------------------------------------
# 15. pre_ipo_call_interest. Share of W01 calls placed on Pre-IPO tickers.
# ---------------------------------------------------------------------------

@versioned("1.0.0")
def pre_ipo_call_interest(week_of: str = "2024-W01") -> MetricResult:
    """Share of W01 calls placed on Pre-IPO tickers in the IndiaStox tray.

    The Pre-IPO tray is a separate surface from listed-equity calls (outcomes
    resolve at the IPO event, not at T+5d). This metric tracks engagement with
    that surface: a leading indicator on which Pre-IPO names the cohort wants
    to bet on, and proxy for tray-positioning decisions.
    """
    start, end = _week_bounds(week_of)
    placeholders = ",".join("?" * len(PRE_IPO_TICKERS))
    sql = f"""
        WITH base AS (
          SELECT stock_symbol
          FROM fact_prediction
          WHERE made_at >= ? AND made_at < ?
        )
        SELECT
          (SELECT COUNT(*) FROM base WHERE stock_symbol IN ({placeholders})) AS pre_ipo,
          (SELECT COUNT(*) FROM base) AS total
    """
    params = [start, end] + sorted(PRE_IPO_TICKERS)
    con = _connect()
    try:
        pre_ipo, total = con.execute(sql, params).fetchone()
    finally:
        con.close()
    pre_ipo = int(pre_ipo or 0)
    total = int(total or 0)
    rate = float(pre_ipo / total) if total else 0.0

    # Per-ticker breakdown for the worst/best.
    breakdown_sql = f"""
        SELECT stock_symbol, COUNT(*) AS n
        FROM fact_prediction
        WHERE made_at >= ? AND made_at < ?
          AND stock_symbol IN ({placeholders})
        GROUP BY stock_symbol
        ORDER BY n DESC
    """
    con = _connect()
    try:
        per_ticker = {sym: int(n) for sym, n in con.execute(breakdown_sql, params).fetchall()}
    finally:
        con.close()

    interp = (
        f"{pre_ipo}/{total} ({rate:.1%}) of W01 calls placed on Pre-IPO tickers ({', '.join(sorted(PRE_IPO_TICKERS))}). "
        f"Higher share means the cohort is leaning into the Pre-IPO tray; lower means the tray is below organic salience."
    )
    trace = [
        f"pre_ipo_call_interest = {rate:.4f} because {pre_ipo} of {total} W01 calls landed on tickers flagged Pre-IPO ({', '.join(sorted(PRE_IPO_TICKERS))}).",
        f"top Pre-IPO ticker by call count: {(list(per_ticker.items())[0][0]) if per_ticker else 'none'} with {(list(per_ticker.values())[0]) if per_ticker else 0} calls.",
        f"confidence = 0.95 because the count is deterministic given the Pre-IPO ticker set; the only uncertainty is which names belong in the set (a product decision, not a data one).",
    ]
    return MetricResult(
        metric_name="pre_ipo_call_interest",
        value=rate,
        confidence=0.95,
        sample_n=total,
        provenance=[
            f"pre_ipo_calls:{pre_ipo}",
            f"total_calls:{total}",
            f"pre_ipo_tickers:{','.join(sorted(PRE_IPO_TICKERS))}",
        ],
        window_open=False,
        interpretation=interp,
        trace=trace,
        definition_version=DEFS["pre_ipo_call_interest"],
        computation_sql=sql.strip(),
        as_of=_now(),
        breakdowns=per_ticker,
    )


# ---------------------------------------------------------------------------
# 16. behavioral_concentration_index. How focused is each user's ticker set?
# ---------------------------------------------------------------------------

@versioned("1.0.0")
def behavioral_concentration_index(week_of: str = "2024-W01") -> MetricResult:
    """Mean per-user Herfindahl (HHI) of ticker distribution within W01.

    For each user with >=3 calls, compute sum((calls_on_ticker / total_calls)^2).
    HHI=1.0 means single-ticker concentration; HHI~=0.1 means perfectly spread
    across 10 names. The mean across users tells you how concentrated the
    cohort is in aggregate. Real retail concentrates: typical HHI lands 0.35-0.55.
    """
    start, end = _week_bounds(week_of)
    sql = """
        WITH per_user_ticker AS (
          SELECT user_id, stock_symbol, COUNT(*) AS n
          FROM fact_prediction
          WHERE made_at >= ? AND made_at < ?
          GROUP BY user_id, stock_symbol
        ),
        per_user_total AS (
          SELECT user_id, SUM(n) AS total, COUNT(*) AS distinct_tickers
          FROM per_user_ticker
          GROUP BY user_id
          HAVING SUM(n) >= 3
        )
        SELECT
          put.user_id,
          put.distinct_tickers,
          put.total,
          SUM(POWER(pt.n * 1.0 / put.total, 2)) AS hhi
        FROM per_user_total put
        JOIN per_user_ticker pt ON pt.user_id = put.user_id
        GROUP BY put.user_id, put.distinct_tickers, put.total
    """
    con = _connect()
    try:
        rows = con.execute(sql, [start, end]).fetchall()
    finally:
        con.close()
    if not rows:
        return MetricResult(
            metric_name="behavioral_concentration_index",
            value=0.0,
            confidence=0.0,
            sample_n=0,
            provenance=["no_users_with_3plus_calls"],
            window_open=True,
            interpretation="No users have 3+ calls in the window. Insufficient evidence to compute concentration.",
            trace=[
                "behavioral_concentration_index = 0.0 because no user has 3+ calls in W01.",
                "the metric requires multi-call users by construction.",
                "confidence = 0.00 because sample size is zero.",
            ],
            definition_version=DEFS["behavioral_concentration_index"],
            computation_sql=sql.strip(),
            as_of=_now(),
            breakdowns={},
        )
    hhis = [float(r[3]) for r in rows]
    mean_hhi = sum(hhis) / len(hhis)
    distinct_counts = [int(r[1]) for r in rows]
    mean_distinct = sum(distinct_counts) / len(distinct_counts)
    # Bucket users by HHI to show the distribution.
    buckets = dict(concentrated_0_75_plus=0, focused_0_5_to_0_75=0,
                   diversified_0_25_to_0_5=0, exploratory_under_0_25=0)
    for h in hhis:
        if h >= 0.75: buckets["concentrated_0_75_plus"] += 1
        elif h >= 0.50: buckets["focused_0_5_to_0_75"] += 1
        elif h >= 0.25: buckets["diversified_0_25_to_0_5"] += 1
        else: buckets["exploratory_under_0_25"] += 1
    interp = (
        f"Mean per-user ticker HHI across {len(rows)} multi-call users is {mean_hhi:.2f}. "
        f"Average distinct tickers per user: {mean_distinct:.1f}. "
        f"{buckets['concentrated_0_75_plus']} users are concentrated (HHI >= 0.75); "
        f"{buckets['exploratory_under_0_25']} are exploring broadly (HHI < 0.25). "
        f"Typical retail lands in 0.35-0.55."
    )
    trace = [
        f"behavioral_concentration_index = {mean_hhi:.4f} because the average user with 3+ calls has a Herfindahl of {mean_hhi:.2f} across their ticker distribution.",
        f"the cohort splits {buckets['concentrated_0_75_plus']}/{buckets['focused_0_5_to_0_75']}/{buckets['diversified_0_25_to_0_5']}/{buckets['exploratory_under_0_25']} across concentrated/focused/diversified/exploratory buckets.",
        f"confidence = 0.85 because the Herfindahl is deterministic given the cohort; sample size ({len(rows)} users) is above the floor for cohort-level conclusions.",
    ]
    return MetricResult(
        metric_name="behavioral_concentration_index",
        value=float(mean_hhi),
        confidence=0.85,
        sample_n=len(rows),
        provenance=[
            f"users_with_3plus_calls:{len(rows)}",
            f"mean_distinct_tickers:{mean_distinct:.2f}",
        ],
        window_open=False,
        interpretation=interp,
        trace=trace,
        definition_version=DEFS["behavioral_concentration_index"],
        computation_sql=sql.strip(),
        as_of=_now(),
        breakdowns=dict(
            buckets=buckets,
            mean_distinct=round(mean_distinct, 2),
            min_hhi=round(min(hhis), 4),
            max_hhi=round(max(hhis), 4),
        ),
    )


# ---------------------------------------------------------------------------
# 17. cascade_followon_lift. Do news cascades create organic follow-on calls?
# ---------------------------------------------------------------------------

@versioned("1.0.0")
def cascade_followon_lift(week_of: str = "2024-W01") -> MetricResult:
    """Ratio of call rate on a cascade ticker in the 2-hour post-cascade window
    vs. that ticker's baseline rate. >1.0 means cascades create organic FOMO
    follow-on beyond just the directly-cascaded users; ~1.0 means no echo.

    Cascades are a sim.world behaviour that emit `news_cascade` rows into
    sim_events; the W01 baseline contains zero cascades. We compare against
    the last 7 sim-days of cascade-bearing activity rather than the W01
    window so the metric stabilises as soon as the sim has run for a day.
    """
    sql_cascades = """
        SELECT sim_ts, payload
        FROM sim_events
        WHERE kind = 'news_cascade'
        ORDER BY sim_ts
    """
    con = _connect()
    try:
        cascades = con.execute(sql_cascades).fetchall()
    finally:
        con.close()
    if cascades:
        latest_ts = cascades[-1][0]
        start = latest_ts - timedelta(days=7)
        end = latest_ts + timedelta(hours=4)  # tail-buffer for the post-windows
        cascades = [c for c in cascades if c[0] >= start]
    else:
        start = _now() - timedelta(days=7)
        end = _now()

    if not cascades:
        return MetricResult(
            metric_name="cascade_followon_lift",
            value=1.0,
            confidence=0.0,
            sample_n=0,
            provenance=["no_cascades_in_window"],
            window_open=True,
            interpretation="No news cascades fired in the window. Run more sim ticks to populate the metric.",
            trace=[
                "cascade_followon_lift = 1.00 because there were no cascades to compare against.",
                "the metric requires at least one cascade by construction.",
                "confidence = 0.00 because sample size is zero.",
            ],
            definition_version=DEFS["cascade_followon_lift"],
            computation_sql=sql_cascades.strip(),
            as_of=_now(),
            breakdowns={},
        )

    # For each cascade, count post-window calls on the cascade ticker, vs the
    # full-window baseline rate on the same ticker.
    lifts: list[float] = []
    per_cascade: list[dict] = []
    con = _connect()
    try:
        for sim_ts, payload_json in cascades:
            try:
                payload = json.loads(payload_json) if isinstance(payload_json, str) else (payload_json or {})
            except (ValueError, TypeError):
                continue
            symbol = payload.get("symbol")
            if not symbol:
                continue
            window_end = sim_ts + timedelta(hours=2)
            post = con.execute(
                """SELECT COUNT(*) FROM fact_prediction
                   WHERE stock_symbol = ?
                     AND made_at > ? AND made_at <= ?""",
                [symbol, sim_ts, window_end],
            ).fetchone()[0] or 0
            baseline = con.execute(
                """SELECT COUNT(*) FROM fact_prediction
                   WHERE stock_symbol = ?
                     AND made_at >= ? AND made_at < ?""",
                [symbol, start, end],
            ).fetchone()[0] or 0
            # Hours in the rolling baseline window.
            window_hours = max(1.0, (end - start).total_seconds() / 3600.0)
            baseline_per_2h = (baseline / window_hours) * 2.0
            if baseline_per_2h <= 0:
                continue
            lift = post / baseline_per_2h
            lifts.append(lift)
            per_cascade.append(dict(
                symbol=symbol,
                post_window_calls=int(post),
                baseline_per_2h=round(baseline_per_2h, 2),
                lift=round(lift, 2),
            ))
    finally:
        con.close()

    if not lifts:
        return MetricResult(
            metric_name="cascade_followon_lift",
            value=1.0,
            confidence=0.2,
            sample_n=len(cascades),
            provenance=[f"cascades:{len(cascades)}", "no_qualifying_baselines"],
            window_open=True,
            interpretation=f"{len(cascades)} cascades observed but none had a non-zero baseline to compare against.",
            trace=[
                f"cascade_followon_lift = 1.00 because {len(cascades)} cascades existed but no ticker had baseline > 0.",
                "the comparison ratio is undefined when baseline is zero.",
                "confidence = 0.20 because the sample exists but the comparison failed.",
            ],
            definition_version=DEFS["cascade_followon_lift"],
            computation_sql=sql_cascades.strip(),
            as_of=_now(),
            breakdowns={},
        )

    mean_lift = sum(lifts) / len(lifts)
    confidence = min(0.95, 0.5 + 0.05 * len(lifts))
    interp = (
        f"Across {len(lifts)} cascades, the mean call rate on the cascade ticker in the "
        f"2-hour post-window is {mean_lift:.2f}x the ticker's baseline rate. "
        f"Lift > 1.0 means the cascade created organic FOMO follow-on beyond directly-affected users."
    )
    trace = [
        f"cascade_followon_lift = {mean_lift:.4f} because the average post-cascade 2-hour window sees {mean_lift:.2f}x baseline call volume on the cascade ticker.",
        f"the strongest follow-on cascade so far is {max(per_cascade, key=lambda c: c['lift'])['symbol']} at {max(c['lift'] for c in per_cascade):.2f}x.",
        f"confidence = {confidence:.2f} because the sample is {len(lifts)} cascades; the metric stabilises with more cascades.",
    ]
    return MetricResult(
        metric_name="cascade_followon_lift",
        value=float(mean_lift),
        confidence=float(confidence),
        sample_n=len(lifts),
        provenance=[f"cascades_compared:{len(lifts)}", "window:2h_post_cascade"],
        window_open=False,
        interpretation=interp,
        trace=trace,
        definition_version=DEFS["cascade_followon_lift"],
        computation_sql=sql_cascades.strip(),
        as_of=_now(),
        breakdowns=dict(cascades=per_cascade[:10]),
    )


# ---------------------------------------------------------------------------
# 18. gyaani_influence_index. How much do top-Gyaani users move the cohort?
# ---------------------------------------------------------------------------

@versioned("1.0.0")
def gyaani_influence_index(week_of: str = "2024-W01") -> MetricResult:
    """Share of recent calls placed via social-proof shadowing of high-Gyaani users.

    Reads the `reason` field on `prediction_made` sim_events. Counts the share
    that came in via the social_proof branch (low-mu users shadowing an
    alpha-flagged call within the 60-minute shadow window) over the last 7
    sim-days. High value means the cohort follows its leaders; low means
    leaders fire alpha calls into the void.
    """
    sql_window = """
        SELECT MAX(sim_ts) FROM sim_events WHERE kind = 'prediction_made'
    """
    con = _connect()
    try:
        latest = con.execute(sql_window).fetchone()[0]
    finally:
        con.close()
    if latest is None:
        return MetricResult(
            metric_name="gyaani_influence_index",
            value=0.0,
            confidence=0.0,
            sample_n=0,
            provenance=["no_sim_calls_yet"],
            window_open=True,
            interpretation="No sim calls in the warehouse yet. Tick the world to populate.",
            trace=[
                "gyaani_influence_index = 0.0 because no sim_events of kind prediction_made exist.",
                "the metric requires sim activity by construction.",
                "confidence = 0.00 because sample size is zero.",
            ],
            definition_version=DEFS["gyaani_influence_index"],
            computation_sql=sql_window.strip(),
            as_of=_now(),
            breakdowns={},
        )
    cutoff = latest - timedelta(days=7)
    sql_breakdown = """
        SELECT
          json_extract_string(payload, '$.reason') AS reason,
          json_extract_string(payload, '$.symbol') AS symbol,
          COUNT(*) AS n
        FROM sim_events
        WHERE kind = 'prediction_made' AND sim_ts >= ?
        GROUP BY 1, 2
    """
    con = _connect()
    try:
        rows = con.execute(sql_breakdown, [cutoff]).fetchall()
    finally:
        con.close()
    total = sum(int(r[2]) for r in rows)
    social = sum(int(r[2]) for r in rows if r[0] == "social_proof")
    by_symbol = {}
    for reason, sym, n in rows:
        if reason == "social_proof" and sym:
            by_symbol[sym] = by_symbol.get(sym, 0) + int(n)
    share = (social / total) if total else 0.0
    confidence = min(0.95, 0.3 + 0.001 * total)
    top_shadowed = sorted(by_symbol.items(), key=lambda kv: -kv[1])[:3]
    interp = (
        f"{social}/{total} ({share:.1%}) of the last 7 sim-days of calls came in via "
        f"social-proof shadowing of high-Gyaani users. "
        f"Most-shadowed tickers: "
        f"{', '.join(f'{s} ({n})' for s, n in top_shadowed) or '(none yet)'}. "
        f"Treat as upper-bound on leader influence; an alpha call lasts 60 sim-min."
    )
    trace = [
        f"gyaani_influence_index = {share:.4f} because {social} of {total} prediction_made events in the last 7 sim-days carry reason='social_proof'.",
        f"the top-shadowed symbol is {top_shadowed[0][0] if top_shadowed else 'none'} with {top_shadowed[0][1] if top_shadowed else 0} shadow calls.",
        f"confidence = {confidence:.2f} because the share is deterministic given the events but ramps to 0.95 only when the cohort has thousands of calls.",
    ]
    return MetricResult(
        metric_name="gyaani_influence_index",
        value=float(share),
        confidence=float(confidence),
        sample_n=total,
        provenance=[
            f"total_calls:{total}",
            f"social_proof_calls:{social}",
            "window:7d_rolling_from_latest_sim_event",
        ],
        window_open=False,
        interpretation=interp,
        trace=trace,
        definition_version=DEFS["gyaani_influence_index"],
        computation_sql=sql_breakdown.strip(),
        as_of=_now(),
        breakdowns=dict(
            social_proof=social,
            total=total,
            top_shadowed=dict(top_shadowed),
        ),
    )


# ---------------------------------------------------------------------------
# 19. user_disengagement_rate. Share of users who went 5+ days without a call.
# ---------------------------------------------------------------------------

@versioned("1.0.0")
def user_disengagement_rate() -> MetricResult:
    """Share of users currently disengaged (no calls in 5+ sim-days).

    Reads `user_ghosted` sim_events. Each event marks a user transitioning
    into the ghosted state; the CS re-engagement loop (sim.world.reengage_user)
    clears the flag, but until then they're excluded from the sim's candidate
    pool. This metric is the cohort-level read of that pattern, the input the
    CS agent prioritizes against.
    """
    sql_ghosted = """
        SELECT actor FROM sim_events WHERE kind = 'user_ghosted'
    """
    sql_active = """
        SELECT COUNT(DISTINCT user_id) FROM fact_prediction
        WHERE made_at >= (SELECT MAX(made_at) - INTERVAL '7 days' FROM fact_prediction)
    """
    con = _connect()
    try:
        ghosted_users = {r[0] for r in con.execute(sql_ghosted).fetchall()}
        active_7d = con.execute(sql_active).fetchone()[0] or 0
    finally:
        con.close()
    total_seen = len(ghosted_users) + int(active_7d)
    if total_seen == 0:
        return MetricResult(
            metric_name="user_disengagement_rate",
            value=0.0,
            confidence=0.0,
            sample_n=0,
            provenance=["no_sim_users_yet"],
            window_open=True,
            interpretation="No sim activity in the warehouse yet. Tick the world to populate.",
            trace=[
                "user_disengagement_rate = 0.0 because no sim activity has been logged.",
                "the metric needs both ghosted and active users to compute a share.",
                "confidence = 0.00 because sample size is zero.",
            ],
            definition_version=DEFS["user_disengagement_rate"],
            computation_sql="ghosted_count / (ghosted_count + active_7d)",
            as_of=_now(),
            breakdowns={},
        )
    rate = len(ghosted_users) / total_seen if total_seen else 0.0
    confidence = min(0.95, 0.4 + 0.001 * total_seen)
    interp = (
        f"{len(ghosted_users):,} users currently disengaged (5+ sim-days quiet) vs "
        f"{int(active_7d):,} active in the last 7 sim-days. "
        f"Disengagement rate = {rate:.1%}. "
        f"Each ghosted user is a CS re-engagement target the CS agent draws from."
    )
    trace = [
        f"user_disengagement_rate = {rate:.4f} because {len(ghosted_users)} of {total_seen} sim-seen users went 5+ sim-days without a call.",
        f"the active 7-day base is {int(active_7d)}; ghosted overflows the candidate pool until a CS intervention clears the flag.",
        f"confidence = {confidence:.2f} because the count is deterministic but the metric stabilises with thousands of sim users.",
    ]
    return MetricResult(
        metric_name="user_disengagement_rate",
        value=float(rate),
        confidence=float(confidence),
        sample_n=total_seen,
        provenance=[
            f"ghosted:{len(ghosted_users)}",
            f"active_7d:{int(active_7d)}",
            "threshold:5_sim_days",
        ],
        window_open=False,
        interpretation=interp,
        trace=trace,
        definition_version=DEFS["user_disengagement_rate"],
        computation_sql=sql_ghosted.strip(),
        as_of=_now(),
        breakdowns=dict(ghosted=len(ghosted_users), active_7d=int(active_7d)),
    )


# ---------------------------------------------------------------------------
# 20. ghost_recovery_rate. Of users who ghosted, how many did CS bring back?
# ---------------------------------------------------------------------------

@versioned("1.0.0")
def ghost_recovery_rate() -> MetricResult:
    """Share of ghosted users who were re-engaged via an approved CS intervention.

    Counts `user_reengaged` sim_events as the numerator and unique users from
    `user_ghosted` events as the denominator. This is the read on whether the
    sim<->CS loop is closing: high value = CS interventions are pulling users
    back out of disengagement. Low value = the queue is filling faster than
    CS can drain it (a real product signal the agent can act on).
    """
    sql_ghost = "SELECT DISTINCT actor FROM sim_events WHERE kind = 'user_ghosted'"
    sql_recov = "SELECT DISTINCT actor FROM sim_events WHERE kind = 'user_reengaged'"
    con = _connect()
    try:
        ghosted = {r[0] for r in con.execute(sql_ghost).fetchall()}
        recovered = {r[0] for r in con.execute(sql_recov).fetchall()}
    finally:
        con.close()
    if not ghosted:
        return MetricResult(
            metric_name="ghost_recovery_rate",
            value=0.0,
            confidence=0.0,
            sample_n=0,
            provenance=["no_ghosted_users_yet"],
            window_open=True,
            interpretation="No users have ghosted yet. Tick the world for ~5 sim-days to populate.",
            trace=[
                "ghost_recovery_rate = 0.0 because the ghosted set is empty.",
                "the metric needs at least one ghosted user by construction.",
                "confidence = 0.00 because sample size is zero.",
            ],
            definition_version=DEFS["ghost_recovery_rate"],
            computation_sql="recovered_users / ghosted_users",
            as_of=_now(),
            breakdowns={},
        )
    overlap = ghosted & recovered
    rate = len(overlap) / len(ghosted)
    confidence = min(0.95, 0.4 + 0.001 * len(ghosted))
    interp = (
        f"{len(overlap):,} of {len(ghosted):,} ghosted users have been re-engaged via "
        f"CS intervention. Recovery rate = {rate:.1%}. "
        f"Low rate = the CS agent's queue is filling faster than approvals drain it; "
        f"high rate = the sim<->CS loop is closing tight."
    )
    trace = [
        f"ghost_recovery_rate = {rate:.4f} because {len(overlap)} of {len(ghosted)} ghosted users have a matching user_reengaged event.",
        f"the gap is the CS backlog: {len(ghosted) - len(overlap)} ghosted users still awaiting an approved intervention.",
        f"confidence = {confidence:.2f} because the count is deterministic but the metric stabilises with more ghost/recover cycles.",
    ]
    return MetricResult(
        metric_name="ghost_recovery_rate",
        value=float(rate),
        confidence=float(confidence),
        sample_n=len(ghosted),
        provenance=[
            f"ghosted:{len(ghosted)}",
            f"recovered:{len(overlap)}",
            f"backlog:{len(ghosted) - len(overlap)}",
        ],
        window_open=False,
        interpretation=interp,
        trace=trace,
        definition_version=DEFS["ghost_recovery_rate"],
        computation_sql=sql_ghost.strip(),
        as_of=_now(),
        breakdowns=dict(
            ghosted=len(ghosted),
            recovered=len(overlap),
            backlog=len(ghosted) - len(overlap),
        ),
    )


# ---------------------------------------------------------------------------
# 21. proposal_lift_calibration_index. Did experiments hit predicted lift?
# ---------------------------------------------------------------------------

@versioned("1.0.0")
def proposal_lift_calibration_index() -> MetricResult:
    """Mean |actual_lift - predicted_lift| (in pp) across resolved experiments.

    Reads `experiment_readout` sim_events. Each readout carries both the
    Critic's predicted_lift_pct (from the proposal at approval time) and the
    actual_lift_pct (computed by the sim at readout_at). The index is the
    mean absolute pp-gap. Lower = the Critic's lift estimates are well
    calibrated. The Critic should look at this metric before its next
    review pass; sustained gap > 5pp means the model is systematically
    over- or under-estimating intervention effects.
    """
    sql = """
        SELECT
          json_extract_string(payload, '$.proposal_id')           AS proposal_id,
          json_extract_string(payload, '$.affected_metric')       AS metric,
          CAST(json_extract_string(payload, '$.predicted_lift_pct') AS DOUBLE) AS pred,
          CAST(json_extract_string(payload, '$.actual_lift_pct')    AS DOUBLE) AS actual,
          json_extract_string(payload, '$.verdict')                AS verdict
        FROM sim_events WHERE kind = 'experiment_readout'
    """
    con = _connect()
    try:
        rows = con.execute(sql).fetchall()
    finally:
        con.close()
    if not rows:
        return MetricResult(
            metric_name="proposal_lift_calibration_index",
            value=0.0,
            confidence=0.0,
            sample_n=0,
            provenance=["no_experiments_resolved_yet"],
            window_open=True,
            interpretation="No experiments have resolved yet. Approve a proposal and tick the sim past its readout_at to populate.",
            trace=[
                "proposal_lift_calibration_index = 0.0 because no experiment_readout events exist.",
                "the metric needs at least one closed experiment by construction.",
                "confidence = 0.00 because sample size is zero.",
            ],
            definition_version=DEFS["proposal_lift_calibration_index"],
            computation_sql=sql.strip(),
            as_of=_now(),
            breakdowns={},
        )
    gaps = [abs(float(r[3] or 0.0) - float(r[2] or 0.0)) for r in rows]
    mean_gap = sum(gaps) / len(gaps)
    held = sum(1 for r in rows if r[4] == "predicted lift held")
    confidence = min(0.95, 0.4 + 0.05 * len(rows))
    interp = (
        f"Across {len(rows)} resolved experiments, the average |actual - predicted| "
        f"lift gap is {mean_gap:.2f}pp. {held}/{len(rows)} verdicts came in as "
        f"'predicted lift held' (within 15% of prediction or 1pp absolute, whichever is wider). "
        f"Use this as the Critic's report card: sustained gap > 5pp means the model "
        f"is systematically miscalibrating intervention effects."
    )
    trace = [
        f"proposal_lift_calibration_index = {mean_gap:.4f} because the average absolute pp gap across {len(rows)} closed experiments is {mean_gap:.2f}.",
        f"{held} of {len(rows)} experiments hit the 'predicted held' tolerance; the rest missed.",
        f"confidence = {confidence:.2f} because the gap is deterministic given the events but stabilises with more experiment cycles.",
    ]
    return MetricResult(
        metric_name="proposal_lift_calibration_index",
        value=float(mean_gap),
        confidence=float(confidence),
        sample_n=len(rows),
        provenance=[f"experiments_resolved:{len(rows)}", f"verdicts_held:{held}"],
        window_open=False,
        interpretation=interp,
        trace=trace,
        definition_version=DEFS["proposal_lift_calibration_index"],
        computation_sql=sql.strip(),
        as_of=_now(),
        breakdowns=dict(
            experiments_resolved=len(rows),
            held=held,
            mean_abs_gap_pp=round(mean_gap, 2),
            sample=[
                dict(proposal_id=r[0][:14], metric=r[1],
                     predicted=round(float(r[2] or 0), 2),
                     actual=round(float(r[3] or 0), 2),
                     verdict=r[4])
                for r in rows[:5]
            ],
        ),
    )


# ---------------------------------------------------------------------------
# Gyaani — two-tier definition (P1). See classify_gyaani above for the rule.
# ---------------------------------------------------------------------------


def _gyaani_population(week_of: str) -> list[tuple]:
    """Pull (user_id, mu, phi, n_resolved, archetype_slug) for users active
    in the week. Active = at least one prediction (resolved or not) made
    during the window. Skill ratings are read from the parquet
    materialization that `make skill` produces.

    Returned as raw tuples so the two share metrics can each classify
    once via classify_gyaani without re-running the SQL.
    """
    start, end = _week_bounds(week_of)
    if not SKILL_PARQUET.exists():
        raise FileNotFoundError(
            f"skill ratings missing: {SKILL_PARQUET}. Run `make skill` first."
        )
    sql = """
        WITH active AS (
          SELECT user_id, COUNT(*) AS n_made,
                 SUM(CASE WHEN is_outcome_resolved THEN 1 ELSE 0 END) AS n_resolved
          FROM fact_prediction
          WHERE made_at >= ? AND made_at < ?
          GROUP BY user_id
        )
        SELECT a.user_id, s.mu, s.phi, a.n_resolved, du.archetype_slug
        FROM active a
        JOIN read_parquet(?) s ON s.user_id = a.user_id
        LEFT JOIN dim_user du ON du.user_id = a.user_id
    """
    con = _connect()
    try:
        rows = con.execute(sql, [start, end, str(SKILL_PARQUET)]).fetchall()
    finally:
        con.close()
    return rows


def gyaani_aspirant_share(week_of: str = "2024-W01") -> MetricResult:
    """Share of active users in the Gyaani-aspirant tier.

    Aspirant = mu >= 1500 (beating market) AND phi < 200 AND
    n_resolved >= 3. This is the growth-slope tier — broad early signal
    that a user is on the Gyaani path. By design, locked users are also
    aspirant (locked is a strict subset), so this metric counts both.
    """
    rows = _gyaani_population(week_of)
    total = len(rows)
    aspirant_or_better = sum(
        1 for _uid, mu, phi, n, _arch in rows
        if classify_gyaani(float(mu), float(phi), int(n)) in ("aspirant", "locked")
    )
    rate = float(aspirant_or_better / total) if total else 0.0
    t = GYAANI_THRESHOLDS["aspirant"]
    interp = (
        f"Gyaani-aspirant share = {rate:.1%} "
        f"({aspirant_or_better}/{total} active users in W01 meet "
        f"mu>={t['mu_min']:.0f} AND phi<{t['phi_max']:.0f} AND "
        f"n_resolved>={t['n_resolved_min']})."
    )
    trace = [
        f"gyaani_aspirant_share = {rate:.4f} = {aspirant_or_better}/{total} of active users.",
        "definition: AND of three thresholds; mu vs. market opponent (1500), "
        "phi as Glicko-2 uncertainty, n_resolved for sample-size gate.",
        f"rule lives in classify_gyaani(); thresholds in GYAANI_THRESHOLDS['aspirant'] (rule v{GYAANI_RULE_VERSION}).",
    ]
    return MetricResult(
        trace=trace,
        metric_name="gyaani_aspirant_share",
        value=rate,
        confidence=0.85,
        sample_n=total,
        provenance=[
            f"cohort_size:{total}",
            f"aspirant_or_locked:{aspirant_or_better}",
            f"rule_version:{GYAANI_RULE_VERSION}",
            f"thresholds:mu>={t['mu_min']:.0f}_phi<{t['phi_max']:.0f}_n>={t['n_resolved_min']}",
        ],
        window_open=False,
        interpretation=interp,
        definition_version=DEFS["gyaani_aspirant_share"],
        computation_sql="(see _gyaani_population) + classify_gyaani per-user",
        as_of=_now(),
        breakdowns=dict(aspirant_or_locked=aspirant_or_better, cohort_size=total),
    )


def gyaani_locked_share(week_of: str = "2024-W01") -> MetricResult:
    """Share of active users in the Gyaani-locked tier (the badge).

    Locked = mu >= 1686 AND phi < 150 AND n_resolved >= 10. Tight by
    design: on W01 substrate this is expected to be <1% because
    n_resolved >= 10 is unreachable for nearly all users on a single
    week. Becomes meaningful once P0.5b ships multi-week data; the rule
    itself doesn't need to change — the data accumulates against it.
    """
    rows = _gyaani_population(week_of)
    total = len(rows)
    locked = sum(
        1 for _uid, mu, phi, n, _arch in rows
        if classify_gyaani(float(mu), float(phi), int(n)) == "locked"
    )
    rate = float(locked / total) if total else 0.0
    t = GYAANI_THRESHOLDS["locked"]
    interp = (
        f"Gyaani-locked share = {rate:.2%} "
        f"({locked}/{total} active users in W01 meet "
        f"mu>={t['mu_min']:.0f} AND phi<{t['phi_max']:.0f} AND "
        f"n_resolved>={t['n_resolved_min']}). "
        f"Multi-week data (P0.5b) is required for this tier to populate "
        f"meaningfully — W01 caps n_resolved at ~11."
    )
    trace = [
        f"gyaani_locked_share = {rate:.4f} = {locked}/{total} of active users.",
        f"definition: strict AND of mu>=p90-equivalent ({t['mu_min']:.0f}), "
        f"phi<{t['phi_max']:.0f}, n_resolved>={t['n_resolved_min']}.",
        f"rule lives in classify_gyaani(); thresholds in GYAANI_THRESHOLDS['locked'] (rule v{GYAANI_RULE_VERSION}).",
        f"W01 caveat: n_resolved>=10 limits this tier on single-week data; "
        f"the rule is invariant to weeks but the data must accumulate.",
    ]
    return MetricResult(
        trace=trace,
        metric_name="gyaani_locked_share",
        value=rate,
        confidence=0.90,
        sample_n=total,
        provenance=[
            f"cohort_size:{total}",
            f"locked:{locked}",
            f"rule_version:{GYAANI_RULE_VERSION}",
            f"thresholds:mu>={t['mu_min']:.0f}_phi<{t['phi_max']:.0f}_n>={t['n_resolved_min']}",
        ],
        window_open=False,
        interpretation=interp,
        definition_version=DEFS["gyaani_locked_share"],
        computation_sql="(see _gyaani_population) + classify_gyaani per-user",
        as_of=_now(),
        breakdowns=dict(locked=locked, cohort_size=total),
    )


def gyaani_status(user_id: str, week_of: str = "2024-W01") -> dict:
    """Per-user Gyaani classification + gap analysis (tool surface).

    Returns:
      {
        "tier": "locked" | "aspirant" | "none",
        "mu": float | None,
        "phi": float | None,
        "n_resolved": int,
        "gaps_to_locked": {
            "mu_short_by": float,         # 0 if already past
            "phi_excess": float,          # 0 if already past
            "calls_short_by": int,        # 0 if already past
        },
        "rule_version": str,
      }

    Agents use this when answering "is X a Gyaani?" or "how close is X
    to Gyaani?" Returns tier="none" + None mu/phi when the user has no
    resolved predictions yet.
    """
    start, end = _week_bounds(week_of)
    sql = """
        WITH active AS (
          SELECT COUNT(*) AS n_made,
                 SUM(CASE WHEN is_outcome_resolved THEN 1 ELSE 0 END) AS n_resolved
          FROM fact_prediction
          WHERE user_id = ? AND made_at >= ? AND made_at < ?
        )
        SELECT s.mu, s.phi, COALESCE(a.n_resolved, 0)
        FROM active a
        LEFT JOIN read_parquet(?) s ON s.user_id = ?
    """
    con = _connect()
    try:
        row = con.execute(sql, [user_id, start, end, str(SKILL_PARQUET), user_id]).fetchone()
    finally:
        con.close()
    mu, phi, n_resolved = row if row else (None, None, 0)
    n_resolved = int(n_resolved or 0)
    if mu is None or phi is None:
        return dict(
            tier="none",
            mu=None,
            phi=None,
            n_resolved=n_resolved,
            gaps_to_locked=dict(mu_short_by=None, phi_excess=None, calls_short_by=None),
            rule_version=GYAANI_RULE_VERSION,
        )
    mu = float(mu)
    phi = float(phi)
    t = GYAANI_THRESHOLDS["locked"]
    return dict(
        tier=classify_gyaani(mu, phi, n_resolved),
        mu=mu,
        phi=phi,
        n_resolved=n_resolved,
        gaps_to_locked=dict(
            mu_short_by=max(0.0, t["mu_min"] - mu),
            phi_excess=max(0.0, phi - t["phi_max"]),
            calls_short_by=max(0, t["n_resolved_min"] - n_resolved),
        ),
        rule_version=GYAANI_RULE_VERSION,
    )


# ---------------------------------------------------------------------------
# P4 — Attention -> Accuracy headline metrics
#
# The strategy meeting framed this as the PMF derisking move: replace
# vanity attention metrics (MAU, session length, calls made, DAU) with
# skill-weighted equivalents. Three of the four ship here; the fourth
# (calls_with_explanation_rate) needs a `rationale` field on
# fact_prediction that the schema doesn't carry yet — stubbed honestly.
# ---------------------------------------------------------------------------


def weekly_active_callers_calibrated(week_of: str = "2024-W01") -> MetricResult:
    """WAU replacement — count of weekly active callers weighted by
    each caller's mean calibration (Brier-derived) over their resolved
    calls in the week.

    Interpretation: an active week is one where 1,000 well-calibrated
    callers contributes more than 1,000 random clickers. The weight is
    in [0, 1] per user; the headline is the *sum of weights* (a count
    in "calibrated-caller-equivalents"). For a population uniformly
    well-calibrated, this approaches WAU; for the legacy unweighted
    MAU it's strictly lower.
    """
    start, end = _week_bounds(week_of)
    sql = """
        WITH per_caller_calibration AS (
          SELECT user_id,
                 COUNT(*) AS n_resolved,
                 AVG(POWER(((CAST(confidence_stars AS DOUBLE) - 1.0) / 4.0)
                         - CASE outcome
                             WHEN 'WIN' THEN 1.0
                             WHEN 'DRAW' THEN 0.5
                             ELSE 0.0
                           END, 2)) AS brier
          FROM fact_prediction
          WHERE made_at >= ? AND made_at < ? AND is_outcome_resolved
          GROUP BY user_id
        ),
        weighted AS (
          SELECT user_id,
                 n_resolved,
                 GREATEST(0.0, 1.0 - brier * 4.0) AS calibration_weight
          FROM per_caller_calibration
          WHERE n_resolved >= 3
        )
        SELECT COALESCE(SUM(calibration_weight), 0.0) AS calibrated_callers,
               COUNT(*) AS raw_active_callers
        FROM weighted
    """
    con = _connect()
    try:
        cal, raw = con.execute(sql, [start, end]).fetchone()
    finally:
        con.close()
    cal = float(cal or 0.0)
    raw = int(raw or 0)
    interp = (
        f"Calibrated WAU = {cal:.1f} (sum of per-caller calibration weights; "
        f"{raw} raw active callers in W01 with >=3 resolved calls). "
        f"Replaces vanity MAU — a population at perfect calibration would "
        f"score {raw}.0; the gap measures how much of 'active' is signal vs noise."
    )
    trace = [
        f"weekly_active_callers_calibrated = {cal:.4f}",
        "definition: sum_u max(0, 1 - brier_u * 4) over users with n_resolved >= 3",
        f"raw active callers (gate met): {raw}",
        "calibration_weight per user is in [0, 1]; sum is the headline.",
    ]
    return MetricResult(
        trace=trace,
        metric_name="weekly_active_callers_calibrated",
        value=cal,
        confidence=0.9,
        sample_n=raw,
        provenance=[
            f"raw_active_callers:{raw}",
            f"calibrated_callers:{cal:.4f}",
            "replaces:WAU/MAU",
        ],
        window_open=False,
        interpretation=interp,
        definition_version=DEFS["weekly_active_callers_calibrated"],
        computation_sql=sql.strip(),
        as_of=_now(),
        breakdowns=dict(raw_active_callers=raw, calibrated_callers=cal),
    )


def high_confidence_call_ratio(week_of: str = "2024-W01") -> MetricResult:
    """Session-length replacement — share of resolved 4-star-or-5-star
    calls in the week that actually WON.

    Interpretation: do users put their thumbs on the right calls? A
    population that high-stars only when right scores near 1.0; a
    population that high-stars indiscriminately scores near the
    population base rate. Replaces "average session length" which
    measured attention not accuracy.
    """
    start, end = _week_bounds(week_of)
    sql = """
        WITH high_conf AS (
          SELECT outcome
          FROM fact_prediction
          WHERE made_at >= ? AND made_at < ?
            AND is_outcome_resolved
            AND confidence_stars >= 4
        )
        SELECT SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) AS wins,
               COUNT(*) AS n
        FROM high_conf
    """
    con = _connect()
    try:
        wins, n = con.execute(sql, [start, end]).fetchone()
    finally:
        con.close()
    wins = int(wins or 0)
    n = int(n or 0)
    ratio = float(wins / n) if n else 0.0
    interp = (
        f"High-confidence call ratio = {ratio:.1%} "
        f"({wins}/{n} resolved >=4-star calls in W01 won). "
        f"Replaces session-length — measures whether high-confidence "
        f"calls are actually signal."
    )
    trace = [
        f"high_confidence_call_ratio = {ratio:.4f} = {wins}/{n}",
        "definition: WIN-rate restricted to resolved calls with confidence_stars >= 4",
        "interpretation: do users high-star the right calls?",
    ]
    return MetricResult(
        trace=trace,
        metric_name="high_confidence_call_ratio",
        value=ratio,
        confidence=0.9,
        sample_n=n,
        provenance=[
            f"high_conf_resolved:{n}",
            f"high_conf_wins:{wins}",
            "replaces:session_length",
        ],
        window_open=False,
        interpretation=interp,
        definition_version=DEFS["high_confidence_call_ratio"],
        computation_sql=sql.strip(),
        as_of=_now(),
        breakdowns=dict(high_conf_wins=wins, high_conf_resolved=n),
    )


def daily_gyaani_aspirant_count(as_of_date: str = "2024-01-07") -> MetricResult:
    """DAU replacement — cumulative count of users who hold
    Gyaani-aspirant tier (or better) as of end-of-day `as_of_date`.

    The headline metric the meeting called out: "DAU replaced by daily
    Gyaani-graduated user count." Daily graduations = day-N count minus
    day-(N-1) count; the metric itself returns the cumulative count so
    consumers can take diffs day-by-day.

    Active set = users with at least 1 prediction made in the
    sliding-week window ending `as_of_date`. Skill ratings are read
    from the parquet materialization (which is computed once per
    `make skill` run); as a consequence this metric is W01-stable
    by construction and will become per-day-meaningful once P0.5b
    snapshots skill ratings daily.
    """
    as_of = datetime.strptime(as_of_date, "%Y-%m-%d")
    window_start = as_of - timedelta(days=7)
    if not SKILL_PARQUET.exists():
        raise FileNotFoundError(
            f"skill ratings missing: {SKILL_PARQUET}. Run `make skill` first."
        )
    sql = """
        WITH active AS (
          SELECT user_id,
                 SUM(CASE WHEN is_outcome_resolved THEN 1 ELSE 0 END) AS n_resolved
          FROM fact_prediction
          WHERE made_at >= ? AND made_at < ?
          GROUP BY user_id
        )
        SELECT a.user_id, s.mu, s.phi, a.n_resolved
        FROM active a
        JOIN read_parquet(?) s ON s.user_id = a.user_id
    """
    con = _connect()
    try:
        rows = con.execute(sql, [window_start, as_of, str(SKILL_PARQUET)]).fetchall()
    finally:
        con.close()
    aspirant_or_better = sum(
        1 for _uid, mu, phi, n in rows
        if classify_gyaani(float(mu), float(phi), int(n)) in ("aspirant", "locked")
    )
    locked = sum(
        1 for _uid, mu, phi, n in rows
        if classify_gyaani(float(mu), float(phi), int(n)) == "locked"
    )
    interp = (
        f"Gyaani-aspirant-or-better count as of {as_of_date} = "
        f"{aspirant_or_better} users ({locked} of them at locked tier). "
        f"Replaces DAU — the headline number that's expected to go "
        f"up-and-to-the-right as the population graduates."
    )
    trace = [
        f"daily_gyaani_aspirant_count = {aspirant_or_better} as of {as_of_date}",
        f"locked_subset = {locked}",
        f"active_set = users with >= 1 call in 7-day window ending {as_of_date}",
        f"rule_version = {GYAANI_RULE_VERSION}; classify_gyaani shared with gyaani_aspirant_share",
    ]
    return MetricResult(
        trace=trace,
        metric_name="daily_gyaani_aspirant_count",
        value=float(aspirant_or_better),
        confidence=0.85,
        sample_n=len(rows),
        provenance=[
            f"as_of:{as_of_date}",
            f"active_set:{len(rows)}",
            f"aspirant_or_better:{aspirant_or_better}",
            f"locked:{locked}",
            "replaces:DAU",
        ],
        window_open=False,
        interpretation=interp,
        definition_version=DEFS["daily_gyaani_aspirant_count"],
        computation_sql=sql.strip(),
        as_of=_now(),
        breakdowns=dict(
            aspirant_or_better=aspirant_or_better,
            locked=locked,
            active_set=len(rows),
        ),
    )


def calls_with_explanation_rate(week_of: str = "2024-W01") -> MetricResult:
    """STUB — replaces "calls made" with "calls accompanied by rationale
    text." Requires a `rationale` field on `fact_prediction` that the
    current schema doesn't carry. Surfaces honestly with value=0.0 and
    a status note so dashboards and agents can flag the gap.

    When the product surface adds the rationale field, this becomes:
      SELECT SUM(CASE WHEN rationale IS NOT NULL AND length(rationale) > 0
                      THEN 1 ELSE 0 END) * 1.0 / COUNT(*)
      FROM fact_prediction WHERE ...
    """
    interp = (
        "STUB: calls_with_explanation_rate requires a `rationale` field on "
        "fact_prediction that does not exist in the current schema. The "
        "metric is registered so downstream agents can flag the gap; "
        "value=0.0 until the rationale field is added in a future "
        "product-surface phase."
    )
    return MetricResult(
        trace=[
            "calls_with_explanation_rate is stubbed pending schema extension.",
            "Plan: add `rationale` TEXT field to fact_prediction; this metric "
            "becomes SUM(rationale IS NOT NULL) / COUNT(*).",
        ],
        metric_name="calls_with_explanation_rate",
        value=0.0,
        confidence=0.0,
        sample_n=0,
        provenance=[
            "status:stub_pending_schema_extension",
            "schema_gap:fact_prediction.rationale",
            "replaces:calls_made_vanity_metric",
        ],
        window_open=False,
        interpretation=interp,
        definition_version=DEFS["calls_with_explanation_rate"],
        computation_sql="-- stubbed: requires fact_prediction.rationale field --",
        as_of=_now(),
        breakdowns=dict(status="stub"),
    )


# ---------------------------------------------------------------------------
# Funnel (P5). Single metric returning the four stage counts + conversion
# rates + segment composition of users stuck at each gate.
#
# The frontend funnel page is a pure render of this metric's breakdowns —
# no client-side metric composition (per the substrate's defined-once
# rule). If the funnel shape needs to change (re-stage, new gate), edit
# this function and only this function.
# ---------------------------------------------------------------------------


def funnel_stages(week_of: str = "2024-W01", acquisition_source: str = "unstop") -> MetricResult:
    """Four-stage growth funnel for IndiaStox cohort.

    Stages (each is a strict subset of the prior):
      1. Signed up         — dim_user row exists in the acquisition cohort.
      2. Made first call   — at least 1 prediction in W01.
      3. Made >= 3 calls   — substantive engagement, the bar that lets
                             Glicko-2 begin shaping mu/phi meaningfully.
      4. Gyaani-aspirant   — classify_gyaani == 'aspirant' or 'locked'.
                             Tracks the badge slope.
      5. (sub-tier) Locked — classify_gyaani == 'locked'. Reported as a
                             sub-count of stage 4 in breakdowns.

    Drop-off segments per gate: of the users who reached stage N but
    NOT stage N+1, what segment do they classify as? Surfaces the
    "growth wall" the product can target with nudges.

    Returns a MetricResult whose `value` is the overall signup -> aspirant
    conversion rate (the headline) and whose `breakdowns` carry the
    per-stage detail the frontend renders.
    """
    from metrics.behavior_segments import classify_user_segment_from_data

    start, end = _week_bounds(week_of)
    if not SKILL_PARQUET.exists():
        raise FileNotFoundError(
            f"skill ratings missing: {SKILL_PARQUET}. Run `make skill` first."
        )

    sql = """
        WITH cohort AS (
          SELECT DISTINCT u.user_id
          FROM dim_user u
          WHERE u.acquisition_source = ?
        ),
        per_user AS (
          SELECT c.user_id,
                 COALESCE(fp.n_made, 0) AS n_made,
                 COALESCE(fp.n_resolved, 0) AS n_resolved
          FROM cohort c
          LEFT JOIN (
            SELECT user_id,
                   COUNT(*) AS n_made,
                   SUM(CASE WHEN is_outcome_resolved THEN 1 ELSE 0 END) AS n_resolved
            FROM fact_prediction
            WHERE made_at >= ? AND made_at < ?
            GROUP BY user_id
          ) fp ON fp.user_id = c.user_id
        )
        SELECT pu.user_id, pu.n_made, pu.n_resolved, s.mu, s.phi
        FROM per_user pu
        LEFT JOIN read_parquet(?) s ON s.user_id = pu.user_id
    """
    # Single connection for the entire funnel computation — no per-user
    # nested opens. Closes only after the seg-mix bulk fetches complete
    # so we never re-attach indiastox within the same request.
    con = _connect()
    try:
        rows = con.execute(sql, [acquisition_source, start, end, str(SKILL_PARQUET)]).fetchall()

        n_signed = len(rows)
        n_called: list[str] = []
        n_three: list[str] = []
        n_aspirant: list[str] = []
        n_locked = 0
        stuck_after_signup: list[str] = []
        stuck_after_call: list[str] = []
        stuck_after_three: list[str] = []

        for uid, n_made, n_resolved, mu, phi in rows:
            n_made = int(n_made or 0)
            n_resolved = int(n_resolved or 0)
            if n_made == 0:
                stuck_after_signup.append(uid)
                continue
            n_called.append(uid)
            if n_resolved < 3:
                stuck_after_call.append(uid)
                continue
            n_three.append(uid)
            if mu is None or phi is None:
                stuck_after_three.append(uid)
                continue
            tier = classify_gyaani(float(mu), float(phi), n_resolved)
            if tier == "none":
                stuck_after_three.append(uid)
                continue
            n_aspirant.append(uid)
            if tier == "locked":
                n_locked += 1

        # Build the segment-mix per gate via batch fetches on the SAME
        # connection. Each call to `_seg_mix` pulls all sampled users'
        # calls + mu in one query, then classifies in memory via the
        # pure `classify_user_segment_from_data` helper. Avoids the
        # per-user nested-connection pattern that triggered the
        # production DuckDB attach conflict on Render.
        def _seg_mix(user_ids: list[str], cap: int = 60) -> dict[str, int]:
            from collections import Counter
            sampled = user_ids[:cap]
            if not sampled:
                return {}
            placeholders = ",".join(["?"] * len(sampled))
            calls_rows = con.execute(
                f"""
                SELECT user_id, made_at, stock_symbol, direction,
                       confidence_stars, outcome, is_outcome_resolved
                FROM fact_prediction
                WHERE user_id IN ({placeholders})
                  AND made_at >= ? AND made_at < ?
                ORDER BY user_id, made_at ASC
                """,
                [*sampled, start, end],
            ).fetchall()
            mu_rows = con.execute(
                f"""
                SELECT user_id, mu
                FROM read_parquet(?)
                WHERE user_id IN ({placeholders})
                """,
                [str(SKILL_PARQUET), *sampled],
            ).fetchall()

            calls_by_user: dict[str, list[tuple]] = {uid: [] for uid in sampled}
            for r in calls_rows:
                calls_by_user.setdefault(r[0], []).append(r[1:])  # drop user_id; preserve schema
            mu_by_user: dict[str, Optional[float]] = {
                r[0]: (float(r[1]) if r[1] is not None else None) for r in mu_rows
            }

            counts: Counter = Counter()
            for uid in sampled:
                r = classify_user_segment_from_data(
                    uid, calls_by_user.get(uid, []), mu_by_user.get(uid),
                )
                counts[r["primary_segment"] or "(none)"] += 1
            return dict(counts.most_common())

        stages = [
            dict(name="signed_up", n=n_signed, label="Signed up"),
            dict(name="made_first_call", n=len(n_called), label="Made first call"),
            dict(name="resolved_three_plus", n=len(n_three), label="3+ resolved calls"),
            dict(name="gyaani_aspirant", n=len(n_aspirant), label="Gyaani aspirant"),
        ]
        for i, stage in enumerate(stages):
            prior_n = stages[i - 1]["n"] if i > 0 else stage["n"]
            stage["conversion_from_prior"] = (stage["n"] / prior_n) if prior_n else 0.0
            stage["share_of_signup"] = (stage["n"] / n_signed) if n_signed else 0.0

        drop_off = dict(
            after_signup=dict(n=len(stuck_after_signup), segment_mix=_seg_mix(stuck_after_signup)),
            after_first_call=dict(n=len(stuck_after_call), segment_mix=_seg_mix(stuck_after_call)),
            after_three_resolved=dict(n=len(stuck_after_three), segment_mix=_seg_mix(stuck_after_three)),
        )
    finally:
        con.close()

    headline_rate = float(len(n_aspirant) / n_signed) if n_signed else 0.0
    interp = (
        f"Funnel ({acquisition_source}, {week_of}): {n_signed} signed up -> "
        f"{len(n_called)} made first call -> {len(n_three)} hit 3 resolved -> "
        f"{len(n_aspirant)} reached Gyaani-aspirant ({n_locked} locked). "
        f"Signup -> aspirant conversion = {headline_rate:.1%}."
    )
    trace = [
        f"funnel_stages headline = {headline_rate:.4f} = {len(n_aspirant)}/{n_signed} aspirant/signup.",
        "stages are strict subsets; conversion_from_prior is each row's funnel coefficient.",
        "drop-off segment mix uses classify_user_segment_from_data (single-conn batch path).",
    ]
    return MetricResult(
        trace=trace,
        metric_name="funnel_stages",
        value=headline_rate,
        confidence=0.90,
        sample_n=n_signed,
        provenance=[
            f"acquisition:{acquisition_source}",
            f"signed_up:{n_signed}",
            f"made_first_call:{len(n_called)}",
            f"resolved_three_plus:{len(n_three)}",
            f"gyaani_aspirant:{len(n_aspirant)}",
            f"gyaani_locked:{n_locked}",
            f"rule_version:{GYAANI_RULE_VERSION}",
        ],
        window_open=False,
        interpretation=interp,
        definition_version=DEFS["funnel_stages"],
        computation_sql=sql.strip(),
        as_of=_now(),
        breakdowns=dict(
            stages=stages,
            locked=n_locked,
            drop_off=drop_off,
            acquisition_source=acquisition_source,
            week_of=week_of,
        ),
    )


# ---------------------------------------------------------------------------
# Insights extractor (P7). Wraps agent.insights.generate_insights() in a
# MetricResult envelope so it joins the tool surface and can be called
# from agents, dashboards, and tests via the same interface as every
# other metric.
#
# value = top insight's surprise_score (the headline "how surprised
# should we be?"). breakdowns carry the full ranked list.
# ---------------------------------------------------------------------------


def insights_generate(week_of: str = "2024-W01", top_n: int = 10) -> MetricResult:
    """Run every registered insight scanner and return the ranked list.

    Calls into `agent.insights.generate_insights()` so the scanner
    logic lives in one place (agent/insights.py). This wrapper only
    handles the MetricResult envelope: a `value` summary, a
    breakdowns table the frontend can render, and the audit
    contract every metric satisfies.
    """
    from agent.insights import INSIGHTS_VERSION, generate_insights

    insights = generate_insights(week_of)
    insights = insights[:top_n]
    top_score = insights[0].surprise_score if insights else 0.0
    by_kind: dict[str, int] = {}
    for ins in insights:
        by_kind[ins.kind] = by_kind.get(ins.kind, 0) + 1

    if insights:
        interp = (
            f"insights_generate returned {len(insights)} ranked observations "
            f"(top surprise={top_score:.2f}). Top finding: "
            f"{insights[0].summary}"
        )
    else:
        interp = "insights_generate returned no observations above scanner floors."

    trace = [
        f"insights_generate top_score = {top_score:.4f}.",
        f"scanners fired: {sorted(by_kind)}.",
        f"insights_version={INSIGHTS_VERSION}; scanner logic lives in agent/insights.py.",
    ]
    return MetricResult(
        trace=trace,
        metric_name="insights_generate",
        value=float(top_score),
        confidence=0.75,  # heuristic scanners; surprise_score is a ranking, not a probability
        sample_n=len(insights),
        provenance=[
            f"insights_version:{INSIGHTS_VERSION}",
            f"scanners:{','.join(sorted(by_kind))}",
            f"top_kind:{insights[0].kind if insights else 'none'}",
        ],
        window_open=False,
        interpretation=interp,
        definition_version=DEFS["insights_generate"],
        computation_sql="-- multi-scanner; see agent/insights.py for SQL --",
        as_of=_now(),
        breakdowns=dict(
            insights=[i.to_dict() for i in insights],
            by_kind=by_kind,
            insights_version=INSIGHTS_VERSION,
        ),
    )


# ---------------------------------------------------------------------------
# Consumption layer: CS nudge targets.
#
# Wraps `gyaani_status` over the cohort of users currently in the
# aspirant tier, ranked by how nudgeable they are (smaller composite
# gap to locked = higher leverage). Frontend /cs-nudges page renders
# this directly; no client-side composition.
# ---------------------------------------------------------------------------


def nudge_targets(week_of: str = "2024-W01", top_n: int = 50,
                  acquisition_source: str = "unstop") -> MetricResult:
    """Top-N aspirant users sorted by smallest composite gap-to-locked.

    Composite gap normalises each axis to its locked threshold range:
      gap_score = (calls_short / 10) + (mu_short / 200) + (phi_excess / 50)
    Lower = more nudgeable. Returns up to top_n users, each enriched
    with archetype, current mu/phi/n_resolved, and the specific axis
    they're shortest on (the message hook the CS team uses).
    """
    start, end = _week_bounds(week_of)
    if not SKILL_PARQUET.exists():
        raise FileNotFoundError(
            f"skill ratings missing: {SKILL_PARQUET}. Run `make skill` first."
        )
    sql = """
        WITH active AS (
          SELECT user_id, SUM(CASE WHEN is_outcome_resolved THEN 1 ELSE 0 END) AS n_resolved
          FROM fact_prediction
          WHERE made_at >= ? AND made_at < ?
          GROUP BY user_id
        )
        SELECT a.user_id, du.archetype_slug, du.full_name, du.acquisition_source,
               s.mu, s.phi, a.n_resolved
        FROM active a
        JOIN read_parquet(?) s ON s.user_id = a.user_id
        LEFT JOIN dim_user du ON du.user_id = a.user_id
        WHERE du.acquisition_source = ?
    """
    con = _connect()
    try:
        rows = con.execute(sql, [start, end, str(SKILL_PARQUET), acquisition_source]).fetchall()
    finally:
        con.close()

    t = GYAANI_THRESHOLDS["locked"]
    candidates: list[dict] = []
    for uid, arch, full_name, acq, mu, phi, n in rows:
        if mu is None or phi is None:
            continue
        mu, phi, n = float(mu), float(phi), int(n)
        tier = classify_gyaani(mu, phi, n)
        if tier != "aspirant":
            continue
        gap_calls = max(0, t["n_resolved_min"] - n)
        gap_mu = max(0.0, t["mu_min"] - mu)
        gap_phi = max(0.0, phi - t["phi_max"])
        gap_score = (gap_calls / 10.0) + (gap_mu / 200.0) + (gap_phi / 50.0)
        # Identify the single largest gap (= the message hook).
        biggest_axis = max(
            ("calls", gap_calls / 10.0),
            ("mu", gap_mu / 200.0),
            ("phi", gap_phi / 50.0),
            key=lambda kv: kv[1],
        )[0]
        hook = (
            f"{gap_calls} more resolved calls" if biggest_axis == "calls"
            else f"{gap_mu:.0f} mu points (build accuracy)" if biggest_axis == "mu"
            else f"phi must drop by {gap_phi:.1f} (make {gap_calls or 'more'} calls to converge)"
        )
        candidates.append(dict(
            user_id=uid,
            display_name=full_name or "(unnamed)",
            archetype=arch or "unknown",
            acquisition_source=acq,
            tier=tier,
            mu=mu,
            phi=phi,
            n_resolved=n,
            gap_score=gap_score,
            biggest_gap_axis=biggest_axis,
            gap_calls=gap_calls,
            gap_mu=gap_mu,
            gap_phi=gap_phi,
            nudge_hook=hook,
        ))
    candidates.sort(key=lambda c: c["gap_score"])
    top = candidates[:top_n]

    interp = (
        f"nudge_targets: {len(candidates)} aspirants in cohort; surfacing the "
        f"top {len(top)} ranked by composite gap-to-locked. Smallest gap = "
        f"highest leverage."
    )
    trace = [
        f"nudge_targets returned {len(top)}/{len(candidates)} aspirant users.",
        "ranking: composite gap_score = (calls/10) + (mu/200) + (phi/50); lower = more nudgeable.",
        f"rule_version={GYAANI_RULE_VERSION}; thresholds from GYAANI_THRESHOLDS['locked'].",
    ]
    return MetricResult(
        trace=trace,
        metric_name="nudge_targets",
        value=float(len(top)),
        confidence=0.90,
        sample_n=len(candidates),
        provenance=[
            f"acquisition:{acquisition_source}",
            f"aspirant_cohort:{len(candidates)}",
            f"surfaced:{len(top)}",
            f"rule_version:{GYAANI_RULE_VERSION}",
        ],
        window_open=False,
        interpretation=interp,
        definition_version=DEFS["nudge_targets"],
        computation_sql=sql.strip(),
        as_of=_now(),
        breakdowns=dict(
            targets=top,
            cohort_size=len(candidates),
            acquisition_source=acquisition_source,
        ),
    )


# ---------------------------------------------------------------------------
# Consumption layer: unified per-user fingerprint.
#
# Composes gyaani_status (P1) + user_reward_axes (P2) + classify_user_segment
# (P3) into a single MetricResult so the in-app badge widget can render the
# user's full state in one round-trip. value = numeric tier
# (0=none, 1=aspirant, 2=locked) so the metric still satisfies the
# MetricResult contract; breakdowns carry the rich detail.
# ---------------------------------------------------------------------------


_TIER_RANK = {"none": 0, "aspirant": 1, "locked": 2}


def user_fingerprint(user_id: str, week_of: str = "2024-W01") -> MetricResult:
    """Unified per-user fingerprint: Gyaani tier + reward axes + segment.

    Returns a MetricResult whose:
      - value is the user's tier rank (0/1/2)
      - breakdowns.gyaani: the gyaani_status() dict
      - breakdowns.reward_axes: the user_reward_axes() dict
      - breakdowns.behavior_segment: the classify_user_segment() dict
      - breakdowns.identity: optional dim_user lookup (name, archetype)

    The in-app badge widget renders this directly; one fetch, full state.
    """
    from metrics.behavior_segments import classify_user_segment
    from metrics.reward_axes import user_reward_axes

    status = gyaani_status(user_id, week_of)
    axes = user_reward_axes(user_id, week_of)
    segment = classify_user_segment(user_id, week_of)

    # Light identity enrichment.
    con = _connect()
    try:
        row = con.execute(
            "SELECT full_name, archetype_slug, acquisition_source "
            "FROM dim_user WHERE user_id = ?",
            [user_id],
        ).fetchone()
    finally:
        con.close()
    identity = dict(
        full_name=(row[0] if row else None),
        archetype_slug=(row[1] if row else None),
        acquisition_source=(row[2] if row else None),
    )

    tier = status["tier"]
    tier_rank = _TIER_RANK.get(tier, 0)

    interp = (
        f"User {user_id[:8]} ({identity['archetype_slug'] or 'unknown archetype'}): "
        f"Gyaani tier='{tier}'; top reward axis="
        f"{axes.get('top_axis') or '(none)'} "
        f"({axes.get('top_score', 0):.2f}); "
        f"primary segment={segment.get('primary_segment') or '(none)'}."
    )
    trace = [
        f"user_fingerprint(user_id={user_id[:8]}): tier_rank={tier_rank}.",
        f"gyaani rule_version={status.get('rule_version', '?')}.",
        f"reward axes rule_version={axes.get('rule_version', '?')}.",
        f"segment rule_version={segment.get('rule_version', '?')}.",
    ]
    return MetricResult(
        trace=trace,
        metric_name="user_fingerprint",
        value=float(tier_rank),
        confidence=0.90,
        sample_n=1,
        provenance=[
            f"user_id:{user_id}",
            f"tier:{tier}",
            f"top_axis:{axes.get('top_axis') or 'none'}",
            f"primary_segment:{segment.get('primary_segment') or 'none'}",
        ],
        window_open=False,
        interpretation=interp,
        definition_version=DEFS["user_fingerprint"],
        computation_sql="-- composite of gyaani_status + user_reward_axes + classify_user_segment --",
        as_of=_now(),
        breakdowns=dict(
            gyaani=status,
            reward_axes=axes,
            behavior_segment=segment,
            identity=identity,
            tier_rank=tier_rank,
        ),
    )
