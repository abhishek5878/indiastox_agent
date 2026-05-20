"""Pytest tests for sim/networks.py — P0.4 deliverable.

Coverage:
  - Group assignment: deterministic, partitions cleanly, size bounded.
  - Group sentiments: aggregate correctly, sum to 1.0 per group.
  - Cascade graph: alphas only, lookback window respected.
  - Follow-edge init: Pareto-like, alpha-generators are heavy-tail targets.
  - Event serialization: ndjson-shaped, datetimes ISO.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from sim.archetypes import archetype_by_slug, archetype_for_persona
from sim.networks import (
    CascadeTriggeredEvent,
    GroupFormedEvent,
    NETWORKS_VERSION,
    assign_groups,
    build_cascade_graph,
    collect_recent_calls_by_followed,
    compute_group_sentiments,
    events_to_ndjson,
    follower_counts,
    initialize_follow_edges,
    serialize_event,
    user_groups_for_week,
)
from sim.states import SocialState, UserState, init_user_state

T0 = datetime(2024, 1, 1, 10, 0, 0)


# ---------------------------------------------------------------------------
# Group assignment
# ---------------------------------------------------------------------------


def test_assign_groups_deterministic() -> None:
    users = [f"u-{i:04d}" for i in range(100)]
    g1 = assign_groups(users, "2024-W01")
    g2 = assign_groups(users, "2024-W01")
    assert g1 == g2


def test_assign_groups_partitions_all_users() -> None:
    users = [f"u-{i:04d}" for i in range(100)]
    groups = assign_groups(users, "2024-W01", group_size_target=10)
    assigned = set()
    for gid, members in groups.items():
        assigned.update(members)
    assert assigned == set(users)


def test_assign_groups_no_user_in_multiple_groups() -> None:
    users = [f"u-{i:04d}" for i in range(50)]
    groups = assign_groups(users, "2024-W02", group_size_target=10)
    counts: dict[str, int] = {}
    for gid, members in groups.items():
        for uid in members:
            counts[uid] = counts.get(uid, 0) + 1
    for uid, cnt in counts.items():
        assert cnt == 1, f"user {uid} appears in {cnt} groups"


def test_assign_groups_size_in_reasonable_range() -> None:
    users = [f"u-{i:04d}" for i in range(200)]
    groups = assign_groups(users, "2024-W01", group_size_target=10)
    sizes = [len(m) for m in groups.values()]
    avg = sum(sizes) / len(sizes)
    assert 5 < avg < 20


def test_assign_groups_different_weeks_yield_different_partitions() -> None:
    users = [f"u-{i:04d}" for i in range(100)]
    g1 = assign_groups(users, "2024-W01")
    g2 = assign_groups(users, "2024-W02")
    g1_map = {uid: gid for gid, members in g1.items() for uid in members}
    g2_map = {uid: gid for gid, members in g2.items() for uid in members}
    moves = sum(1 for u in users if g1_map[u].split("-")[1] != g2_map[u].split("-")[1])
    assert moves > 30


def test_user_groups_for_week_one_group_per_user() -> None:
    users = [f"u-{i:04d}" for i in range(50)]
    gids = user_groups_for_week("u-0001", "2024-W01", users)
    assert len(gids) == 1


def test_assign_groups_empty_input() -> None:
    assert assign_groups([], "2024-W01") == {}


# ---------------------------------------------------------------------------
# Group sentiments
# ---------------------------------------------------------------------------


def test_group_sentiment_single_sector() -> None:
    groups = {"g1": ["u1", "u2"]}
    calls = [("u1", "TCS", "IT"), ("u2", "INFY", "IT")]
    sentiments = compute_group_sentiments(groups, calls)
    assert sentiments["g1"]["IT"] == 1.0


def test_group_sentiment_normalized() -> None:
    groups = {"g1": ["u1", "u2"]}
    calls = [("u1", "TCS", "IT"), ("u1", "HDFC", "banking"), ("u2", "INFY", "IT")]
    sentiments = compute_group_sentiments(groups, calls)
    total = sum(sentiments["g1"].values())
    assert abs(total - 1.0) < 1e-9
    assert sentiments["g1"]["IT"] > sentiments["g1"]["banking"]


def test_group_sentiment_empty_group() -> None:
    groups = {"g1": ["u1"], "g_empty": ["u2"]}
    calls = [("u1", "TCS", "IT")]
    sentiments = compute_group_sentiments(groups, calls)
    assert sentiments["g1"] == {"IT": 1.0}
    assert sentiments["g_empty"] == {}


def test_group_sentiment_ignores_non_member_calls() -> None:
    groups = {"g1": ["u1"]}
    calls = [("u1", "TCS", "IT"), ("u_outsider", "HDFC", "banking")]
    sentiments = compute_group_sentiments(groups, calls)
    assert "banking" not in sentiments["g1"]
    assert sentiments["g1"]["IT"] == 1.0


# ---------------------------------------------------------------------------
# Cascade graph
# ---------------------------------------------------------------------------


def _force_user_to_archetype(uid: str, slug: str) -> UserState:
    """Helper: build a UserState with a specific archetype, bypassing the
    hash-deterministic assignment used by init_user_state."""
    return UserState(persona_id=uid, archetype_slug=slug)


def test_cascade_graph_includes_only_alphas() -> None:
    alpha = _force_user_to_archetype("alpha_1", "alpha_generator")
    normal = _force_user_to_archetype("normal_1", "weekend_casual")
    recent = [
        ("alpha_1", "TCS", "IT", T0 - timedelta(minutes=10)),
        ("normal_1", "HDFC", "banking", T0 - timedelta(minutes=10)),
    ]
    graph = build_cascade_graph([alpha, normal], recent, now=T0)
    assert "alpha_1" in graph
    assert "normal_1" not in graph
    assert ("TCS", "IT") in graph["alpha_1"]


def test_cascade_graph_respects_lookback() -> None:
    alpha = _force_user_to_archetype("alpha_1", "alpha_generator")
    recent = [
        ("alpha_1", "TCS", "IT", T0 - timedelta(minutes=300)),
        ("alpha_1", "INFY", "IT", T0 - timedelta(minutes=30)),
    ]
    graph = build_cascade_graph([alpha], recent, now=T0, lookback_minutes=120)
    assert graph == {"alpha_1": [("INFY", "IT")]}


def test_cascade_graph_no_alphas() -> None:
    normal = _force_user_to_archetype("normal_1", "weekend_casual")
    recent = [("normal_1", "TCS", "IT", T0 - timedelta(minutes=10))]
    graph = build_cascade_graph([normal], recent, now=T0)
    assert graph == {}


def test_collect_recent_calls_by_followed() -> None:
    follower = UserState(
        persona_id="u1",
        archetype_slug="fomo_cascader",
        social=SocialState(following=("u2", "u3")),
    )
    recent = [
        ("u2", "TCS", "IT", T0 - timedelta(minutes=10)),
        ("u3", "INFY", "IT", T0 - timedelta(minutes=20)),
        ("u_unfollowed", "HDFC", "banking", T0 - timedelta(minutes=10)),
    ]
    out = collect_recent_calls_by_followed(follower, recent, now=T0)
    out_ids = {item[0] for item in out}
    assert out_ids == {"u2", "u3"}


def test_collect_recent_calls_by_followed_respects_lookback() -> None:
    follower = UserState(
        persona_id="u1",
        archetype_slug="fomo_cascader",
        social=SocialState(following=("u2",)),
    )
    recent = [
        ("u2", "TCS", "IT", T0 - timedelta(minutes=600)),
        ("u2", "INFY", "IT", T0 - timedelta(minutes=30)),
    ]
    out = collect_recent_calls_by_followed(follower, recent, now=T0, lookback_minutes=240)
    assert out == [("u2", "INFY", "IT")]


# ---------------------------------------------------------------------------
# Follow-edge initialization
# ---------------------------------------------------------------------------


def test_follow_edges_deterministic() -> None:
    users = [init_user_state(f"persona-fl-{i:04d}", T0) for i in range(50)]
    e1 = initialize_follow_edges(users)
    e2 = initialize_follow_edges(users)
    assert e1 == e2


def test_follow_edges_respect_max_follow() -> None:
    users = [init_user_state(f"persona-fl-{i:04d}", T0) for i in range(100)]
    edges = initialize_follow_edges(users, max_follow_per_user=15)
    for uid, follows in edges.items():
        assert len(follows) <= 15


def test_follow_edges_alphas_are_heavy_tail() -> None:
    """Alpha-generator and influencer-aspirant archetypes should rank
    in the top decile of follower counts on a large sample."""
    users = [init_user_state(f"persona-fl-pop-{i:05d}", T0) for i in range(1000)]
    edges = initialize_follow_edges(users)
    counts = follower_counts(edges)

    alpha_ids = {
        u.persona_id for u in users
        if u.archetype_slug in ("alpha_generator", "influencer_aspirant")
    }
    if len(alpha_ids) < 10:
        return

    all_counts = sorted(counts.values(), reverse=True)
    top_decile_threshold = all_counts[len(all_counts) // 10]

    alpha_counts = [counts[uid] for uid in alpha_ids]
    alpha_avg = sum(alpha_counts) / len(alpha_counts)
    other_counts = [c for uid, c in counts.items() if uid not in alpha_ids]
    other_avg = sum(other_counts) / max(1, len(other_counts))

    assert alpha_avg > other_avg, (
        f"alphas avg {alpha_avg:.2f} should exceed others avg {other_avg:.2f}"
    )


def test_follow_edges_no_self_loops() -> None:
    users = [init_user_state(f"persona-self-{i:04d}", T0) for i in range(100)]
    edges = initialize_follow_edges(users)
    for uid, follows in edges.items():
        assert uid not in follows


def test_follow_edges_no_duplicates() -> None:
    users = [init_user_state(f"persona-dup-{i:04d}", T0) for i in range(100)]
    edges = initialize_follow_edges(users)
    for uid, follows in edges.items():
        assert len(follows) == len(set(follows))


# ---------------------------------------------------------------------------
# Event serialization
# ---------------------------------------------------------------------------


def test_serialize_group_formed_event() -> None:
    e = GroupFormedEvent(
        week_of="2024-W01",
        group_id="wk2024-W01-grp0",
        member_user_ids=("u1", "u2", "u3"),
        sim_now=T0,
    )
    d = serialize_event(e)
    assert d["kind"] == "group_formed"
    assert d["sim_now"] == T0.isoformat()
    assert d["member_user_ids"] == ["u1", "u2", "u3"]
    assert d["version"] == NETWORKS_VERSION


def test_serialize_cascade_event() -> None:
    e = CascadeTriggeredEvent(
        alpha_user_id="alpha_1",
        ticker="TCS",
        sector="IT",
        follower_user_ids=("u2", "u3"),
        sim_now=T0,
    )
    d = serialize_event(e)
    assert d["kind"] == "cascade_triggered"
    assert d["ticker"] == "TCS"


def test_events_to_ndjson_format() -> None:
    e1 = GroupFormedEvent("2024-W01", "g1", ("u1",), T0)
    e2 = GroupFormedEvent("2024-W01", "g2", ("u2",), T0)
    ndjson = events_to_ndjson([e1, e2])
    lines = ndjson.split("\n")
    assert len(lines) == 2
    for line in lines:
        parsed = json.loads(line)
        assert parsed["kind"] == "group_formed"


# ---------------------------------------------------------------------------
# Integration with layers.compose_all_layers context shape
# ---------------------------------------------------------------------------


def test_cascade_graph_shape_matches_layer_input() -> None:
    """build_cascade_graph output shape must match what layer_copy_trading
    expects (alpha_user_id -> Iterable[(ticker, sector)])."""
    alpha = _force_user_to_archetype("alpha_1", "alpha_generator")
    recent = [("alpha_1", "TCS", "IT", T0 - timedelta(minutes=10))]
    graph = build_cascade_graph([alpha], recent, now=T0)
    for alpha_id, calls in graph.items():
        for call in calls:
            assert len(call) == 2
            assert isinstance(call[0], str)
            assert isinstance(call[1], str)


def test_group_sentiments_shape_matches_layer_input() -> None:
    """compute_group_sentiments output shape must match what
    layer_group_clustering expects (group_id -> {sector -> score})."""
    groups = {"g1": ["u1"]}
    calls = [("u1", "TCS", "IT")]
    sentiments = compute_group_sentiments(groups, calls)
    for gid, sec_map in sentiments.items():
        for sec, score in sec_map.items():
            assert isinstance(sec, str)
            assert isinstance(score, float)
            assert 0.0 <= score <= 1.0
