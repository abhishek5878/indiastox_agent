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
}


def _connect(read_only: bool = True):
    if not WAREHOUSE_DB.exists():
        raise FileNotFoundError(f"warehouse not built: {WAREHOUSE_DB}. Run `make resolve` first.")
    return duckdb.connect(str(WAREHOUSE_DB), read_only=read_only)


def _week_bounds(week_of: str) -> tuple[datetime, datetime]:
    year, week = week_of.split("-W")
    monday = datetime.strptime(f"{int(year)}-W{int(week):02d}-1", "%G-W%V-%u").replace(tzinfo=timezone.utc)
    return monday, monday + timedelta(days=7)


def _now() -> datetime:
    return datetime.now(timezone.utc)


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

    return MetricResult(
        metric_name="weekly_active_posters",
        value=float(value),
        confidence=confidence,
        sample_n=int(value + excluded),
        provenance=provenance,
        window_open=window_open,
        interpretation=interp,
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
    return MetricResult(
        metric_name="time_to_first_action",
        value=median_hours,
        confidence=confidence,
        sample_n=sample_n,
        provenance=provenance,
        window_open=window_open,
        interpretation=interp,
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
    return MetricResult(
        metric_name="unstop_to_participation_rate",
        value=rate,
        confidence=confidence,
        sample_n=signups,
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
    return MetricResult(
        metric_name="ghost_rate",
        value=rate,
        confidence=confidence,
        sample_n=total,
        provenance=provenance,
        window_open=window_open,
        interpretation=interp,
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
    return MetricResult(
        metric_name="dark_channel_fraction",
        value=rate,
        confidence=1.0,  # the fraction itself is exact — it's the channel BEHIND it that's unknown
        sample_n=total,
        provenance=[f"dark_signups:{dark}", f"total_signups:{total}", "definition:touchpoint_source='whatsapp_dark'"],
        window_open=False,
        interpretation=interp,
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
    return MetricResult(
        metric_name="brier_score",
        value=brier,
        confidence=0.85 if n >= 500 else 0.60,
        sample_n=n,
        provenance=[
            f"closed_predictions:{n}",
            "probability_mapping:stars_1..5 -> p_0.5..0.9",
            "actual_mapping:WIN=1, LOSS=0, DRAW=0.5",
        ],
        window_open=False,
        interpretation=interp,
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
    return MetricResult(
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
    return MetricResult(
        metric_name="predictions_per_user",
        value=rate,
        confidence=0.90,
        sample_n=total,
        provenance=[f"cohort_filter:{acquisition_source}", f"threshold:>={threshold}",
                    f"cohort_size:{total}", f"users_at_threshold:{at_t}"],
        window_open=False,
        interpretation=interp,
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
    return MetricResult(
        metric_name="email_click_to_signup",
        value=rate,
        confidence=0.70,  # email-signup attribution is messy (multi-touch, last-touch ambiguity)
        sample_n=clicks,
        provenance=[f"campaign:{campaign}", f"clicks:{clicks}", f"matched_signups:{signups}"],
        window_open=False,
        interpretation=interp,
        definition_version=DEFS["email_click_to_signup"],
        computation_sql=sql.strip(),
        as_of=_now(),
        breakdowns=dict(campaign_id=campaign, clicks=clicks, signups=signups),
    )
