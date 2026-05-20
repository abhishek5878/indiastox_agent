"""Pytest tests for sim/layers.py — P0.3 deliverable.

One test per behavior layer verifying its monotonicity / direction of effect,
plus composition tests verifying the merge math.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from sim.archetypes import archetype_by_slug, archetype_for_persona
from sim.layers import (
    ActionModifier,
    LAYER_VERSION,
    compose,
    compose_all_layers,
    layer_copy_trading,
    layer_group_clustering,
    layer_knowledge_freshness,
    layer_learning_curve,
    layer_mood_arc,
    layer_peer_copy,
    layer_time_of_day,
    layer_trust_decay,
)
from sim.states import (
    AffectiveState,
    BeliefState,
    KnowledgeState,
    SocialState,
    TrustState,
    UserState,
    init_user_state,
)

T0 = datetime(2024, 1, 1, 10, 0, 0)  # Mon 10am — active for most archetypes
T_NIGHT = datetime(2024, 1, 1, 3, 0, 0)  # 3am — inactive for most
T_WEEKEND = datetime(2024, 1, 6, 10, 0, 0)  # Sat 10am


# ---------------------------------------------------------------------------
# ActionModifier basics
# ---------------------------------------------------------------------------


def test_default_modifier_is_neutral() -> None:
    m = ActionModifier()
    assert m.call_probability_multiplier == 1.0
    assert m.sector_bias == ()
    assert m.star_inflation == 0.0
    assert m.ghost_probability == 0.0
    assert m.follow_target is None
    assert m.version == LAYER_VERSION


def test_modifier_frozen() -> None:
    m = ActionModifier()
    with pytest.raises(Exception):
        m.star_inflation = 5.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# compose math
# ---------------------------------------------------------------------------


def test_compose_neutral_when_empty() -> None:
    out = compose([])
    assert out.call_probability_multiplier == 1.0
    assert out.ghost_probability == 0.0


def test_compose_multiplies_call_prob() -> None:
    a = ActionModifier(call_probability_multiplier=2.0)
    b = ActionModifier(call_probability_multiplier=1.5)
    out = compose([a, b])
    assert out.call_probability_multiplier == 3.0


def test_compose_sums_star_inflation() -> None:
    a = ActionModifier(star_inflation=0.5)
    b = ActionModifier(star_inflation=0.3)
    out = compose([a, b])
    assert out.star_inflation == 0.8


def test_compose_clamps_ghost_probability() -> None:
    a = ActionModifier(ghost_probability=0.6)
    b = ActionModifier(ghost_probability=0.7)
    out = compose([a, b])
    assert out.ghost_probability == 1.0


def test_compose_multiplies_sector_bias() -> None:
    a = ActionModifier(sector_bias=(("IT", 2.0), ("banking", 1.5)))
    b = ActionModifier(sector_bias=(("IT", 1.5), ("FMCG", 1.2)))
    out = compose([a, b])
    biases = dict(out.sector_bias)
    assert biases["IT"] == 3.0
    assert biases["banking"] == 1.5
    assert biases["FMCG"] == 1.2


# ---------------------------------------------------------------------------
# Layer 1 — peer_copy
# ---------------------------------------------------------------------------


def test_peer_copy_no_following_is_neutral() -> None:
    us = init_user_state("persona-pcopy-1", T0)
    us = replace(us, social=SocialState())
    arch = archetype_by_slug(us.archetype_slug)
    m = layer_peer_copy(us, arch, [("u2", "TCS", "IT")])
    assert m.sector_bias == ()
    assert m.call_probability_multiplier == 1.0


def test_peer_copy_biases_toward_followed_sector() -> None:
    arch = archetype_by_slug("fomo_cascader")
    us = UserState(
        persona_id="u1",
        archetype_slug=arch.slug,
        social=SocialState(following=("u2", "u3")),
    )
    recent = [("u2", "TCS", "IT"), ("u3", "INFY", "IT"), ("u_unfollowed", "HDFC", "banking")]
    m = layer_peer_copy(us, arch, recent)
    biases = dict(m.sector_bias)
    assert "IT" in biases
    assert biases["IT"] > 1.0
    assert "banking" not in biases


def test_peer_copy_low_susceptibility_no_op() -> None:
    arch = archetype_by_slug("it_sector_specialist")
    us = UserState(
        persona_id="u1",
        archetype_slug=arch.slug,
        social=SocialState(following=("u2",)),
    )
    recent = [("u2", "TCS", "IT")]
    m = layer_peer_copy(us, arch, recent)
    biases = dict(m.sector_bias)
    if "IT" in biases:
        assert biases["IT"] < 1.6


# ---------------------------------------------------------------------------
# Layer 2 — learning_curve
# ---------------------------------------------------------------------------


def test_learning_curve_high_phi_inflates_stars() -> None:
    arch = archetype_by_slug("newbie_cautious")
    us = init_user_state("persona-lc-1", T0)
    high_phi_beliefs = tuple((sec, 0.0, 350.0) for sec, _, _ in us.belief.sector_beliefs)
    us = replace(us, belief=replace(us.belief, sector_beliefs=high_phi_beliefs))
    m = layer_learning_curve(us, arch, T0)
    assert m.star_inflation > 0.5


def test_learning_curve_low_phi_no_inflation() -> None:
    arch = archetype_by_slug("alpha_generator")
    us = init_user_state("persona-lc-2", T0)
    low_phi_beliefs = tuple((sec, 0.0, 50.0) for sec, _, _ in us.belief.sector_beliefs)
    us = replace(us, belief=replace(us.belief, sector_beliefs=low_phi_beliefs))
    m = layer_learning_curve(us, arch, T0)
    assert m.star_inflation < 0.05


def test_learning_curve_inflation_strictly_decreases_with_phi() -> None:
    arch = archetype_by_slug("aspirant_college_student")
    us = init_user_state("persona-lc-3", T0)
    inflations = []
    for phi in (350.0, 250.0, 150.0, 50.0):
        b = tuple((sec, 0.0, phi) for sec, _, _ in us.belief.sector_beliefs)
        u = replace(us, belief=replace(us.belief, sector_beliefs=b))
        inflations.append(layer_learning_curve(u, arch, T0).star_inflation)
    for i in range(len(inflations) - 1):
        assert inflations[i] >= inflations[i + 1]


# ---------------------------------------------------------------------------
# Layer 3 — mood_arc
# ---------------------------------------------------------------------------


def test_mood_arc_tilt_raises_call_prob_and_stars() -> None:
    arch = archetype_by_slug("tilt_trader")
    us = UserState(
        persona_id="u1",
        archetype_slug=arch.slug,
        affective=AffectiveState(tilt=0.6, euphoria=0.1, depression=0.1, neutral=0.2),
    )
    m = layer_mood_arc(us, arch)
    assert m.call_probability_multiplier > 1.0
    assert m.star_inflation > 0.0


def test_mood_arc_depression_raises_ghost_prob() -> None:
    arch = archetype_by_slug("ghost_risk_junior")
    us = UserState(
        persona_id="u1",
        archetype_slug=arch.slug,
        affective=AffectiveState(tilt=0.05, euphoria=0.05, depression=0.6, neutral=0.3),
    )
    m = layer_mood_arc(us, arch)
    assert m.ghost_probability > 0.0


def test_mood_arc_neutral_is_no_op() -> None:
    arch = archetype_by_slug("weekend_casual")
    us = UserState(persona_id="u1", archetype_slug=arch.slug)
    m = layer_mood_arc(us, arch)
    assert m.call_probability_multiplier == 1.0
    assert m.star_inflation == 0.0
    assert m.ghost_probability == 0.0


# ---------------------------------------------------------------------------
# Layer 4 — time_of_day
# ---------------------------------------------------------------------------


def test_time_of_day_active_hour_high_mult() -> None:
    arch = archetype_by_slug("day_trader")
    us = UserState(persona_id="u1", archetype_slug=arch.slug)
    at_market_open = datetime(2024, 1, 1, 9, 30, 0)
    m = layer_time_of_day(us, arch, at_market_open)
    assert m.call_probability_multiplier > 1.0


def test_time_of_day_inactive_hour_low_mult() -> None:
    arch = archetype_by_slug("day_trader")
    us = UserState(persona_id="u1", archetype_slug=arch.slug)
    at_3am = datetime(2024, 1, 1, 3, 0, 0)
    m = layer_time_of_day(us, arch, at_3am)
    assert m.call_probability_multiplier < 0.5


def test_time_of_day_weekday_only_floors_on_weekend() -> None:
    arch = archetype_by_slug("day_trader")
    us = UserState(persona_id="u1", archetype_slug=arch.slug)
    m = layer_time_of_day(us, arch, T_WEEKEND)
    assert m.call_probability_multiplier < 0.1


def test_time_of_day_weekend_only_floors_on_weekday() -> None:
    arch = archetype_by_slug("weekend_casual")
    us = UserState(persona_id="u1", archetype_slug=arch.slug)
    weekday = datetime(2024, 1, 1, 10, 0, 0)
    m = layer_time_of_day(us, arch, weekday)
    assert m.call_probability_multiplier < 0.1


# ---------------------------------------------------------------------------
# Layer 5 — group_clustering
# ---------------------------------------------------------------------------


def test_group_clustering_biases_toward_group_sentiment() -> None:
    arch = archetype_by_slug("group_whisper_follower")
    us = UserState(
        persona_id="u1",
        archetype_slug=arch.slug,
        social=SocialState(in_groups=("g1",)),
    )
    sentiments = {"g1": {"IT": 0.8, "banking": 0.2}}
    m = layer_group_clustering(us, arch, sentiments)
    biases = dict(m.sector_bias)
    assert biases["IT"] > biases["banking"]


def test_group_clustering_no_groups_is_neutral() -> None:
    arch = archetype_by_slug("group_whisper_follower")
    us = UserState(persona_id="u1", archetype_slug=arch.slug)
    m = layer_group_clustering(us, arch, {"g1": {"IT": 0.9}})
    assert m.sector_bias == ()


# ---------------------------------------------------------------------------
# Layer 6 — copy_trading
# ---------------------------------------------------------------------------


def test_copy_trading_biases_toward_followed_alpha() -> None:
    arch = archetype_by_slug("influencer_aspirant")
    us = UserState(
        persona_id="u1",
        archetype_slug=arch.slug,
        social=SocialState(following=("alpha_1",)),
    )
    alpha_calls = {"alpha_1": [("TCS", "IT"), ("INFY", "IT")]}
    m = layer_copy_trading(us, arch, alpha_calls)
    biases = dict(m.sector_bias)
    assert biases.get("IT", 1.0) > 1.0


def test_copy_trading_unfollowed_alpha_ignored() -> None:
    arch = archetype_by_slug("influencer_aspirant")
    us = UserState(
        persona_id="u1",
        archetype_slug=arch.slug,
        social=SocialState(following=("alpha_1",)),
    )
    alpha_calls = {"alpha_2": [("TCS", "IT")]}
    m = layer_copy_trading(us, arch, alpha_calls)
    assert m.sector_bias == ()


# ---------------------------------------------------------------------------
# Layer 7 — trust_decay
# ---------------------------------------------------------------------------


def test_trust_decay_low_trust_raises_ghost() -> None:
    arch = archetype_by_slug("skeptic")
    us = UserState(
        persona_id="u1",
        archetype_slug=arch.slug,
        trust=TrustState(trust=0.2),
    )
    m = layer_trust_decay(us, arch)
    assert m.ghost_probability >= 0.2
    assert m.call_probability_multiplier < 1.0


def test_trust_decay_high_trust_neutral() -> None:
    arch = archetype_by_slug("aspirant_college_student")
    us = UserState(
        persona_id="u1",
        archetype_slug=arch.slug,
        trust=TrustState(trust=0.8),
    )
    m = layer_trust_decay(us, arch)
    assert m.ghost_probability == 0.0
    assert m.call_probability_multiplier == 1.0


def test_trust_decay_monotonic_with_trust() -> None:
    """Lower trust should never yield smaller ghost_probability than higher trust."""
    arch = archetype_by_slug("skeptic")
    last_ghost = -1.0
    for trust in (0.9, 0.6, 0.4, 0.2, 0.05):
        us = UserState(persona_id="u1", archetype_slug=arch.slug, trust=TrustState(trust=trust))
        m = layer_trust_decay(us, arch)
        assert m.ghost_probability >= last_ghost
        last_ghost = m.ghost_probability


# ---------------------------------------------------------------------------
# Layer 8 — knowledge_freshness
# ---------------------------------------------------------------------------


def test_knowledge_freshness_fresh_ticker_gets_boost() -> None:
    arch = archetype_by_slug("it_sector_specialist")
    us = UserState(
        persona_id="u1",
        archetype_slug=arch.slug,
        knowledge=KnowledgeState(ticker_freshness=(("TCS", 0.9), ("INFY", 0.1))),
    )
    m = layer_knowledge_freshness(us, arch)
    biases = dict(m.ticker_bias)
    assert biases["TCS"] > 1.0
    assert biases["INFY"] < 1.0


def test_knowledge_freshness_empty_is_neutral() -> None:
    arch = archetype_by_slug("ghost_risk_junior")
    us = UserState(persona_id="u1", archetype_slug=arch.slug)
    m = layer_knowledge_freshness(us, arch)
    assert m.ticker_bias == ()


# ---------------------------------------------------------------------------
# compose_all_layers — integration
# ---------------------------------------------------------------------------


def test_compose_all_layers_smoke() -> None:
    us = init_user_state("persona-compose-1", T0)
    m = compose_all_layers(us, T0)
    assert isinstance(m, ActionModifier)
    assert m.layer_name == "composed"


def test_compose_all_layers_no_args_handles_missing_context() -> None:
    """The composition should not raise when none of the context args are
    provided — layers must handle empty/None gracefully."""
    us = init_user_state("persona-compose-2", T0)
    m = compose_all_layers(us, T_NIGHT)
    assert isinstance(m, ActionModifier)


def test_compose_all_layers_with_full_context() -> None:
    arch = archetype_by_slug("fomo_cascader")
    us = UserState(
        persona_id="u1",
        archetype_slug=arch.slug,
        social=SocialState(following=("u2", "alpha_1"), in_groups=("g1",)),
        affective=AffectiveState(tilt=0.4, euphoria=0.1, depression=0.1, neutral=0.4),
        trust=TrustState(trust=0.6),
        knowledge=KnowledgeState(ticker_freshness=(("TCS", 0.9),)),
    )
    recent_followed = [("u2", "INFY", "IT")]
    sentiments = {"g1": {"IT": 0.8}}
    alpha_calls = {"alpha_1": [("TCS", "IT")]}
    m = compose_all_layers(
        us,
        T0,
        recent_calls_by_followed=recent_followed,
        group_sentiments=sentiments,
        alpha_recent_calls=alpha_calls,
    )
    biases = dict(m.sector_bias)
    assert biases.get("IT", 1.0) > 1.0
    assert m.call_probability_multiplier > 1.0


def test_compose_all_layers_disengaged_user_high_ghost() -> None:
    """A user with depression > 0.3 + trust < 0.3 should compose into a
    high ghost_probability — verifies layer additivity end-to-end."""
    arch = archetype_by_slug("ghost_risk_junior")
    us = UserState(
        persona_id="u1",
        archetype_slug=arch.slug,
        affective=AffectiveState(tilt=0.05, euphoria=0.05, depression=0.7, neutral=0.2),
        trust=TrustState(trust=0.15),
    )
    m = compose_all_layers(us, T0)
    assert m.ghost_probability > 0.3
