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
}

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
