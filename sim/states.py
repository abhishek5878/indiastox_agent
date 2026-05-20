"""Eight internal state vectors per agent, plus pure update rules.

The current sim treats users as parametric — a single `true_skill` scalar
plus 14 behavior layers reading shared world state. That works for
population metrics but cannot answer the questions the strategy meeting
surfaced (activation moments, drop-off typologies, recovery arcs, silent-
failure trajectories). Those need agents whose internal state *evolves
event-by-event*.

This module defines:

  - 8 frozen state-vector dataclasses (belief, affective, social,
    identity, goal, time_budget, knowledge, trust);
  - One bundle dataclass `UserState`;
  - A `Event` discriminated union for the things that drive updates;
  - Pure update rules `update_X(state_in, event, archetype) -> state_out`
    that return a new state without mutating the input.

Each state carries `STATE_VERSION` so any modeled number written downstream
honors the substrate invariant ("modeled numbers carry the model version
that produced them").

Update math is intentionally simple where it can be — the goal of P0.2 is
to make the design surface real, not to ship the final calibration. P0.3
behavior layers will compose these update rules with the sim tick loop.
The sim's canonical Glicko-2 lives in metrics/skill.py and is the platform-
authoritative skill measure; `BeliefState` here is the *user's perceived*
skill, which can and should diverge — that gap is the miscalibration the
meeting is trying to expose.

Conventions:
  - Frozen dataclasses everywhere. Updates return new instances.
  - Mood vector sums to 1.0 (it's a probability distribution).
  - Trust ∈ [0, 1]; floor and ceiling are enforced.
  - Belief mu uses the same convention as `true_skill` (centered ~0).
  - Knowledge freshness ∈ [0, 1] per ticker; 0 = stale, 1 = just-refreshed.
  - Every update rule is total: undefined event kinds are a no-op,
    not an error. This keeps the dispatcher composable.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Mapping, Optional, Tuple, Union

from sim.archetypes import (
    ALL_SECTORS,
    GOALS,
    Archetype,
    archetype_by_slug,
    archetype_for_persona,
)

STATE_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Events — discriminated union driving state updates.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CallMadeEvent:
    user_id: str
    ticker: str
    sector: str
    direction: str
    stars: int
    sim_now: datetime
    kind: str = "call_made"


@dataclass(frozen=True)
class OutcomeResolvedEvent:
    user_id: str
    ticker: str
    sector: str
    outcome: str
    stars: int
    sim_now: datetime
    kind: str = "outcome_resolved"


@dataclass(frozen=True)
class PlatformRecEvent:
    user_id: str
    rec_type: str
    was_acted_on: bool
    was_helpful: bool
    sim_now: datetime
    kind: str = "platform_rec"


@dataclass(frozen=True)
class FollowEdgeEvent:
    user_id: str
    other_user_id: str
    direction: str
    sim_now: datetime
    kind: str = "follow_edge"


@dataclass(frozen=True)
class TimeTickEvent:
    user_id: str
    sim_now: datetime
    kind: str = "time_tick"


Event = Union[
    CallMadeEvent,
    OutcomeResolvedEvent,
    PlatformRecEvent,
    FollowEdgeEvent,
    TimeTickEvent,
]


# ---------------------------------------------------------------------------
# 8 state vectors.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BeliefState:
    """Per-sector belief about own skill. May be miscalibrated vs. true_skill.

    `sector_beliefs[s] = (mu_belief, phi_belief)`. The gap between mu_belief
    and the user's true_skill is the load-bearing thing P0.2 captures — it
    drives over- and under-confidence in star ratings and is what the meeting
    means by "users self-handicap into their known domain."
    """

    sector_beliefs: Tuple[Tuple[str, float, float], ...] = ()
    version: str = STATE_VERSION


@dataclass(frozen=True)
class AffectiveState:
    """4-component mood probability vector. Sums to 1.0.

    `tilt` rises after losses and drives revenge trading. `euphoria` rises
    after wins and drives star inflation. `depression` rises on sustained
    loss arcs and drives ghosting. `neutral` is the resting state. Mood
    decays toward `neutral` on time ticks where no outcome occurred.
    """

    tilt: float = 0.05
    euphoria: float = 0.05
    depression: float = 0.05
    neutral: float = 0.85
    last_outcome_kind: str = "none"
    version: str = STATE_VERSION

    def __post_init__(self) -> None:
        total = self.tilt + self.euphoria + self.depression + self.neutral
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"AffectiveState components sum to {total}, expected 1.0")


@dataclass(frozen=True)
class SocialState:
    """Follow/copy network position.

    `following` is the set of user_ids this user has chosen to copy.
    `follower_count` is the cached cardinality of the inbound edge set;
    storing the count rather than the set keeps state size bounded for the
    long Pareto tail of alpha-generator followers.
    """

    following: Tuple[str, ...] = ()
    follower_count: int = 0
    in_groups: Tuple[str, ...] = ()
    version: str = STATE_VERSION


@dataclass(frozen=True)
class IdentityState:
    """Self-narrative — archetype + optional sectoral specialization."""

    archetype_slug: str = ""
    sectoral_identity: str = "broad"
    version: str = STATE_VERSION


@dataclass(frozen=True)
class GoalState:
    """Primary motivation. Mostly static; can shift on badge achievement."""

    primary_goal: str = "entertainment"
    secondary_goal: str = "learning"
    version: str = STATE_VERSION


@dataclass(frozen=True)
class TimeBudgetState:
    """Daily attention minutes + active hours pattern."""

    daily_minutes_remaining: float = 30.0
    minutes_used_today: float = 0.0
    active_hours: Tuple[int, ...] = (10, 11, 14, 15, 21)
    last_tick_date: str = ""
    version: str = STATE_VERSION


@dataclass(frozen=True)
class KnowledgeState:
    """Per-ticker freshness ∈ [0, 1]. Decays daily; refreshed on touch."""

    ticker_freshness: Tuple[Tuple[str, float], ...] = ()
    last_decay_date: str = ""
    version: str = STATE_VERSION


@dataclass(frozen=True)
class TrustState:
    """Platform trust ∈ [0, 1]. Below 0.3 the user disengages."""

    trust: float = 0.7
    bad_recs_received: int = 0
    good_recs_received: int = 0
    version: str = STATE_VERSION


@dataclass(frozen=True)
class UserState:
    """Bundle of all 8 state vectors for one user.

    Designed so update rules can be applied to one slice at a time without
    rebuilding the whole bundle: e.g. `replace(us, trust=update_trust(...))`.
    """

    persona_id: str
    archetype_slug: str
    belief: BeliefState = field(default_factory=BeliefState)
    affective: AffectiveState = field(default_factory=AffectiveState)
    social: SocialState = field(default_factory=SocialState)
    identity: IdentityState = field(default_factory=IdentityState)
    goal: GoalState = field(default_factory=GoalState)
    time_budget: TimeBudgetState = field(default_factory=TimeBudgetState)
    knowledge: KnowledgeState = field(default_factory=KnowledgeState)
    trust: TrustState = field(default_factory=TrustState)
    version: str = STATE_VERSION


# ---------------------------------------------------------------------------
# Factories — init from archetype.
# ---------------------------------------------------------------------------


def init_belief_state(arch: Archetype) -> BeliefState:
    """Initialize per-sector belief seeded by archetype calibration.

    A perfectly calibrated archetype (calibration=1.0) starts with mu_belief
    equal to its true_skill_mean across all sectors. A randomly miscalibrated
    archetype (calibration=0.0) starts with mu_belief = 0 (no prior). Phi
    starts high (350) reflecting initial uncertainty, matching Glicko-2's
    default for a new player.
    """
    cal = arch.initial_belief_calibration
    initial_mu = cal * arch.true_skill_mean
    initial_phi = 350.0
    return BeliefState(
        sector_beliefs=tuple((s, initial_mu, initial_phi) for s in ALL_SECTORS)
    )


def init_affective_state(arch: Archetype) -> AffectiveState:
    """Default mood vector. All archetypes start in mostly-neutral mood;
    `affective_volatility` only matters once outcomes arrive."""
    return AffectiveState()


def init_social_state(arch: Archetype) -> SocialState:
    """Empty follow set at t=0. Edges form via P0.4 behavior layers."""
    return SocialState()


def init_identity_state(arch: Archetype) -> IdentityState:
    """Identity narrows over time. At t=0, sectoral_identity = single-sector
    archetypes inherit their sector; broad archetypes start as 'broad'."""
    sec_id = arch.sector_affinity[0] if len(arch.sector_affinity) == 1 else "broad"
    return IdentityState(archetype_slug=arch.slug, sectoral_identity=sec_id)


def init_goal_state(arch: Archetype) -> GoalState:
    secondary = "learning" if arch.primary_goal != "learning" else "social"
    return GoalState(primary_goal=arch.primary_goal, secondary_goal=secondary)


def init_time_budget_state(arch: Archetype, sim_now: datetime) -> TimeBudgetState:
    return TimeBudgetState(
        daily_minutes_remaining=arch.daily_time_budget_minutes_mean,
        minutes_used_today=0.0,
        active_hours=arch.active_hours,
        last_tick_date=sim_now.strftime("%Y-%m-%d"),
    )


def init_knowledge_state(arch: Archetype, sim_now: datetime) -> KnowledgeState:
    """Empty ticker_freshness at t=0 — knowledge accrues via events.
    Veterans-returning carry stale knowledge tags (handled by cohort logic
    in P0.5)."""
    return KnowledgeState(
        ticker_freshness=(),
        last_decay_date=sim_now.strftime("%Y-%m-%d"),
    )


def init_trust_state(arch: Archetype) -> TrustState:
    return TrustState(trust=arch.initial_trust)


def init_user_state(persona_id: str, sim_now: datetime) -> UserState:
    """Build a complete UserState from a persona_id at sim t=0.

    The archetype assignment is hash-deterministic; every state field is
    seeded from the archetype's traits. Call this once at persona creation;
    thereafter use the update_* functions to evolve state per event.
    """
    arch = archetype_for_persona(persona_id)
    return UserState(
        persona_id=persona_id,
        archetype_slug=arch.slug,
        belief=init_belief_state(arch),
        affective=init_affective_state(arch),
        social=init_social_state(arch),
        identity=init_identity_state(arch),
        goal=init_goal_state(arch),
        time_budget=init_time_budget_state(arch, sim_now),
        knowledge=init_knowledge_state(arch, sim_now),
        trust=init_trust_state(arch),
    )


# ---------------------------------------------------------------------------
# Update rules — pure functions, one per state vector.
# Each is a no-op on unrelated event kinds; this keeps the dispatcher simple.
# ---------------------------------------------------------------------------


def update_belief(
    state: BeliefState, event: Event, arch: Archetype
) -> BeliefState:
    """Outcome-driven Bayesian belief update on the affected sector.

    A win signals +1, a loss signals -1. Belief mu moves toward the signal
    at archetype-specific learning rate. Phi shrinks slowly toward a floor
    (50) as more sector-specific observations land — modeling Glicko-2's
    phi behavior but at a per-user-perceived granularity that may differ
    from the platform's measured value.
    """
    if not isinstance(event, OutcomeResolvedEvent):
        return state

    sector = event.sector
    signal = 1.0 if event.outcome == "WIN" else -1.0
    lr = arch.learning_curve_rate

    new_beliefs = []
    found = False
    for sec, mu, phi in state.sector_beliefs:
        if sec == sector:
            new_mu = mu + lr * (signal - mu)
            new_phi = max(50.0, phi * (1.0 - lr * 0.5))
            new_beliefs.append((sec, new_mu, new_phi))
            found = True
        else:
            new_beliefs.append((sec, mu, phi))
    if not found:
        new_beliefs.append((sector, lr * signal, 350.0 * (1.0 - lr * 0.5)))

    return replace(state, sector_beliefs=tuple(new_beliefs))


def update_affective(
    state: AffectiveState, event: Event, arch: Archetype
) -> AffectiveState:
    """Mood transition on outcomes; decay-toward-neutral on time ticks.

    Outcome handling: win → euphoria; loss → tilt + depression. The shift
    magnitude is gated by archetype `affective_volatility` so stoic archetypes
    barely move and tilt-prone archetypes swing hard. Stars-on-loss
    additionally amplifies tilt (a 5★ loss hurts more than a 1★ loss).
    """
    vol = arch.affective_volatility

    if isinstance(event, OutcomeResolvedEvent):
        if event.outcome == "WIN":
            star_factor = 1.0 + (event.stars - 1) * 0.1
            shift = vol * 0.3 * star_factor
            new = _shift_mood(state, target="euphoria", shift=shift)
            return replace(new, last_outcome_kind="win")
        else:
            star_factor = 1.0 + (event.stars - 1) * 0.15
            shift = vol * 0.35 * star_factor
            new = _shift_mood(state, target="tilt", shift=shift * 0.7)
            new = _shift_mood(new, target="depression", shift=shift * 0.3)
            return replace(new, last_outcome_kind="loss")

    if isinstance(event, TimeTickEvent):
        decay = 0.1
        new_tilt = state.tilt * (1 - decay)
        new_euphoria = state.euphoria * (1 - decay)
        new_depression = state.depression * (1 - decay)
        absorbed = (state.tilt + state.euphoria + state.depression) * decay
        new_neutral = state.neutral + absorbed
        return AffectiveState(
            tilt=new_tilt,
            euphoria=new_euphoria,
            depression=new_depression,
            neutral=new_neutral,
            last_outcome_kind=state.last_outcome_kind,
        )

    return state


def _shift_mood(state: AffectiveState, target: str, shift: float) -> AffectiveState:
    """Move `shift` probability mass into `target`, drawn proportionally
    from the other three components. Renormalizes to sum exactly 1.0."""
    shift = max(0.0, min(0.95, shift))
    fields = {
        "tilt": state.tilt,
        "euphoria": state.euphoria,
        "depression": state.depression,
        "neutral": state.neutral,
    }
    pulled_from = {k: v for k, v in fields.items() if k != target}
    pulled_total = sum(pulled_from.values())
    if pulled_total <= 0:
        return state
    actual_shift = min(shift, pulled_total * 0.9)
    new_target = fields[target] + actual_shift
    scale = (pulled_total - actual_shift) / pulled_total
    new_fields = {k: (v * scale if k != target else new_target) for k, v in fields.items()}
    total = sum(new_fields.values())
    new_fields = {k: v / total for k, v in new_fields.items()}
    return AffectiveState(
        tilt=new_fields["tilt"],
        euphoria=new_fields["euphoria"],
        depression=new_fields["depression"],
        neutral=new_fields["neutral"],
        last_outcome_kind=state.last_outcome_kind,
    )


def update_social(
    state: SocialState, event: Event, arch: Archetype
) -> SocialState:
    """Follow-edge formation / dissolution via FollowEdgeEvent.

    P0.4 will add group_formed events that update `in_groups`; for P0.2 we
    only handle follow/unfollow + cached follower_count updates.
    """
    if not isinstance(event, FollowEdgeEvent):
        return state

    if event.direction == "follow":
        if event.other_user_id in state.following:
            return state
        return replace(state, following=state.following + (event.other_user_id,))
    if event.direction == "unfollow":
        new_following = tuple(u for u in state.following if u != event.other_user_id)
        return replace(state, following=new_following)
    if event.direction == "follower_gained":
        return replace(state, follower_count=state.follower_count + 1)
    if event.direction == "follower_lost":
        return replace(state, follower_count=max(0, state.follower_count - 1))
    return state


def update_identity(
    state: IdentityState, event: Event, arch: Archetype, call_count_by_sector: Optional[Mapping[str, int]] = None
) -> IdentityState:
    """Sectoral identity narrows after sustained single-sector activity.

    A broad-identity user who makes ≥10 calls in a single sector with that
    sector accounting for ≥70% of their total adopts the sectoral identity.
    Identity rarely *widens* — once narrowed it tends to stick (matches the
    Anchored Conservative archetype dynamic). identity_strength gates how
    strongly the narrowing fires.
    """
    if call_count_by_sector is None or state.sectoral_identity != "broad":
        return state

    total = sum(call_count_by_sector.values())
    if total < 10:
        return state

    dominant_sector = max(call_count_by_sector.items(), key=lambda kv: kv[1])
    dominant_share = dominant_sector[1] / total
    threshold = 0.7 - arch.identity_strength * 0.2
    if dominant_share >= threshold:
        return replace(state, sectoral_identity=dominant_sector[0])
    return state


def update_goal(
    state: GoalState, event: Event, arch: Archetype, gyaani_achieved: bool = False
) -> GoalState:
    """Goal can shift on badge achievement: badge-aspirants become
    influence-seekers once they cross the Gyaani threshold."""
    if gyaani_achieved and state.primary_goal == "badge":
        return replace(state, primary_goal="influence", secondary_goal="badge")
    return state


def update_time_budget(
    state: TimeBudgetState, event: Event, arch: Archetype
) -> TimeBudgetState:
    """Decrement remaining minutes on call events; refresh daily budget
    on date change observed in a TimeTickEvent.

    Minute cost per call is a constant 3 minutes — coarse but good enough
    for the substrate's "did this user run out of attention today" signal.
    """
    if isinstance(event, TimeTickEvent):
        new_date = event.sim_now.strftime("%Y-%m-%d")
        if new_date != state.last_tick_date:
            return TimeBudgetState(
                daily_minutes_remaining=arch.daily_time_budget_minutes_mean,
                minutes_used_today=0.0,
                active_hours=state.active_hours,
                last_tick_date=new_date,
            )
        return state

    if isinstance(event, CallMadeEvent):
        cost = 3.0
        return replace(
            state,
            daily_minutes_remaining=max(0.0, state.daily_minutes_remaining - cost),
            minutes_used_today=state.minutes_used_today + cost,
        )

    return state


def update_knowledge(
    state: KnowledgeState, event: Event, arch: Archetype
) -> KnowledgeState:
    """Ticker freshness jumps to 1.0 on touch (call_made or rec exposure);
    decays exponentially daily on TimeTickEvent.

    Decay half-life is archetype-specific via `knowledge_decay_days` — pharma
    doctors retain knowledge longer than ghost-risk juniors.
    """
    if isinstance(event, CallMadeEvent):
        existing = {t: f for t, f in state.ticker_freshness}
        existing[event.ticker] = 1.0
        return replace(state, ticker_freshness=tuple(sorted(existing.items())))

    if isinstance(event, TimeTickEvent):
        new_date = event.sim_now.strftime("%Y-%m-%d")
        if new_date == state.last_decay_date:
            return state
        try:
            old = datetime.strptime(state.last_decay_date, "%Y-%m-%d")
            cur = datetime.strptime(new_date, "%Y-%m-%d")
            days_elapsed = max(1, (cur - old).days)
        except ValueError:
            days_elapsed = 1
        half_life = max(0.5, arch.knowledge_decay_days)
        decay_factor = math.exp(-days_elapsed * math.log(2) / half_life)
        decayed = tuple(
            (t, f * decay_factor) for t, f in state.ticker_freshness if f * decay_factor > 0.01
        )
        return replace(state, ticker_freshness=decayed, last_decay_date=new_date)

    return state


def update_trust(
    state: TrustState, event: Event, arch: Archetype
) -> TrustState:
    """Platform trust update on rec exposure.

    `was_helpful=False` decrements trust by `trust_decay_rate`; helpful recs
    recover trust by half that rate (recovery is slower than decay — matches
    the meeting's "first impressions matter more" observation). Trust is
    clamped to [0, 1].
    """
    if not isinstance(event, PlatformRecEvent):
        return state

    if not event.was_helpful:
        new_trust = max(0.0, state.trust - arch.trust_decay_rate)
        return replace(state, trust=new_trust, bad_recs_received=state.bad_recs_received + 1)

    new_trust = min(1.0, state.trust + arch.trust_decay_rate * 0.5)
    return replace(state, trust=new_trust, good_recs_received=state.good_recs_received + 1)


# ---------------------------------------------------------------------------
# Composed dispatch — apply one event to a full UserState.
# ---------------------------------------------------------------------------


def apply_event(state: UserState, event: Event) -> UserState:
    """Apply an event to all relevant state vectors at once.

    Each per-state update is a no-op on unrelated events, so we can dispatch
    universally without an event-kind switch. The bundle is rebuilt with
    `replace()`, preserving identity-equality of unchanged sub-states (each
    update_* function returns the input unchanged when its event kind
    doesn't match).
    """
    arch = archetype_by_slug(state.archetype_slug)
    return UserState(
        persona_id=state.persona_id,
        archetype_slug=state.archetype_slug,
        belief=update_belief(state.belief, event, arch),
        affective=update_affective(state.affective, event, arch),
        social=update_social(state.social, event, arch),
        identity=state.identity,
        goal=state.goal,
        time_budget=update_time_budget(state.time_budget, event, arch),
        knowledge=update_knowledge(state.knowledge, event, arch),
        trust=update_trust(state.trust, event, arch),
    )
