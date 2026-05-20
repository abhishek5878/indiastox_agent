"""Pytest tests for sim/states.py — P0.2 deliverable.

Coverage:
  - Initialization from archetype produces expected initial values
  - Update rules are pure (input state unchanged after call)
  - Update monotonicity per state vector (the right direction of motion
    for representative events)
  - Composed apply_event dispatches to all 8 states correctly
  - States are immutable (FrozenInstanceError on mutation)
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from sim.archetypes import archetype_by_slug, archetype_for_persona
from sim.states import (
    AffectiveState,
    BeliefState,
    CallMadeEvent,
    FollowEdgeEvent,
    GoalState,
    IdentityState,
    KnowledgeState,
    OutcomeResolvedEvent,
    PlatformRecEvent,
    SocialState,
    STATE_VERSION,
    TimeBudgetState,
    TimeTickEvent,
    TrustState,
    UserState,
    apply_event,
    init_belief_state,
    init_user_state,
    update_affective,
    update_belief,
    update_goal,
    update_identity,
    update_knowledge,
    update_social,
    update_time_budget,
    update_trust,
)

T0 = datetime(2024, 1, 1, 10, 0, 0)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


def test_init_user_state_basic() -> None:
    us = init_user_state("persona-00001", T0)
    assert us.persona_id == "persona-00001"
    assert us.archetype_slug == archetype_for_persona("persona-00001").slug
    assert us.version == STATE_VERSION
    assert isinstance(us.belief, BeliefState)
    assert isinstance(us.affective, AffectiveState)


def test_init_affective_state_is_neutral_dominant() -> None:
    us = init_user_state("persona-00001", T0)
    assert us.affective.neutral > 0.5
    total = us.affective.tilt + us.affective.euphoria + us.affective.depression + us.affective.neutral
    assert abs(total - 1.0) < 1e-9


def test_init_belief_state_calibrated_archetype() -> None:
    """A well-calibrated archetype (Alpha Generator, cal=0.9) should start
    with mu_belief close to its true_skill_mean (1.4)."""
    alpha = archetype_by_slug("alpha_generator")
    state = init_belief_state(alpha)
    for sec, mu, phi in state.sector_beliefs:
        assert abs(mu - alpha.initial_belief_calibration * alpha.true_skill_mean) < 1e-9
        assert phi == 350.0


def test_init_belief_state_uncalibrated_archetype() -> None:
    """Newbie Cautious (cal=0.1) should start near zero mu (no prior)."""
    newbie = archetype_by_slug("newbie_cautious")
    state = init_belief_state(newbie)
    for sec, mu, phi in state.sector_beliefs:
        assert abs(mu) < 0.05


def test_init_identity_state_narrow_archetype() -> None:
    """An archetype with single sector_affinity (IT specialist) starts with
    its sectoral identity set."""
    state = init_user_state("persona-test-id", T0)
    if state.archetype_slug == "it_sector_specialist":
        assert state.identity.sectoral_identity == "IT"


def test_init_identity_state_broad_archetype() -> None:
    """An archetype with empty sector_affinity (Weekend Casual) starts broad."""
    weekend = archetype_by_slug("weekend_casual")
    from sim.states import init_identity_state
    state = init_identity_state(weekend)
    assert state.sectoral_identity == "broad"


def test_init_time_budget_state() -> None:
    arch = archetype_by_slug("day_trader")
    from sim.states import init_time_budget_state
    state = init_time_budget_state(arch, T0)
    assert state.daily_minutes_remaining == arch.daily_time_budget_minutes_mean
    assert state.minutes_used_today == 0.0
    assert state.active_hours == arch.active_hours


# ---------------------------------------------------------------------------
# Purity — update rules don't mutate inputs
# ---------------------------------------------------------------------------


def test_update_belief_is_pure() -> None:
    arch = archetype_by_slug("recovery_streaker")
    state = init_belief_state(arch)
    event = OutcomeResolvedEvent(
        user_id="u1", ticker="TCS", sector="IT", outcome="WIN", stars=4, sim_now=T0
    )
    before = state
    after = update_belief(state, event, arch)
    assert before is state
    assert before.sector_beliefs == state.sector_beliefs
    assert after is not state


def test_update_affective_is_pure() -> None:
    arch = archetype_by_slug("tilt_trader")
    state = AffectiveState()
    event = OutcomeResolvedEvent(
        user_id="u1", ticker="TCS", sector="IT", outcome="LOSS", stars=5, sim_now=T0
    )
    after = update_affective(state, event, arch)
    assert state.tilt == 0.05
    assert after.tilt > state.tilt


# ---------------------------------------------------------------------------
# Belief monotonicity
# ---------------------------------------------------------------------------


def test_belief_increases_after_wins() -> None:
    """After repeated wins in a sector, mu_belief in that sector should
    rise. Non-target sectors should be unchanged."""
    arch = archetype_by_slug("aspirant_college_student")
    state = init_belief_state(arch)
    initial_mu_it = next(mu for sec, mu, phi in state.sector_beliefs if sec == "IT")
    initial_mu_banking = next(mu for sec, mu, phi in state.sector_beliefs if sec == "banking")

    for _ in range(10):
        event = OutcomeResolvedEvent(
            user_id="u1", ticker="TCS", sector="IT", outcome="WIN", stars=3, sim_now=T0
        )
        state = update_belief(state, event, arch)

    final_mu_it = next(mu for sec, mu, phi in state.sector_beliefs if sec == "IT")
    final_mu_banking = next(mu for sec, mu, phi in state.sector_beliefs if sec == "banking")
    assert final_mu_it > initial_mu_it
    assert final_mu_banking == initial_mu_banking


def test_belief_decreases_after_losses() -> None:
    arch = archetype_by_slug("aspirant_college_student")
    state = init_belief_state(arch)
    initial_mu_it = next(mu for sec, mu, phi in state.sector_beliefs if sec == "IT")

    for _ in range(10):
        event = OutcomeResolvedEvent(
            user_id="u1", ticker="TCS", sector="IT", outcome="LOSS", stars=3, sim_now=T0
        )
        state = update_belief(state, event, arch)

    final_mu_it = next(mu for sec, mu, phi in state.sector_beliefs if sec == "IT")
    assert final_mu_it < initial_mu_it


def test_belief_phi_shrinks_with_observations() -> None:
    arch = archetype_by_slug("aspirant_college_student")
    state = init_belief_state(arch)
    initial_phi = next(phi for sec, mu, phi in state.sector_beliefs if sec == "IT")
    for _ in range(20):
        event = OutcomeResolvedEvent(
            user_id="u1", ticker="TCS", sector="IT", outcome="WIN", stars=3, sim_now=T0
        )
        state = update_belief(state, event, arch)
    final_phi = next(phi for sec, mu, phi in state.sector_beliefs if sec == "IT")
    assert final_phi < initial_phi


# ---------------------------------------------------------------------------
# Affective monotonicity
# ---------------------------------------------------------------------------


def test_tilt_rises_after_loss() -> None:
    arch = archetype_by_slug("tilt_trader")
    state = AffectiveState()
    event = OutcomeResolvedEvent(
        user_id="u1", ticker="TCS", sector="IT", outcome="LOSS", stars=5, sim_now=T0
    )
    after = update_affective(state, event, arch)
    assert after.tilt > state.tilt
    assert after.last_outcome_kind == "loss"


def test_euphoria_rises_after_win() -> None:
    arch = archetype_by_slug("tilt_trader")
    state = AffectiveState()
    event = OutcomeResolvedEvent(
        user_id="u1", ticker="TCS", sector="IT", outcome="WIN", stars=5, sim_now=T0
    )
    after = update_affective(state, event, arch)
    assert after.euphoria > state.euphoria
    assert after.last_outcome_kind == "win"


def test_mood_sums_to_one_after_updates() -> None:
    arch = archetype_by_slug("tilt_trader")
    state = AffectiveState()
    for outcome in ("WIN", "LOSS", "LOSS", "WIN", "LOSS"):
        event = OutcomeResolvedEvent(
            user_id="u1", ticker="TCS", sector="IT", outcome=outcome, stars=3, sim_now=T0
        )
        state = update_affective(state, event, arch)
        total = state.tilt + state.euphoria + state.depression + state.neutral
        assert abs(total - 1.0) < 1e-6, f"mood drifted from 1.0: {total}"


def test_mood_decays_toward_neutral_on_time_ticks() -> None:
    arch = archetype_by_slug("tilt_trader")
    state = AffectiveState()
    loss_event = OutcomeResolvedEvent(
        user_id="u1", ticker="TCS", sector="IT", outcome="LOSS", stars=5, sim_now=T0
    )
    state = update_affective(state, loss_event, arch)
    tilt_after_loss = state.tilt

    for i in range(10):
        tick = TimeTickEvent(user_id="u1", sim_now=T0 + timedelta(hours=i + 1))
        state = update_affective(state, tick, arch)

    assert state.tilt < tilt_after_loss
    assert state.neutral > 0.5


def test_volatility_affects_mood_swing_magnitude() -> None:
    """Stoic archetype (low volatility) should shift mood less than tilt-prone
    archetype on the same event."""
    stoic = archetype_by_slug("diversifier_index_investor")
    volatile = archetype_by_slug("tilt_trader")
    event = OutcomeResolvedEvent(
        user_id="u1", ticker="TCS", sector="IT", outcome="LOSS", stars=5, sim_now=T0
    )
    stoic_after = update_affective(AffectiveState(), event, stoic)
    volatile_after = update_affective(AffectiveState(), event, volatile)
    assert volatile_after.tilt > stoic_after.tilt


# ---------------------------------------------------------------------------
# Social
# ---------------------------------------------------------------------------


def test_follow_edge_added() -> None:
    arch = archetype_by_slug("fomo_cascader")
    state = SocialState()
    event = FollowEdgeEvent(user_id="u1", other_user_id="u2", direction="follow", sim_now=T0)
    after = update_social(state, event, arch)
    assert "u2" in after.following
    assert "u2" not in state.following


def test_follow_edge_idempotent() -> None:
    arch = archetype_by_slug("fomo_cascader")
    state = SocialState(following=("u2",))
    event = FollowEdgeEvent(user_id="u1", other_user_id="u2", direction="follow", sim_now=T0)
    after = update_social(state, event, arch)
    assert after.following == ("u2",)


def test_unfollow() -> None:
    arch = archetype_by_slug("fomo_cascader")
    state = SocialState(following=("u2", "u3", "u4"))
    event = FollowEdgeEvent(user_id="u1", other_user_id="u3", direction="unfollow", sim_now=T0)
    after = update_social(state, event, arch)
    assert "u3" not in after.following
    assert set(after.following) == {"u2", "u4"}


# ---------------------------------------------------------------------------
# Identity narrowing
# ---------------------------------------------------------------------------


def test_identity_narrows_after_concentrated_calls() -> None:
    arch = archetype_by_slug("anchored_conservative")
    state = IdentityState(archetype_slug=arch.slug, sectoral_identity="broad")
    call_counts = {"IT": 11, "banking": 2, "energy": 1}
    after = update_identity(state, TimeTickEvent(user_id="u1", sim_now=T0), arch, call_counts)
    assert after.sectoral_identity == "IT"


def test_identity_stays_broad_below_threshold() -> None:
    arch = archetype_by_slug("diversifier_index_investor")
    state = IdentityState(archetype_slug=arch.slug, sectoral_identity="broad")
    call_counts = {"IT": 4, "banking": 4, "energy": 3}
    after = update_identity(state, TimeTickEvent(user_id="u1", sim_now=T0), arch, call_counts)
    assert after.sectoral_identity == "broad"


# ---------------------------------------------------------------------------
# Goal shift on badge achievement
# ---------------------------------------------------------------------------


def test_goal_shifts_on_gyaani_achievement() -> None:
    arch = archetype_by_slug("aspirant_college_student")
    state = GoalState(primary_goal="badge", secondary_goal="social")
    after = update_goal(state, TimeTickEvent(user_id="u1", sim_now=T0), arch, gyaani_achieved=True)
    assert after.primary_goal == "influence"


def test_goal_unchanged_without_achievement() -> None:
    arch = archetype_by_slug("aspirant_college_student")
    state = GoalState(primary_goal="badge", secondary_goal="social")
    after = update_goal(state, TimeTickEvent(user_id="u1", sim_now=T0), arch, gyaani_achieved=False)
    assert after.primary_goal == "badge"


# ---------------------------------------------------------------------------
# Time-budget
# ---------------------------------------------------------------------------


def test_time_budget_refreshes_on_new_day() -> None:
    arch = archetype_by_slug("day_trader")
    state = TimeBudgetState(
        daily_minutes_remaining=5.0,
        minutes_used_today=85.0,
        active_hours=arch.active_hours,
        last_tick_date="2024-01-01",
    )
    next_day = TimeTickEvent(user_id="u1", sim_now=datetime(2024, 1, 2, 9, 0, 0))
    after = update_time_budget(state, next_day, arch)
    assert after.daily_minutes_remaining == arch.daily_time_budget_minutes_mean
    assert after.minutes_used_today == 0.0
    assert after.last_tick_date == "2024-01-02"


def test_time_budget_decrements_on_call() -> None:
    arch = archetype_by_slug("day_trader")
    state = TimeBudgetState(
        daily_minutes_remaining=60.0,
        minutes_used_today=30.0,
        active_hours=arch.active_hours,
        last_tick_date="2024-01-01",
    )
    event = CallMadeEvent(
        user_id="u1", ticker="TCS", sector="IT", direction="BULL", stars=4, sim_now=T0
    )
    after = update_time_budget(state, event, arch)
    assert after.daily_minutes_remaining == 57.0
    assert after.minutes_used_today == 33.0


# ---------------------------------------------------------------------------
# Knowledge
# ---------------------------------------------------------------------------


def test_knowledge_freshness_jumps_on_call() -> None:
    arch = archetype_by_slug("it_sector_specialist")
    state = KnowledgeState(last_decay_date="2024-01-01")
    event = CallMadeEvent(
        user_id="u1", ticker="TCS", sector="IT", direction="BULL", stars=4, sim_now=T0
    )
    after = update_knowledge(state, event, arch)
    fresh = dict(after.ticker_freshness)
    assert fresh["TCS"] == 1.0


def test_knowledge_decays_over_days() -> None:
    arch = archetype_by_slug("ghost_risk_junior")
    state = KnowledgeState(
        ticker_freshness=(("TCS", 1.0), ("INFY", 1.0)),
        last_decay_date="2024-01-01",
    )
    later = TimeTickEvent(user_id="u1", sim_now=datetime(2024, 1, 5, 10, 0, 0))
    after = update_knowledge(state, later, arch)
    fresh = dict(after.ticker_freshness)
    for tkr in ("TCS", "INFY"):
        if tkr in fresh:
            assert fresh[tkr] < 1.0


def test_pharma_doctor_retains_knowledge_longer_than_junior() -> None:
    pharma = archetype_by_slug("pharma_doctor")
    junior = archetype_by_slug("ghost_risk_junior")
    initial = KnowledgeState(
        ticker_freshness=(("ZYDUSLIFE", 1.0),),
        last_decay_date="2024-01-01",
    )
    week_later = TimeTickEvent(user_id="u1", sim_now=datetime(2024, 1, 8, 10, 0, 0))
    pharma_after = update_knowledge(initial, week_later, pharma)
    junior_after = update_knowledge(initial, week_later, junior)
    p_fresh = dict(pharma_after.ticker_freshness).get("ZYDUSLIFE", 0.0)
    j_fresh = dict(junior_after.ticker_freshness).get("ZYDUSLIFE", 0.0)
    assert p_fresh > j_fresh


# ---------------------------------------------------------------------------
# Trust
# ---------------------------------------------------------------------------


def test_trust_decreases_on_bad_rec() -> None:
    arch = archetype_by_slug("skeptic")
    state = TrustState(trust=0.5)
    event = PlatformRecEvent(
        user_id="u1", rec_type="ai_flag", was_acted_on=True, was_helpful=False, sim_now=T0
    )
    after = update_trust(state, event, arch)
    assert after.trust < state.trust
    assert after.bad_recs_received == 1


def test_trust_increases_on_good_rec_slower_than_decay() -> None:
    arch = archetype_by_slug("skeptic")
    state = TrustState(trust=0.5)
    bad = PlatformRecEvent(
        user_id="u1", rec_type="ai_flag", was_acted_on=True, was_helpful=False, sim_now=T0
    )
    good = PlatformRecEvent(
        user_id="u1", rec_type="ai_flag", was_acted_on=True, was_helpful=True, sim_now=T0
    )
    after_bad = update_trust(state, bad, arch)
    after_good = update_trust(state, good, arch)
    bad_delta = state.trust - after_bad.trust
    good_delta = after_good.trust - state.trust
    assert bad_delta > good_delta


def test_trust_clamped_to_unit_interval() -> None:
    arch = archetype_by_slug("skeptic")
    state = TrustState(trust=0.05)
    bad = PlatformRecEvent(
        user_id="u1", rec_type="ai_flag", was_acted_on=True, was_helpful=False, sim_now=T0
    )
    after = update_trust(state, bad, arch)
    assert after.trust >= 0.0


# ---------------------------------------------------------------------------
# Composed dispatch
# ---------------------------------------------------------------------------


def test_apply_event_dispatches_all_states() -> None:
    us = init_user_state("persona-apply-test", T0)
    win = OutcomeResolvedEvent(
        user_id=us.persona_id, ticker="TCS", sector="IT", outcome="WIN", stars=4, sim_now=T0
    )
    after = apply_event(us, win)
    assert after.affective.euphoria > us.affective.euphoria
    initial_mu = next(mu for sec, mu, phi in us.belief.sector_beliefs if sec == "IT")
    after_mu = next(mu for sec, mu, phi in after.belief.sector_beliefs if sec == "IT")
    assert after_mu > initial_mu
    assert after.trust.trust == us.trust.trust


def test_apply_event_does_not_mutate_input() -> None:
    us = init_user_state("persona-apply-pure", T0)
    win = OutcomeResolvedEvent(
        user_id=us.persona_id, ticker="TCS", sector="IT", outcome="WIN", stars=4, sim_now=T0
    )
    before_belief = us.belief
    _ = apply_event(us, win)
    assert us.belief is before_belief


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_states_frozen() -> None:
    state = BeliefState()
    with pytest.raises(Exception):
        state.version = "9.9.9"  # type: ignore[misc]


def test_user_state_frozen() -> None:
    us = init_user_state("persona-frozen", T0)
    with pytest.raises(Exception):
        us.persona_id = "different"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Version invariants
# ---------------------------------------------------------------------------


def test_all_states_carry_version() -> None:
    us = init_user_state("persona-versioned", T0)
    for attr in ("belief", "affective", "social", "identity", "goal", "time_budget", "knowledge", "trust"):
        sub = getattr(us, attr)
        assert sub.version == STATE_VERSION
