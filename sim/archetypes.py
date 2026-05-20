"""Persona archetypes for the IndiaStox living-world sim.

Today the sim treats each persona as a single `true_skill ~ N(0, 1)` scalar
plus an acquisition source. That works for population-level metrics but not
for the insight questions the strategy meeting surfaced (activation moments,
drop-off typologies, recovery arcs, silent-failure trajectories). Those
questions need agents whose behavior is *shaped by an archetype* — a
template that biases their initial state vectors, personality traits, and
update rules.

This module defines 20 archetype templates and a deterministic assignment
function (`archetype_for_persona`) that maps a `persona_id` to exactly one
archetype reproducibly across runs. P0.1 ships the templates + assignment
only; P0.2 will consume these to drive the 8 internal state vectors, and
P0.3 will use the per-archetype traits to modify the behavior layers.

Population weights sum to 1.0 and are documented as a falsifiable claim —
once real Day-1 user data arrives, the team is expected to re-weight.

This file does NOT couple to generate.py's RNG. Assignment is by stable
hash of persona_id, so any persona (synthetic or real) can be classified
without needing to know its position in a generation sequence.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Tuple

ARCHETYPE_VERSION = "1.0.0"

# Goals an archetype is primarily motivated by. Drives which signals matter
# to the user during behavior-layer updates.
GOALS = ("badge", "influence", "learning", "entertainment", "income", "social")

# Live sectors in the warehouse (per sim/world.py SECTOR_OF) plus two
# aspirational sectors the meeting called out by name (pharma_doctor archetype
# requires "pharma"; sectoral_rotator references "auto"). If tickers for these
# do not exist yet, the behavior-layer fallback in P0.3 will widen the call
# pool — the archetype's preference is still recorded for downstream insight
# analysis.
LIVE_SECTORS = ("energy", "IT", "banking", "FMCG")
ASPIRATIONAL_SECTORS = ("pharma", "auto")
ALL_SECTORS = LIVE_SECTORS + ASPIRATIONAL_SECTORS


@dataclass(frozen=True)
class Archetype:
    """A persona template biasing initial state and trait values.

    Fields fall into three groups:
      - Identity: how the archetype is named and weighted in the population.
      - Personality traits: constants per user that modify update rules in
        the behavior layers (set once at sampling, never updated).
      - Initial-state biases: starting values for the 8 internal state
        vectors that P0.2 will define and evolve.

    All numeric ranges are documented inline only where the WHY is
    non-obvious; the field names carry the rest.
    """

    name: str
    slug: str
    weight: float
    description: str

    # ----- True-skill distribution (compatible with existing schema) -----
    # The sim today samples a single true_skill ~ N(0, 1) per persona; here
    # we keep the same scalar but let archetypes shift its mean/spread.
    true_skill_mean: float
    true_skill_std: float

    # ----- Personality traits (constant per user) -----
    affective_volatility: float          # 0..1; mood reactivity to outcomes
    social_susceptibility: float         # 0..1; copy-call probability per followed user
    identity_strength: float             # 0..1; identity bias on next action
    learning_curve_rate: float           # 0..1; speed belief_mu → true_skill
    trust_decay_rate: float              # per-bad-platform-rec trust decrement
    knowledge_decay_days: float          # per-ticker freshness half-life (days)
    star_inflation_under_tilt: float     # multiplier on star confidence when tilted

    primary_goal: str                    # one of GOALS

    # ----- Activity pattern -----
    daily_time_budget_minutes_mean: float
    daily_time_budget_minutes_std: float
    active_hours: Tuple[int, ...]        # hours-of-day where activity peaks
    weekday_only: bool = False
    weekend_only: bool = False

    # ----- Sector preference -----
    sector_affinity: Tuple[str, ...] = ()   # empty = broad coverage

    # ----- Initial-state biases (consumed by P0.2 state-vector init) -----
    initial_belief_calibration: float = 0.5  # 0=random; 1=perfect alignment with true_skill at t=0
    initial_trust: float = 0.7
    initial_follower_pareto_alpha: float = 2.0  # higher alpha => fewer followers; alpha < 1 => power-law tail

    # ----- Cohort tags (special-case archetypes) -----
    cohort_tag: str = ""                  # e.g. "returning_veteran" — picked up by P0.5 multi-week generator


def _g(goal: str) -> str:
    assert goal in GOALS, f"goal {goal} not in {GOALS}"
    return goal


# ----------------------------------------------------------------------
# The 20 archetype templates.
#
# Weights sum to exactly 1.00. They encode a hypothesis about the
# IndiaStox active base, NOT a measurement. The team is expected to
# re-weight once real Day-1 signups land. See task_plan.md adversarial
# review #3 for the falsifiability claim.
# ----------------------------------------------------------------------

ARCHETYPES: Tuple[Archetype, ...] = (
    Archetype(
        name="Aspirant College Student",
        slug="aspirant_college_student",
        weight=0.10,
        description="High learning rate, bursty time-budget around classes, "
                    "high social susceptibility, identity = future trader.",
        true_skill_mean=-0.2,
        true_skill_std=0.9,
        affective_volatility=0.6,
        social_susceptibility=0.75,
        identity_strength=0.4,
        learning_curve_rate=0.45,
        trust_decay_rate=0.05,
        knowledge_decay_days=5.0,
        star_inflation_under_tilt=1.3,
        primary_goal=_g("badge"),
        daily_time_budget_minutes_mean=35.0,
        daily_time_budget_minutes_std=20.0,
        active_hours=(11, 12, 18, 19, 20, 21),
        initial_belief_calibration=0.3,
    ),
    Archetype(
        name="IT Sector Specialist",
        slug="it_sector_specialist",
        weight=0.08,
        description="Narrow IT/Tech affinity, high knowledge in sector, "
                    "moderate true skill often overconfidence-rated.",
        true_skill_mean=0.3,
        true_skill_std=0.7,
        affective_volatility=0.3,
        social_susceptibility=0.25,
        identity_strength=0.8,
        learning_curve_rate=0.2,
        trust_decay_rate=0.08,
        knowledge_decay_days=10.0,
        star_inflation_under_tilt=1.1,
        primary_goal=_g("income"),
        daily_time_budget_minutes_mean=25.0,
        daily_time_budget_minutes_std=10.0,
        active_hours=(9, 10, 14, 15, 16, 22),
        sector_affinity=("IT",),
        initial_belief_calibration=0.7,
    ),
    Archetype(
        name="Weekend Casual",
        slug="weekend_casual",
        weight=0.06,
        description="Active only Sat/Sun, low affective volatility, "
                    "treats IndiaStox as entertainment.",
        true_skill_mean=0.0,
        true_skill_std=0.6,
        affective_volatility=0.15,
        social_susceptibility=0.4,
        identity_strength=0.2,
        learning_curve_rate=0.1,
        trust_decay_rate=0.03,
        knowledge_decay_days=14.0,
        star_inflation_under_tilt=1.05,
        primary_goal=_g("entertainment"),
        daily_time_budget_minutes_mean=45.0,
        daily_time_budget_minutes_std=25.0,
        active_hours=(10, 11, 12, 19, 20, 21, 22),
        weekend_only=True,
    ),
    Archetype(
        name="FOMO Cascader",
        slug="fomo_cascader",
        weight=0.07,
        description="High social susceptibility, low patience, copies "
                    "trending tiles, goal = social.",
        true_skill_mean=-0.1,
        true_skill_std=0.8,
        affective_volatility=0.7,
        social_susceptibility=0.9,
        identity_strength=0.3,
        learning_curve_rate=0.15,
        trust_decay_rate=0.06,
        knowledge_decay_days=3.0,
        star_inflation_under_tilt=1.4,
        primary_goal=_g("social"),
        daily_time_budget_minutes_mean=40.0,
        daily_time_budget_minutes_std=15.0,
        active_hours=(10, 11, 13, 14, 15, 20, 21),
        initial_belief_calibration=0.25,
    ),
    Archetype(
        name="Pharma Domain Expert",
        slug="pharma_doctor",
        weight=0.03,
        description="Narrow Pharma/Healthcare, calibrated in-sector, "
                    "low weekday time-budget (clinical hours).",
        true_skill_mean=0.5,
        true_skill_std=0.5,
        affective_volatility=0.2,
        social_susceptibility=0.15,
        identity_strength=0.85,
        learning_curve_rate=0.15,
        trust_decay_rate=0.1,
        knowledge_decay_days=14.0,
        star_inflation_under_tilt=1.0,
        primary_goal=_g("income"),
        daily_time_budget_minutes_mean=18.0,
        daily_time_budget_minutes_std=8.0,
        active_hours=(8, 13, 21, 22),
        sector_affinity=("pharma",),
        initial_belief_calibration=0.85,
    ),
    Archetype(
        name="Tilt Trader",
        slug="tilt_trader",
        weight=0.05,
        description="High affective volatility; post-loss revenge "
                    "probability 3× baseline; star inflation under tilt.",
        true_skill_mean=-0.1,
        true_skill_std=1.0,
        affective_volatility=0.95,
        social_susceptibility=0.4,
        identity_strength=0.3,
        learning_curve_rate=0.1,
        trust_decay_rate=0.15,
        knowledge_decay_days=4.0,
        star_inflation_under_tilt=2.0,
        primary_goal=_g("income"),
        daily_time_budget_minutes_mean=55.0,
        daily_time_budget_minutes_std=30.0,
        active_hours=(9, 10, 14, 15, 16, 22, 23),
        initial_belief_calibration=0.4,
    ),
    Archetype(
        name="Recovery Streaker",
        slug="recovery_streaker",
        weight=0.05,
        description="Capable of 0/4 then 4/4 arcs (user's named case). "
                    "Moderate base rate, high streak variance, "
                    "comeback-narrative driven.",
        true_skill_mean=0.1,
        true_skill_std=1.2,
        affective_volatility=0.55,
        social_susceptibility=0.35,
        identity_strength=0.5,
        learning_curve_rate=0.35,
        trust_decay_rate=0.04,
        knowledge_decay_days=6.0,
        star_inflation_under_tilt=1.2,
        primary_goal=_g("badge"),
        daily_time_budget_minutes_mean=30.0,
        daily_time_budget_minutes_std=20.0,
        active_hours=(10, 11, 14, 15, 21),
    ),
    Archetype(
        name="Group Whisper Follower",
        slug="group_whisper_follower",
        weight=0.05,
        description="High in-group conformity, copies a specific 3-5 "
                    "person sub-network (WhatsApp-style).",
        true_skill_mean=-0.05,
        true_skill_std=0.7,
        affective_volatility=0.4,
        social_susceptibility=0.85,
        identity_strength=0.45,
        learning_curve_rate=0.2,
        trust_decay_rate=0.05,
        knowledge_decay_days=5.0,
        star_inflation_under_tilt=1.2,
        primary_goal=_g("social"),
        daily_time_budget_minutes_mean=28.0,
        daily_time_budget_minutes_std=12.0,
        active_hours=(9, 13, 14, 20, 21, 22),
        initial_follower_pareto_alpha=1.2,
    ),
    Archetype(
        name="Anchored Conservative",
        slug="anchored_conservative",
        weight=0.05,
        description="First call's sector becomes 80% of future calls; "
                    "low exploration, high consistency.",
        true_skill_mean=0.1,
        true_skill_std=0.6,
        affective_volatility=0.2,
        social_susceptibility=0.2,
        identity_strength=0.9,
        learning_curve_rate=0.12,
        trust_decay_rate=0.04,
        knowledge_decay_days=12.0,
        star_inflation_under_tilt=1.0,
        primary_goal=_g("learning"),
        daily_time_budget_minutes_mean=22.0,
        daily_time_budget_minutes_std=8.0,
        active_hours=(10, 11, 15, 20),
        initial_belief_calibration=0.5,
    ),
    Archetype(
        name="Diversifier Index Investor",
        slug="diversifier_index_investor",
        weight=0.04,
        description="Wide sector coverage, low conviction per call, "
                    "treats stars as low-info.",
        true_skill_mean=0.05,
        true_skill_std=0.4,
        affective_volatility=0.15,
        social_susceptibility=0.2,
        identity_strength=0.4,
        learning_curve_rate=0.18,
        trust_decay_rate=0.03,
        knowledge_decay_days=10.0,
        star_inflation_under_tilt=1.0,
        primary_goal=_g("learning"),
        daily_time_budget_minutes_mean=20.0,
        daily_time_budget_minutes_std=7.0,
        active_hours=(11, 12, 21, 22),
    ),
    Archetype(
        name="Alpha Generator",
        slug="alpha_generator",
        weight=0.03,
        description="Top 5% true mu, well-calibrated, high follower "
                    "count (Pareto top); goal = influence.",
        true_skill_mean=1.4,
        true_skill_std=0.4,
        affective_volatility=0.25,
        social_susceptibility=0.1,
        identity_strength=0.9,
        learning_curve_rate=0.3,
        trust_decay_rate=0.02,
        knowledge_decay_days=10.0,
        star_inflation_under_tilt=1.05,
        primary_goal=_g("influence"),
        daily_time_budget_minutes_mean=50.0,
        daily_time_budget_minutes_std=15.0,
        active_hours=(9, 10, 11, 14, 15, 16, 21, 22),
        initial_belief_calibration=0.9,
        initial_follower_pareto_alpha=0.7,
    ),
    Archetype(
        name="Ghost-Risk Junior",
        slug="ghost_risk_junior",
        weight=0.10,
        description="1-2 calls then disappears unless recovered. "
                    "The population P6 activation work is targeting.",
        true_skill_mean=-0.4,
        true_skill_std=1.0,
        affective_volatility=0.7,
        social_susceptibility=0.5,
        identity_strength=0.15,
        learning_curve_rate=0.1,
        trust_decay_rate=0.25,
        knowledge_decay_days=2.0,
        star_inflation_under_tilt=1.5,
        primary_goal=_g("entertainment"),
        daily_time_budget_minutes_mean=12.0,
        daily_time_budget_minutes_std=10.0,
        active_hours=(20, 21, 22),
        initial_belief_calibration=0.2,
        initial_trust=0.4,
    ),
    Archetype(
        name="Skeptic",
        slug="skeptic",
        weight=0.03,
        description="High trust-decay rate, abandons platform after "
                    "first wrong call from self or platform recs.",
        true_skill_mean=0.2,
        true_skill_std=0.7,
        affective_volatility=0.5,
        social_susceptibility=0.1,
        identity_strength=0.7,
        learning_curve_rate=0.2,
        trust_decay_rate=0.4,
        knowledge_decay_days=8.0,
        star_inflation_under_tilt=1.1,
        primary_goal=_g("learning"),
        daily_time_budget_minutes_mean=18.0,
        daily_time_budget_minutes_std=8.0,
        active_hours=(10, 11, 21),
        initial_trust=0.5,
    ),
    Archetype(
        name="Day Trader",
        slug="day_trader",
        weight=0.04,
        description="High frequency, NSE 9-11 + 14-16 time-of-day peaks; "
                    "income-oriented.",
        true_skill_mean=0.2,
        true_skill_std=0.9,
        affective_volatility=0.6,
        social_susceptibility=0.25,
        identity_strength=0.7,
        learning_curve_rate=0.25,
        trust_decay_rate=0.1,
        knowledge_decay_days=3.0,
        star_inflation_under_tilt=1.3,
        primary_goal=_g("income"),
        daily_time_budget_minutes_mean=90.0,
        daily_time_budget_minutes_std=30.0,
        active_hours=(9, 10, 11, 14, 15, 16),
        weekday_only=True,
        initial_belief_calibration=0.6,
    ),
    Archetype(
        name="Lurker Turned Caller",
        slug="lurker_turned_caller",
        weight=0.05,
        description="Long passive Week-1, then activates Week-2 after "
                    "watching others succeed; latent cascade-follower.",
        true_skill_mean=0.0,
        true_skill_std=0.8,
        affective_volatility=0.3,
        social_susceptibility=0.6,
        identity_strength=0.3,
        learning_curve_rate=0.25,
        trust_decay_rate=0.06,
        knowledge_decay_days=7.0,
        star_inflation_under_tilt=1.1,
        primary_goal=_g("learning"),
        daily_time_budget_minutes_mean=22.0,
        daily_time_budget_minutes_std=12.0,
        active_hours=(11, 20, 21, 22),
        cohort_tag="late_activator",
    ),
    Archetype(
        name="Influencer Aspirant",
        slug="influencer_aspirant",
        weight=0.03,
        description="Goal = followers; calls high-visibility tickers, "
                    "sometimes miscalibrated, prioritizes explanation text.",
        true_skill_mean=0.1,
        true_skill_std=0.7,
        affective_volatility=0.5,
        social_susceptibility=0.35,
        identity_strength=0.75,
        learning_curve_rate=0.2,
        trust_decay_rate=0.05,
        knowledge_decay_days=6.0,
        star_inflation_under_tilt=1.4,
        primary_goal=_g("influence"),
        daily_time_budget_minutes_mean=45.0,
        daily_time_budget_minutes_std=20.0,
        active_hours=(10, 11, 12, 19, 20, 21, 22),
        initial_follower_pareto_alpha=1.0,
    ),
    Archetype(
        name="Sectoral Rotator",
        slug="sectoral_rotator",
        weight=0.03,
        description="Narrow but rotates: Pharma → Banking → Auto across "
                    "weeks. Pattern-detector style.",
        true_skill_mean=0.3,
        true_skill_std=0.6,
        affective_volatility=0.3,
        social_susceptibility=0.2,
        identity_strength=0.75,
        learning_curve_rate=0.3,
        trust_decay_rate=0.04,
        knowledge_decay_days=8.0,
        star_inflation_under_tilt=1.1,
        primary_goal=_g("income"),
        daily_time_budget_minutes_mean=35.0,
        daily_time_budget_minutes_std=10.0,
        active_hours=(10, 11, 14, 15, 16, 21),
        sector_affinity=("pharma", "banking", "auto"),
        initial_belief_calibration=0.7,
    ),
    Archetype(
        name="Streak Breaker",
        slug="streak_breaker",
        weight=0.02,
        description="Paradoxical exit at peak; quits while ahead, "
                    "returns when peers do. Goal = exit at peak.",
        true_skill_mean=0.2,
        true_skill_std=0.8,
        affective_volatility=0.4,
        social_susceptibility=0.3,
        identity_strength=0.5,
        learning_curve_rate=0.2,
        trust_decay_rate=0.05,
        knowledge_decay_days=10.0,
        star_inflation_under_tilt=1.0,
        primary_goal=_g("badge"),
        daily_time_budget_minutes_mean=25.0,
        daily_time_budget_minutes_std=15.0,
        active_hours=(10, 11, 14, 21),
    ),
    Archetype(
        name="Newbie Cautious",
        slug="newbie_cautious",
        weight=0.05,
        description="First 4 weeks all 1-star calls; gradual star "
                    "upgrade as belief-state confidence builds.",
        true_skill_mean=-0.1,
        true_skill_std=0.6,
        affective_volatility=0.25,
        social_susceptibility=0.3,
        identity_strength=0.3,
        learning_curve_rate=0.4,
        trust_decay_rate=0.05,
        knowledge_decay_days=7.0,
        star_inflation_under_tilt=1.0,
        primary_goal=_g("learning"),
        daily_time_budget_minutes_mean=15.0,
        daily_time_budget_minutes_std=6.0,
        active_hours=(20, 21, 22),
        initial_belief_calibration=0.1,
    ),
    Archetype(
        name="Veteran Returning",
        slug="veteran_returning",
        weight=0.04,
        description="Was active in a synthetic-prior cohort, returning "
                    "with stale knowledge. Knowledge-state freshness = 0 at t=0.",
        true_skill_mean=0.4,
        true_skill_std=0.6,
        affective_volatility=0.3,
        social_susceptibility=0.2,
        identity_strength=0.7,
        learning_curve_rate=0.15,
        trust_decay_rate=0.08,
        knowledge_decay_days=15.0,
        star_inflation_under_tilt=1.0,
        primary_goal=_g("income"),
        daily_time_budget_minutes_mean=30.0,
        daily_time_budget_minutes_std=12.0,
        active_hours=(10, 11, 15, 21, 22),
        initial_belief_calibration=0.5,
        initial_trust=0.6,
        cohort_tag="returning_veteran",
    ),
)


# ----------------------------------------------------------------------
# Module-load invariants. Fail fast if archetype table drifts.
# ----------------------------------------------------------------------


def _validate_archetypes() -> None:
    """Module-load invariant check.

    Three things must hold for the rest of the substrate to behave:
      (1) weights sum to exactly 1.0 (within float epsilon);
      (2) slugs are unique (used as DB keys);
      (3) all goals + sectors reference allowed values.
    """
    total = sum(a.weight for a in ARCHETYPES)
    if abs(total - 1.0) > 1e-9:
        raise AssertionError(
            f"ARCHETYPES weights sum to {total}, expected 1.0. "
            "Re-balance archetype table."
        )

    slugs = [a.slug for a in ARCHETYPES]
    if len(slugs) != len(set(slugs)):
        dupes = {s for s in slugs if slugs.count(s) > 1}
        raise AssertionError(f"duplicate archetype slugs: {dupes}")

    for a in ARCHETYPES:
        if a.primary_goal not in GOALS:
            raise AssertionError(f"archetype {a.slug} has invalid goal {a.primary_goal}")
        for sec in a.sector_affinity:
            if sec not in ALL_SECTORS:
                raise AssertionError(
                    f"archetype {a.slug} sector_affinity {sec} not in {ALL_SECTORS}"
                )


_validate_archetypes()


# Precomputed cumulative weights for O(log n) lookup. Built once at import.
_CUMULATIVE_WEIGHTS: Tuple[float, ...] = tuple(
    sum(a.weight for a in ARCHETYPES[: i + 1]) for i in range(len(ARCHETYPES))
)


def archetype_for_persona(persona_id: str) -> Archetype:
    """Deterministic archetype assignment for a persona_id.

    The same persona_id always maps to the same archetype across runs,
    independent of generation order. Uses SHA-256 of `archetype:{persona_id}`
    so the assignment is decoupled from any other RNG sub-seed used in
    generate.py.

    Falls through to the last archetype on floating-point edge cases (when
    r is within epsilon of 1.0).
    """
    h = hashlib.sha256(f"archetype:{persona_id}".encode()).hexdigest()
    r = int(h[:8], 16) / 0x100000000
    for arch, cum in zip(ARCHETYPES, _CUMULATIVE_WEIGHTS):
        if r < cum:
            return arch
    return ARCHETYPES[-1]


def archetype_by_slug(slug: str) -> Archetype:
    """Lookup by slug. Raises KeyError if unknown."""
    for a in ARCHETYPES:
        if a.slug == slug:
            return a
    raise KeyError(f"unknown archetype slug: {slug}")


def sample_initial_true_skill(persona_id: str) -> float:
    """Return a true_skill scalar from the assigned archetype's distribution.

    This is a drop-in replacement for the current
    `rng_skill.gauss(0.0, 1.0)` line in generate.py. The mean and std are
    archetype-dependent, but the sampling itself is deterministic by
    persona_id so identical seeds reproduce identical skills. The hash-based
    Gaussian draw uses Box-Muller on two uniform samples derived from the
    persona_id; this avoids needing a shared random.Random instance whose
    output depends on call order.
    """
    import math

    arch = archetype_for_persona(persona_id)
    h1 = hashlib.sha256(f"skill1:{persona_id}".encode()).hexdigest()
    h2 = hashlib.sha256(f"skill2:{persona_id}".encode()).hexdigest()
    u1 = max(int(h1[:8], 16) / 0x100000000, 1e-12)
    u2 = int(h2[:8], 16) / 0x100000000
    z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
    return arch.true_skill_mean + arch.true_skill_std * z
