"""Insight extractor — auto-rank surprising observations from the substrate (P7).

The strategy meeting framed two umbrella terms together: "groundbreaking
insights" and "growth hack". Both share a substrate: the metrics layer
already exposes 28 tools; what's missing is an agent that *scans* them
for anomalies and surfaces a ranked list of "things worth investigating".

This module is that agent. It runs four scanners over the W01 substrate
and returns a ranked list of Insight records, each carrying:
  - the scanner that found it (kind)
  - the subject (an archetype slug, a funnel gate, a user_id, etc.)
  - observed vs expected with a numeric gap
  - a [0, 1] surprise_score so insights from different scanners can be
    ranked against each other
  - a one-line natural-language summary
  - a suggested_experiment string the Growth Agent can file as a
    proposal through the existing bonus/experiment_loop pipeline

Scanners (all four real on W01):
  1. near_miss_aspirants  — users 1 axis short of Gyaani-locked
  2. archetype_design_surprise — observed aspirant rate vs archetype intent
  3. funnel_gate_clog     — top stuck segment per funnel gate
  4. axis_outliers        — archetype scores far from population mean

The output is consumed by `metrics.definitions.insights_generate()` which
packages the ranked list as a MetricResult. The dispatch table
`_SCANNERS` is the single source of truth that maps scanner name ->
function; new scanners register here.
"""
from __future__ import annotations

import statistics
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import duckdb

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from metrics.definitions import GYAANI_THRESHOLDS, classify_gyaani
from sim.archetypes import ARCHETYPES

INSIGHTS_VERSION = "1.0.0"

WAREHOUSE_DB = _REPO / "warehouse" / "indiastox.duckdb"
SKILL_PARQUET = _REPO / "data" / "skill_ratings.parquet"


@dataclass
class Insight:
    """One observation the substrate flagged as worth investigating.

    surprise_score is in [0, 1] so insights from different scanners can
    be ranked against each other; each scanner is responsible for
    normalising into that range with a documented mapping.
    """
    kind: str
    subject: str
    observed: float
    expected: float
    surprise_score: float
    summary: str
    suggested_experiment: str
    breakdown: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _load_population(week_of: str) -> list[tuple]:
    """Single warehouse pull — every scanner shares this read.

    Returns rows of (user_id, archetype_slug, mu, phi, n_resolved). Only
    users active in the window with a skill rating are returned.
    """
    from datetime import datetime, timedelta
    year, week = week_of.split("-W")
    start = datetime.strptime(f"{int(year)}-W{int(week):02d}-1", "%G-W%V-%u")
    end = start + timedelta(days=7)
    sql = """
        WITH active AS (
          SELECT user_id, SUM(CASE WHEN is_outcome_resolved THEN 1 ELSE 0 END) AS n_resolved
          FROM fact_prediction
          WHERE made_at >= ? AND made_at < ?
          GROUP BY user_id
        )
        SELECT a.user_id, du.archetype_slug, s.mu, s.phi, a.n_resolved
        FROM active a
        JOIN read_parquet(?) s ON s.user_id = a.user_id
        LEFT JOIN dim_user du ON du.user_id = a.user_id
    """
    con = duckdb.connect(str(WAREHOUSE_DB), read_only=False)
    try:
        return con.execute(sql, [start, end, str(SKILL_PARQUET)]).fetchall()
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Scanner 1: near-miss aspirants
# ---------------------------------------------------------------------------


def scan_near_miss_aspirants(rows: list[tuple], week_of: str, top_n: int = 5) -> list[Insight]:
    """Users currently in aspirant tier who are exactly ONE locked-threshold
    axis short of graduating to the badge. High-leverage nudge targets.

    surprise_score = 1.0 - (normalised gap). A user 1 call short = high
    score; a user 80mu short = lower.
    """
    locked = GYAANI_THRESHOLDS["locked"]
    near: list[tuple] = []
    for uid, arch, mu, phi, n in rows:
        if mu is None or phi is None:
            continue
        mu, phi, n = float(mu), float(phi), int(n)
        tier = classify_gyaani(mu, phi, n)
        if tier != "aspirant":
            continue
        gap_calls = max(0, locked["n_resolved_min"] - n)
        gap_mu = max(0.0, locked["mu_min"] - mu)
        gap_phi = max(0.0, phi - locked["phi_max"])
        axes_short = (gap_calls > 0) + (gap_mu > 0) + (gap_phi > 0)
        if axes_short != 1:
            continue
        # Normalise per-axis gap to [0, 1]; smaller gap = higher surprise (= more nudgeable).
        if gap_calls > 0:
            short_axis, score = "calls", 1.0 - min(gap_calls / 5.0, 1.0)
        elif gap_mu > 0:
            short_axis, score = "mu", 1.0 - min(gap_mu / 200.0, 1.0)
        else:
            short_axis, score = "phi", 1.0 - min(gap_phi / 50.0, 1.0)
        near.append((score, short_axis, uid, arch, mu, phi, n, gap_calls, gap_mu, gap_phi))

    near.sort(key=lambda r: -r[0])
    out: list[Insight] = []
    for score, axis, uid, arch, mu, phi, n, gc, gm, gp in near[:top_n]:
        gap_str = f"calls_short={gc}" if axis == "calls" else (
            f"mu_short={gm:.0f}" if axis == "mu" else f"phi_excess={gp:.1f}"
        )
        out.append(Insight(
            kind="near_miss_aspirant",
            subject=uid,
            observed=score,
            expected=1.0,
            surprise_score=float(score),
            summary=(
                f"User {uid[:8]} ({arch or 'unknown archetype'}) is one {axis} "
                f"away from Gyaani-locked: {gap_str} (mu={mu:.0f}, phi={phi:.0f}, n={n})."
            ),
            suggested_experiment=(
                f"Send a targeted nudge surfacing 'you are {gap_str} from the "
                f"Gyaani badge'; A/B test on near-miss aspirants and measure "
                f"locked-tier conversion lift within 7 days."
            ),
            breakdown=dict(user_id=uid, archetype=arch, mu=mu, phi=phi, n_resolved=n,
                           short_axis=axis, gap_calls=gc, gap_mu=gm, gap_phi=gp),
        ))
    return out


# ---------------------------------------------------------------------------
# Scanner 2: archetype design surprise
# ---------------------------------------------------------------------------


def _expected_aspirant_rate(archetype) -> float:
    """Heuristic mapping of archetype design to expected aspirant rate.

    Anchored on true_skill_mean (skill bias) AND time_budget (volume).
    Low-volume archetypes (time_budget < 20) get a discount because phi
    convergence depends on call count. Single source of expected-rate
    truth; if the heuristic changes, every scanner sees the change.
    """
    base = 0.40 + archetype.true_skill_mean * 0.25
    if archetype.daily_time_budget_minutes_mean < 20:
        base *= 0.5  # data starvation penalty
    if archetype.cohort_tag == "late_activator":
        base *= 0.2  # lurkers don't activate in W01 by design
    return max(0.0, min(1.0, base))


def scan_archetype_design_surprise(rows: list[tuple], week_of: str, top_n: int = 5) -> list[Insight]:
    """Archetypes whose observed aspirant rate diverges sharply from the
    rate their design implies. Both directions are interesting:
      - underperformers: the archetype is being failed by something
        (data starvation, design mis-spec, behavior layer gap)
      - overperformers: the archetype design under-predicted them
        (the substrate is generating more skill than spec'd)

    surprise_score = abs(observed - expected) clamped to [0, 1].
    """
    by_arch: dict[str, list] = {}
    for _uid, arch, mu, phi, n in rows:
        if not arch or mu is None or phi is None:
            continue
        by_arch.setdefault(arch, []).append((float(mu), float(phi), int(n)))

    results: list[tuple] = []
    for arch_slug, users in by_arch.items():
        archetype = next((a for a in ARCHETYPES if a.slug == arch_slug), None)
        if archetype is None:
            continue
        if len(users) < 10:
            continue  # noise floor — small cohorts shouldn't surface
        aspirants = sum(1 for mu, phi, n in users if classify_gyaani(mu, phi, n) in ("aspirant", "locked"))
        observed = aspirants / len(users)
        expected = _expected_aspirant_rate(archetype)
        surprise = abs(observed - expected)
        results.append((surprise, arch_slug, observed, expected, len(users)))

    results.sort(key=lambda r: -r[0])
    out: list[Insight] = []
    for surprise, arch_slug, observed, expected, n_users in results[:top_n]:
        direction = "outperforming" if observed > expected else "underperforming"
        delta_pp = (observed - expected) * 100
        out.append(Insight(
            kind="archetype_design_surprise",
            subject=arch_slug,
            observed=float(observed),
            expected=float(expected),
            surprise_score=float(min(1.0, surprise)),
            summary=(
                f"{arch_slug} {direction} archetype design: observed aspirant "
                f"rate {observed*100:.1f}% vs expected {expected*100:.1f}% "
                f"({delta_pp:+.1f}pp gap, n={n_users})."
            ),
            suggested_experiment=(
                f"Investigate the {direction} signal: "
                f"{'audit which behavior layers gate ' + arch_slug + ' from graduating' if direction == 'underperforming' else 'audit whether the archetype true_skill distribution is mis-spec''d high'}; "
                f"propose a calibration patch and measure the aspirant rate next "
                f"week."
            ),
            breakdown=dict(archetype=arch_slug, n_users=n_users, observed=observed,
                           expected=expected, delta_pp=delta_pp, direction=direction),
        ))
    return out


# ---------------------------------------------------------------------------
# Scanner 3: funnel gate clog
# ---------------------------------------------------------------------------


def scan_funnel_gate_clog(_rows: list[tuple], week_of: str, top_n: int = 3) -> list[Insight]:
    """For each funnel gate, the largest stuck-segment cohort. Surfaces
    where intervention has the most leverage.

    surprise_score = stuck_count / signed_up_count (so a gate with 500
    stuck users in a 1700 cohort scores 0.29).
    """
    # Lazy import — funnel_stages opens its own DB connection; keep
    # the scanner's read pattern uncoupled from _load_population.
    from metrics.definitions import funnel_stages

    f = funnel_stages(week_of=week_of)
    breakdowns = f.breakdowns
    signed = breakdowns["stages"][0]["n"]
    if signed == 0:
        return []

    out: list[Insight] = []
    gate_meta = [
        ("after_signup", "signup -> first call",
         "trigger first-call onboarding push targeting "),
        ("after_first_call", "first call -> 3 resolved",
         "send second-call prompt to "),
        ("after_three_resolved", "3 resolved -> Gyaani aspirant",
         "deploy mu-building practice prompts to "),
    ]
    for gate_key, gate_label, exp_prefix in gate_meta:
        gate = breakdowns["drop_off"][gate_key]
        if gate["n"] == 0 or not gate["segment_mix"]:
            continue
        top_seg, top_n_seg = next(iter(gate["segment_mix"].items()))
        score = min(1.0, gate["n"] / signed)
        out.append(Insight(
            kind="funnel_gate_clog",
            subject=gate_key,
            observed=float(gate["n"]),
            expected=0.0,
            surprise_score=float(score),
            summary=(
                f"Gate '{gate_label}' has {gate['n']} stuck users; "
                f"top segment in sample: {top_seg} ({top_n_seg})."
            ),
            suggested_experiment=(
                f"{exp_prefix}{top_seg} segment; measure progression "
                f"to next stage within 7 days. Sample n={gate['n']}."
            ),
            breakdown=dict(gate=gate_key, stuck_n=gate["n"], top_segment=top_seg,
                           segment_mix=gate["segment_mix"]),
        ))
    out.sort(key=lambda i: -i.surprise_score)
    return out[:top_n]


# ---------------------------------------------------------------------------
# Scanner 4: axis outliers — per-archetype mu deviations from population
# ---------------------------------------------------------------------------


def scan_axis_outliers(rows: list[tuple], week_of: str, top_n: int = 5) -> list[Insight]:
    """Archetypes whose population-mean mu deviates strongly from the
    overall population mean. Captures archetype design drift — if
    "ghost_risk_junior" lands with mean mu well above 1500, the
    archetype isn't actually risky in the substrate.

    surprise_score = abs(z-score) normalised to [0, 1] by capping at 3sigma.
    """
    all_mus = [float(mu) for _uid, _arch, mu, _phi, _n in rows if mu is not None]
    if len(all_mus) < 50:
        return []
    pop_mean = statistics.fmean(all_mus)
    pop_std = statistics.pstdev(all_mus) or 1.0

    by_arch: dict[str, list[float]] = {}
    for _uid, arch, mu, _phi, _n in rows:
        if not arch or mu is None:
            continue
        by_arch.setdefault(arch, []).append(float(mu))

    candidates: list[tuple] = []
    for arch_slug, mus in by_arch.items():
        if len(mus) < 15:
            continue
        arch_mean = statistics.fmean(mus)
        z = (arch_mean - pop_mean) / pop_std
        # Cohort std-error of mean
        cohort_sem = pop_std / (len(mus) ** 0.5)
        z_of_mean = (arch_mean - pop_mean) / cohort_sem
        candidates.append((abs(z), arch_slug, arch_mean, z, len(mus), z_of_mean))

    candidates.sort(key=lambda r: -r[0])
    out: list[Insight] = []
    for abs_z, arch_slug, arch_mean, raw_z, n_users, z_of_mean in candidates[:top_n]:
        if abs_z < 0.15:  # not worth surfacing
            continue
        direction = "above" if raw_z > 0 else "below"
        out.append(Insight(
            kind="axis_outlier_mu",
            subject=arch_slug,
            observed=float(arch_mean),
            expected=float(pop_mean),
            surprise_score=float(min(1.0, abs_z / 3.0)),
            summary=(
                f"{arch_slug} mean mu {arch_mean:.0f} sits {direction} "
                f"population mean ({pop_mean:.0f}); z={raw_z:+.2f}, "
                f"z_of_mean={z_of_mean:+.2f}, n={n_users}."
            ),
            suggested_experiment=(
                f"Check whether {arch_slug}'s true_skill distribution in "
                f"sim/archetypes.py matches the observed mu position; "
                f"if mismatched, re-tune true_skill_mean and re-run."
            ),
            breakdown=dict(archetype=arch_slug, arch_mean=arch_mean,
                           pop_mean=pop_mean, z=raw_z, z_of_mean=z_of_mean,
                           n_users=n_users),
        ))
    return out


# ---------------------------------------------------------------------------
# Dispatch table + top-level driver
# ---------------------------------------------------------------------------


_SCANNERS: dict[str, Callable[[list[tuple], str], list[Insight]]] = {
    "near_miss_aspirant": scan_near_miss_aspirants,
    "archetype_design_surprise": scan_archetype_design_surprise,
    "funnel_gate_clog": scan_funnel_gate_clog,
    "axis_outlier_mu": scan_axis_outliers,
}


def generate_insights(week_of: str = "2024-W01", top_n_per_scanner: int = 5) -> list[Insight]:
    """Run every registered scanner over the W01 substrate and return
    the merged ranked list (by surprise_score desc).

    Callers that want a single growth-hack hypothesis take the first
    Insight; callers that want the full picture iterate. The metric
    wrapper in metrics/definitions.py packages this as a MetricResult.
    """
    rows = _load_population(week_of)
    all_insights: list[Insight] = []
    for name, scanner in _SCANNERS.items():
        try:
            insights = scanner(rows, week_of)
        except Exception as e:
            # Scanners should be defensive — log and continue rather
            # than fail the whole sweep on one bad scanner.
            insights = [Insight(
                kind=name,
                subject="(scanner_error)",
                observed=0.0,
                expected=0.0,
                surprise_score=0.0,
                summary=f"scanner {name} raised: {type(e).__name__}: {e}",
                suggested_experiment="fix the scanner and rerun.",
                breakdown=dict(error=str(e)),
            )]
        all_insights.extend(insights)
    all_insights.sort(key=lambda i: -i.surprise_score)
    return all_insights
