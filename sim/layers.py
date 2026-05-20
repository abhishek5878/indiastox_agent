"""Eight new behavior layers atop the existing 14.

Each layer reads the agent's archetype + current state and returns a typed
`ActionModifier` describing how the user's next action should be biased.
Layers compose: `compose(modifiers)` merges them into a single modifier
that downstream tick code applies to action selection (sector, ticker,
star confidence, call-vs-ghost probability).

Why this shape:
  - Layers are pure functions. No global RNG, no mutation. They take
    everything they need as args; testable in isolation.
  - Layers don't know about each other. Composition lives in one place.
  - Layers don't read DB or world state directly — they take small,
    structured context args (recent_calls_by_followed, group_sentiments,
    alpha_recent_calls). The tick driver assembles these before calling.
    Keeps the layer code free of DuckDB connection management.
  - The legacy 14 layers in `sim/world.py` are not touched. P0.5/P0.6
    will wire a new tick driver that consumes BOTH the legacy layers AND
    these new ones; today they coexist.

The 8 layers and what each models:

  1. peer_copy           — per-edge social copying from followed users
  2. learning_curve      — calibration improves with experience
  3. mood_arc            — tilt/euphoria/depression shape next action
  4. time_of_day         — activity peaks at archetype-specific hours
  5. group_clustering    — implicit-group sentiment biases sector choice
  6. copy_trading        — explicit follow-the-alpha sub-graph
  7. trust_decay         — low platform trust raises ghost probability
  8. knowledge_freshness — fresh tickers bias ticker selection
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from sim.archetypes import Archetype, archetype_by_slug
from sim.states import UserState


LAYER_VERSION = "1.0.0"


@dataclass(frozen=True)
class ActionModifier:
    """Bias signal returned by each behavior layer.

    Composition semantics (used by `compose`):
      - call_probability_multiplier: layers multiply (default 1.0)
      - sector_bias: per-sector multipliers; layers multiply (default 1.0)
      - ticker_bias: per-ticker multipliers; layers multiply (default 1.0)
      - star_inflation: additive offset to nominal star confidence
      - ghost_probability: layers sum, clamp to [0, 1]
      - follow_target: at most one across layers (first non-None wins);
        compose returns None if multiple layers disagree (kept for
        debuggability — the tick driver decides what to do with it)
    """

    call_probability_multiplier: float = 1.0
    sector_bias: Tuple[Tuple[str, float], ...] = ()
    ticker_bias: Tuple[Tuple[str, float], ...] = ()
    star_inflation: float = 0.0
    ghost_probability: float = 0.0
    follow_target: Optional[str] = None
    layer_name: str = ""
    version: str = LAYER_VERSION


# ---------------------------------------------------------------------------
# Composition.
# ---------------------------------------------------------------------------


def compose(modifiers: Iterable[ActionModifier]) -> ActionModifier:
    """Merge an iterable of ActionModifiers into a single result.

    Multiplicative fields multiply, additive sum (with ghost_probability
    clamped to [0, 1]), follow_target picks first non-None. layer_name on
    the composed result is "composed".
    """
    call_mult = 1.0
    sector_bias: Dict[str, float] = {}
    ticker_bias: Dict[str, float] = {}
    star_inflation = 0.0
    ghost_prob = 0.0
    follow_target: Optional[str] = None

    for m in modifiers:
        call_mult *= m.call_probability_multiplier
        for sec, mult in m.sector_bias:
            sector_bias[sec] = sector_bias.get(sec, 1.0) * mult
        for tkr, mult in m.ticker_bias:
            ticker_bias[tkr] = ticker_bias.get(tkr, 1.0) * mult
        star_inflation += m.star_inflation
        ghost_prob += m.ghost_probability
        if follow_target is None and m.follow_target is not None:
            follow_target = m.follow_target

    return ActionModifier(
        call_probability_multiplier=call_mult,
        sector_bias=tuple(sorted(sector_bias.items())),
        ticker_bias=tuple(sorted(ticker_bias.items())),
        star_inflation=star_inflation,
        ghost_probability=min(1.0, ghost_prob),
        follow_target=follow_target,
        layer_name="composed",
    )


# ---------------------------------------------------------------------------
# Layer 1 — peer_copy
# ---------------------------------------------------------------------------


def layer_peer_copy(
    us: UserState,
    arch: Archetype,
    recent_calls_by_followed: Iterable[Tuple[str, str, str]] = (),
) -> ActionModifier:
    """Bias next call toward what followed users recently called.

    `recent_calls_by_followed` is a sequence of (other_user_id, ticker, sector)
    triples observed in the last few ticks. Only entries where
    other_user_id is in `us.social.following` count. Bias magnitude scales
    with `arch.social_susceptibility`.
    """
    if not us.social.following or arch.social_susceptibility < 0.05:
        return ActionModifier(layer_name="peer_copy")

    sec_counts: Dict[str, int] = {}
    tkr_counts: Dict[str, int] = {}
    matched = 0
    for other_id, ticker, sector in recent_calls_by_followed:
        if other_id in us.social.following:
            sec_counts[sector] = sec_counts.get(sector, 0) + 1
            tkr_counts[ticker] = tkr_counts.get(ticker, 0) + 1
            matched += 1

    if matched == 0:
        return ActionModifier(layer_name="peer_copy")

    boost = 1.0 + 2.0 * arch.social_susceptibility
    sec_bias = tuple((sec, boost ** (cnt / matched)) for sec, cnt in sec_counts.items())
    tkr_bias = tuple((tkr, boost ** (cnt / matched)) for tkr, cnt in tkr_counts.items())

    return ActionModifier(
        sector_bias=sec_bias,
        ticker_bias=tkr_bias,
        call_probability_multiplier=1.0 + 0.5 * arch.social_susceptibility,
        layer_name="peer_copy",
    )


# ---------------------------------------------------------------------------
# Layer 2 — learning_curve
# ---------------------------------------------------------------------------


def layer_learning_curve(
    us: UserState, arch: Archetype, sim_now: datetime
) -> ActionModifier:
    """Star-confidence inflation drops as belief phi shrinks.

    A user with high phi (uncertain about their skill) tends to over-star;
    as phi shrinks toward the floor (50), star inflation decays toward 0.
    Phi shrinks via the `update_belief` rule whenever outcomes resolve, so
    the more resolved calls a user has accumulated in a sector, the more
    calibrated their stars become.
    """
    if not us.belief.sector_beliefs:
        return ActionModifier(star_inflation=1.0, layer_name="learning_curve")

    avg_phi = sum(phi for sec, mu, phi in us.belief.sector_beliefs) / len(us.belief.sector_beliefs)
    inflation = max(0.0, (avg_phi - 50.0) / 300.0)
    return ActionModifier(
        star_inflation=inflation * (1.0 - arch.learning_curve_rate * 0.5),
        layer_name="learning_curve",
    )


# ---------------------------------------------------------------------------
# Layer 3 — mood_arc
# ---------------------------------------------------------------------------


def layer_mood_arc(us: UserState, arch: Archetype) -> ActionModifier:
    """Affective state biases call_prob, star_inflation, ghost_prob.

    Tilt > 0.3 → revenge trading: call_probability_multiplier rises sharply
    and stars inflate (the user picks higher confidence under tilt to
    "win back" the loss). Euphoria > 0.3 → moderate star inflation (riding
    the high). Depression > 0.3 → ghost_probability rises (sustained loss
    arc trends to disengagement).
    """
    mood = us.affective
    call_mult = 1.0
    star_inf = 0.0
    ghost_p = 0.0

    if mood.tilt > 0.3:
        call_mult *= 1.0 + 2.0 * (mood.tilt - 0.3)
        star_inf += arch.star_inflation_under_tilt * (mood.tilt - 0.3) * 2.0
    if mood.euphoria > 0.3:
        star_inf += (mood.euphoria - 0.3) * 1.5
    if mood.depression > 0.3:
        ghost_p += (mood.depression - 0.3) * 0.4
        call_mult *= 1.0 - 0.5 * (mood.depression - 0.3)

    return ActionModifier(
        call_probability_multiplier=max(0.0, call_mult),
        star_inflation=star_inf,
        ghost_probability=ghost_p,
        layer_name="mood_arc",
    )


# ---------------------------------------------------------------------------
# Layer 4 — time_of_day
# ---------------------------------------------------------------------------


def layer_time_of_day(
    us: UserState, arch: Archetype, sim_now: datetime
) -> ActionModifier:
    """Multiply call_probability by active-hour bias.

    If the current sim_now hour is in `arch.active_hours`, multiplier is
    high (~3×); otherwise low (~0.2×). Weekday-only / weekend-only
    archetypes additionally floor the multiplier on the wrong day.
    """
    hour = sim_now.hour
    weekday = sim_now.weekday() < 5  # Mon-Fri

    if arch.weekday_only and not weekday:
        return ActionModifier(call_probability_multiplier=0.05, layer_name="time_of_day")
    if arch.weekend_only and weekday:
        return ActionModifier(call_probability_multiplier=0.05, layer_name="time_of_day")

    in_active = hour in arch.active_hours
    mult = 3.0 if in_active else 0.2
    return ActionModifier(call_probability_multiplier=mult, layer_name="time_of_day")


# ---------------------------------------------------------------------------
# Layer 5 — group_clustering
# ---------------------------------------------------------------------------


def layer_group_clustering(
    us: UserState,
    arch: Archetype,
    group_sentiments: Optional[Mapping[str, Mapping[str, float]]] = None,
) -> ActionModifier:
    """If the user is in a group, bias sector choice toward group sentiment.

    `group_sentiments[group_id][sector] = score in [0, 1]` — higher score
    means the group is more bullish on that sector. The user adopts a
    weighted-average sentiment across their groups, with bias magnitude
    gated by `arch.social_susceptibility * 0.5` (groups have less
    influence than direct peer follows).
    """
    if not us.social.in_groups or not group_sentiments:
        return ActionModifier(layer_name="group_clustering")

    aggregated: Dict[str, float] = {}
    n_groups = 0
    for gid in us.social.in_groups:
        sents = group_sentiments.get(gid)
        if sents is None:
            continue
        n_groups += 1
        for sec, score in sents.items():
            aggregated[sec] = aggregated.get(sec, 0.0) + score

    if n_groups == 0:
        return ActionModifier(layer_name="group_clustering")

    boost_strength = arch.social_susceptibility * 0.5
    sec_bias = tuple(
        (sec, 1.0 + boost_strength * (total / n_groups))
        for sec, total in aggregated.items()
    )
    return ActionModifier(sector_bias=sec_bias, layer_name="group_clustering")


# ---------------------------------------------------------------------------
# Layer 6 — copy_trading
# ---------------------------------------------------------------------------


def layer_copy_trading(
    us: UserState,
    arch: Archetype,
    alpha_recent_calls: Optional[Mapping[str, Iterable[Tuple[str, str]]]] = None,
) -> ActionModifier:
    """Explicit follow-the-alpha sub-graph.

    Distinct from peer_copy: peer_copy biases toward any followed user's
    recent calls; copy_trading is specifically biased toward alpha_generator
    archetype users in the followed set, with a strong sector/ticker bias
    when those alphas have made recent calls. Magnitude scales with
    archetype-default copy strength.
    """
    if not us.social.following or not alpha_recent_calls:
        return ActionModifier(layer_name="copy_trading")

    sec_counts: Dict[str, int] = {}
    tkr_counts: Dict[str, int] = {}
    matched = 0
    for alpha_id, calls in alpha_recent_calls.items():
        if alpha_id in us.social.following:
            for ticker, sector in calls:
                sec_counts[sector] = sec_counts.get(sector, 0) + 1
                tkr_counts[ticker] = tkr_counts.get(ticker, 0) + 1
                matched += 1

    if matched == 0:
        return ActionModifier(layer_name="copy_trading")

    boost = 1.0 + 4.0 * arch.social_susceptibility
    sec_bias = tuple((sec, boost) for sec, _ in sec_counts.items())
    tkr_bias = tuple((tkr, boost * 1.5) for tkr, _ in tkr_counts.items())

    return ActionModifier(
        sector_bias=sec_bias,
        ticker_bias=tkr_bias,
        call_probability_multiplier=1.0 + 0.8 * arch.social_susceptibility,
        layer_name="copy_trading",
    )


# ---------------------------------------------------------------------------
# Layer 7 — trust_decay
# ---------------------------------------------------------------------------


def layer_trust_decay(us: UserState, arch: Archetype) -> ActionModifier:
    """Low platform trust raises ghost probability and dampens activity.

    Trust < 0.3 → ghost_probability += 0.2 (the disengagement floor);
    trust < 0.5 → call_prob multiplier 0.7× (dampened engagement).
    Trust ≥ 0.7 is a no-op so engaged users see no penalty.
    """
    trust = us.trust.trust
    ghost_p = 0.0
    call_mult = 1.0
    if trust < 0.3:
        ghost_p += 0.2
        call_mult *= 0.5
    elif trust < 0.5:
        call_mult *= 0.7

    return ActionModifier(
        call_probability_multiplier=call_mult,
        ghost_probability=ghost_p,
        layer_name="trust_decay",
    )


# ---------------------------------------------------------------------------
# Layer 8 — knowledge_freshness
# ---------------------------------------------------------------------------


def layer_knowledge_freshness(us: UserState, arch: Archetype) -> ActionModifier:
    """Bias ticker selection toward tickers with fresh knowledge.

    Freshness ∈ [0, 1]; freshness=1.0 just-touched, decays daily. Tickers
    with freshness ≥ 0.7 get a 2× bias; stale tickers (freshness < 0.2) get
    a 0.3× bias. Tickers with no entry are neutral (no bias emitted).
    """
    if not us.knowledge.ticker_freshness:
        return ActionModifier(layer_name="knowledge_freshness")

    biases: List[Tuple[str, float]] = []
    for tkr, freshness in us.knowledge.ticker_freshness:
        if freshness >= 0.7:
            biases.append((tkr, 2.0))
        elif freshness < 0.2:
            biases.append((tkr, 0.3))

    return ActionModifier(
        ticker_bias=tuple(biases),
        layer_name="knowledge_freshness",
    )


# ---------------------------------------------------------------------------
# Top-level convenience: run all 8 layers and compose.
# ---------------------------------------------------------------------------


def compose_all_layers(
    us: UserState,
    sim_now: datetime,
    recent_calls_by_followed: Iterable[Tuple[str, str, str]] = (),
    group_sentiments: Optional[Mapping[str, Mapping[str, float]]] = None,
    alpha_recent_calls: Optional[Mapping[str, Iterable[Tuple[str, str]]]] = None,
) -> ActionModifier:
    """Run every layer and merge into one ActionModifier.

    The tick driver calls this once per user-tick and applies the result
    to action selection (sector, ticker, stars, call-vs-ghost branch).
    The archetype is fetched once via `archetype_by_slug` to avoid 8
    redundant lookups.
    """
    arch = archetype_by_slug(us.archetype_slug)
    modifiers = [
        layer_peer_copy(us, arch, recent_calls_by_followed),
        layer_learning_curve(us, arch, sim_now),
        layer_mood_arc(us, arch),
        layer_time_of_day(us, arch, sim_now),
        layer_group_clustering(us, arch, group_sentiments),
        layer_copy_trading(us, arch, alpha_recent_calls),
        layer_trust_decay(us, arch),
        layer_knowledge_freshness(us, arch),
    ]
    return compose(modifiers)
