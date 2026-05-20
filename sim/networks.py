"""Cross-agent dynamics: groups, cascade graph, follow networks.

The 8 behavior layers in `sim/layers.py` consume per-user-tick context
(group_sentiments, recent_calls_by_followed, alpha_recent_calls). This
module produces that context from population-level views of the world,
and defines the new event kinds the substrate emits when cross-agent
state changes.

Design principles:
  - Pure functions. No I/O, no globals. The tick driver assembles inputs
    and consumes outputs.
  - Deterministic by `(user_id, week_of)` hashes. No shared RNG state.
  - Decoupled from sim/world.py. P0.5/P0.6 will wire the tick driver
    that invokes these once per population tick (typically once per sim day).

Three population functions:
  - `assign_groups`        — partition users into WhatsApp-style clusters
  - `compute_group_sentiments` — aggregate per-sector enthusiasm per group
  - `build_cascade_graph`  — recent alpha-generator calls, keyed by alpha id

Plus initial follow-edge assignment under a Pareto distribution
(alpha-generators land in the long tail; most users follow few; a few
follow many).

The new event kinds are typed; serialization to ndjson is a one-liner
for the tick driver to call. The events themselves carry the substrate
invariant `version` field.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from sim.archetypes import Archetype, archetype_by_slug
from sim.states import UserState


NETWORKS_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# New event kinds — cross-agent state transitions.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GroupFormedEvent:
    week_of: str
    group_id: str
    member_user_ids: Tuple[str, ...]
    sim_now: datetime
    kind: str = "group_formed"
    version: str = NETWORKS_VERSION


@dataclass(frozen=True)
class CascadeTriggeredEvent:
    alpha_user_id: str
    ticker: str
    sector: str
    follower_user_ids: Tuple[str, ...]
    sim_now: datetime
    kind: str = "cascade_triggered"
    version: str = NETWORKS_VERSION


@dataclass(frozen=True)
class CopyCallEvent:
    copier_user_id: str
    source_user_id: str
    ticker: str
    sector: str
    sim_now: datetime
    kind: str = "copy_call"
    version: str = NETWORKS_VERSION


@dataclass(frozen=True)
class FollowEdgeFormedEvent:
    follower_user_id: str
    followed_user_id: str
    sim_now: datetime
    kind: str = "follow_edge_formed"
    version: str = NETWORKS_VERSION


@dataclass(frozen=True)
class FollowEdgeDissolvedEvent:
    follower_user_id: str
    followed_user_id: str
    reason: str
    sim_now: datetime
    kind: str = "follow_edge_dissolved"
    version: str = NETWORKS_VERSION


# ---------------------------------------------------------------------------
# Group formation.
# ---------------------------------------------------------------------------


def assign_groups(
    user_ids: Iterable[str],
    week_of: str,
    group_size_target: int = 10,
) -> Dict[str, List[str]]:
    """Deterministic hash-bucket group assignment.

    Returns `{group_id -> [user_id, ...]}`. The number of groups is roughly
    `len(user_ids) // group_size_target`; each user maps to exactly one
    group per `week_of`. Same inputs always produce the same partition.

    The group_id format is `wk<week_of>-grp<idx>` so groups across weeks
    are distinct entities (a user moves between groups week-over-week,
    which matches the meeting's framing that group membership is
    transient and behavior-driven, not fixed).
    """
    user_list = sorted(set(user_ids))
    n_users = len(user_list)
    if n_users == 0:
        return {}

    n_groups = max(1, n_users // group_size_target)
    groups: Dict[str, List[str]] = {f"wk{week_of}-grp{i}": [] for i in range(n_groups)}

    for uid in user_list:
        h = hashlib.sha256(f"group:{uid}:{week_of}".encode()).hexdigest()
        bucket = int(h[:8], 16) % n_groups
        groups[f"wk{week_of}-grp{bucket}"].append(uid)

    return groups


def user_groups_for_week(
    user_id: str, week_of: str, all_user_ids: Iterable[str], group_size_target: int = 10
) -> Tuple[str, ...]:
    """Return the group_id(s) a single user belongs to in `week_of`.

    In the current design each user is in exactly one group per week, but
    the return type is a tuple so future "user in multiple groups" doesn't
    break the API.
    """
    groups = assign_groups(all_user_ids, week_of, group_size_target)
    result = tuple(gid for gid, members in groups.items() if user_id in members)
    return result


# ---------------------------------------------------------------------------
# Group sentiment.
# ---------------------------------------------------------------------------


def compute_group_sentiments(
    groups: Mapping[str, List[str]],
    recent_calls: Iterable[Tuple[str, str, str]],
) -> Dict[str, Dict[str, float]]:
    """Per-group per-sector enthusiasm in [0, 1].

    `recent_calls` is a sequence of (user_id, ticker, sector) within the
    sentiment window (P0.5/P0.6 sets the window — typically last 1-2 sim
    days). For each group, count sector occurrences from member calls,
    normalize so the per-group sector probabilities sum to 1.0.

    Empty groups or groups with no recent calls get an empty sentiment
    map (treated as "no signal" by `layer_group_clustering`).
    """
    member_to_group: Dict[str, str] = {}
    for gid, members in groups.items():
        for uid in members:
            member_to_group[uid] = gid

    group_sec_counts: Dict[str, Dict[str, int]] = {gid: {} for gid in groups}
    for uid, ticker, sector in recent_calls:
        gid = member_to_group.get(uid)
        if gid is None:
            continue
        group_sec_counts[gid][sector] = group_sec_counts[gid].get(sector, 0) + 1

    result: Dict[str, Dict[str, float]] = {}
    for gid, sec_counts in group_sec_counts.items():
        total = sum(sec_counts.values())
        if total == 0:
            result[gid] = {}
            continue
        result[gid] = {sec: cnt / total for sec, cnt in sec_counts.items()}
    return result


# ---------------------------------------------------------------------------
# Cascade graph — alpha-generator recent calls keyed by alpha id.
# ---------------------------------------------------------------------------


def build_cascade_graph(
    users: Iterable[UserState],
    recent_calls_with_time: Iterable[Tuple[str, str, str, datetime]],
    *,
    now: datetime,
    lookback_minutes: int = 120,
    alpha_archetype_slugs: Tuple[str, ...] = ("alpha_generator",),
) -> Dict[str, List[Tuple[str, str]]]:
    """Return `{alpha_user_id -> [(ticker, sector), ...]}` for alpha-archetype
    users' calls within the lookback window.

    This is exactly the shape `layer_copy_trading` consumes. Followers
    looking at the alpha sub-graph in the last 2 hours pick up signal here.
    """
    alpha_ids = {
        u.persona_id for u in users if u.archetype_slug in alpha_archetype_slugs
    }
    if not alpha_ids:
        return {}

    cutoff = now - timedelta(minutes=lookback_minutes)
    result: Dict[str, List[Tuple[str, str]]] = {aid: [] for aid in alpha_ids}
    for uid, ticker, sector, ts in recent_calls_with_time:
        if uid in alpha_ids and ts >= cutoff:
            result[uid].append((ticker, sector))

    return {aid: calls for aid, calls in result.items() if calls}


def collect_recent_calls_by_followed(
    follower_state: UserState,
    recent_calls_with_time: Iterable[Tuple[str, str, str, datetime]],
    *,
    now: datetime,
    lookback_minutes: int = 240,
) -> List[Tuple[str, str, str]]:
    """Filter the recent-calls stream to only those by users `follower_state`
    follows. Returns the (user_id, ticker, sector) shape `layer_peer_copy`
    consumes.
    """
    followed = set(follower_state.social.following)
    if not followed:
        return []

    cutoff = now - timedelta(minutes=lookback_minutes)
    return [
        (uid, ticker, sector)
        for uid, ticker, sector, ts in recent_calls_with_time
        if uid in followed and ts >= cutoff
    ]


# ---------------------------------------------------------------------------
# Follow-edge initialization (Pareto follower distribution).
# ---------------------------------------------------------------------------


def _pareto_invcdf(alpha: float, u: float) -> float:
    """Inverse-CDF of Pareto(alpha). u ∈ (0, 1)."""
    u = max(1e-12, min(1.0 - 1e-12, u))
    return 1.0 / (1.0 - u) ** (1.0 / alpha)


def initialize_follow_edges(
    users: Iterable[UserState],
    *,
    alpha_archetype_slugs: Tuple[str, ...] = ("alpha_generator", "influencer_aspirant"),
    max_follow_per_user: int = 30,
) -> Dict[str, List[str]]:
    """Assign each user an initial set of users they follow.

    Follower-count distribution is Pareto: alpha-generators and influencer-
    aspirants are the heavy-tail targets. Each user's follow-count is drawn
    from a Pareto with their archetype's `initial_follower_pareto_alpha`
    (low alpha → high variance → some users follow many, most follow few).

    Targets are weighted by archetype: alpha-generators get 10× the
    probability of being followed compared to a generic user. Deterministic
    by user_id hash so the same population produces the same graph.
    """
    user_list = sorted(users, key=lambda u: u.persona_id)
    if not user_list:
        return {}

    alpha_pool = [u.persona_id for u in user_list if u.archetype_slug in alpha_archetype_slugs]
    other_pool = [u.persona_id for u in user_list if u.archetype_slug not in alpha_archetype_slugs]

    result: Dict[str, List[str]] = {}
    for u in user_list:
        arch = archetype_by_slug(u.archetype_slug)
        h = hashlib.sha256(f"follow_count:{u.persona_id}".encode()).hexdigest()
        rand_u = int(h[:8], 16) / 0x100000000
        raw = _pareto_invcdf(arch.initial_follower_pareto_alpha, rand_u)
        n_follow = max(0, min(max_follow_per_user, int(raw) - 1))

        picks: List[str] = []
        for k in range(n_follow):
            pick_h = hashlib.sha256(f"follow_pick:{u.persona_id}:{k}".encode()).hexdigest()
            pick_r = int(pick_h[:8], 16) / 0x100000000
            if alpha_pool and pick_r < 0.4:
                idx = int(pick_h[8:16], 16) % len(alpha_pool)
                candidate = alpha_pool[idx]
            elif other_pool:
                idx = int(pick_h[8:16], 16) % len(other_pool)
                candidate = other_pool[idx]
            else:
                continue
            if candidate != u.persona_id and candidate not in picks:
                picks.append(candidate)

        result[u.persona_id] = picks

    return result


def follower_counts(follow_edges: Mapping[str, List[str]]) -> Dict[str, int]:
    """Invert a follow-edge dict to per-user follower counts.

    Useful for the social.follower_count cache and for verifying that
    initialize_follow_edges produces a Pareto-like distribution.
    """
    counts: Dict[str, int] = {uid: 0 for uid in follow_edges}
    for follower, followed_list in follow_edges.items():
        for f in followed_list:
            counts[f] = counts.get(f, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Event serialization (ndjson-ready).
# ---------------------------------------------------------------------------


def serialize_event(event: object) -> Dict[str, object]:
    """Convert any cross-agent event dataclass to a JSON-serializable dict.

    Datetime fields are isoformatted; tuple fields become lists. The result
    is ready to be `json.dumps`-ed and appended to `raw/agent_actions.ndjson`.
    The tick driver in P0.5/P0.6 is expected to call this.
    """
    d = asdict(event)
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = v.isoformat()
        elif isinstance(v, tuple):
            d[k] = list(v)
    return d


def events_to_ndjson(events: Iterable[object]) -> str:
    """Pack a sequence of events into newline-delimited JSON.

    Returns a string; the caller decides where to write it. Keeps this
    module free of file I/O so it stays pure.
    """
    return "\n".join(json.dumps(serialize_event(e), sort_keys=True) for e in events)
