"""Living-world simulator.

Advances synthetic time forward from the W01 baseline. Each tick:
  - 1 to N new personas join (synthesized name + Indian city + Unstop or
    whatsapp_dark channel; same persona_id schema as generate.py).
  - Existing users make a few new predictions (biased by their true_skill,
    same generator that powered N1 signal).
  - Any prediction whose resolved_at <= synthetic now resolves (WIN/LOSS/DRAW
    biased by maker's true_skill).
  - Side effects mutate dim_user, fact_acquisition, fact_engagement,
    fact_prediction, agent_actions (the watcher decisions).
  - One row per action lands in `sim_events` so the UI's event stream
    has a feed to read.

Determinism: each tick takes a `tick_seed` so the same (baseline, seed)
yields the same mutations. UI default: seed = floor(synthetic_minutes / tick_minutes).
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import duckdb

_REPO = Path(__file__).resolve().parents[1]
WAREHOUSE = _REPO / "warehouse" / "indiastox.duckdb"

# Synthetic time starts at the W01 boundary (Mon 8am IST). The baseline
# warehouse contains all W01 events through Sun. Sim picks up from W01+7d.
WEEK_START = datetime(2024, 1, 1, 8, 0, 0)  # naive UTC (matches warehouse convention)
SIM_T0 = datetime(2024, 1, 8, 0, 0, 0)  # synthetic clock begins here

STOCK_SYMBOLS = ["RELIANCE", "TCS", "INFY", "HDFC", "WIPRO",
                 "ICICIBANK", "BAJFINANCE", "SBIN", "HCLTECH", "ITC"]
TIER1_CITIES = ["Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai", "Pune"]
TIER2_CITIES = ["Lucknow", "Jaipur", "Indore", "Kanpur", "Surat", "Bhopal", "Patna"]
FIRST_NAMES = ["Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh",
               "Mohammed", "Krishna", "Ishaan", "Ananya", "Aadhya", "Pari",
               "Diya", "Anika", "Saanvi", "Aaradhya", "Myra", "Sara", "Aanya"]
LAST_NAMES = ["Sharma", "Verma", "Patel", "Singh", "Kumar", "Gupta", "Iyer",
              "Reddy", "Joshi", "Mehta", "Kapoor", "Bose", "Shah", "Khanna"]


# ---------------------------------------------------------------------------
# Schema bootstrap — sim_events table
# ---------------------------------------------------------------------------

_SIM_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS sim_events (
  event_id TEXT PRIMARY KEY,
  sim_ts TIMESTAMP NOT NULL,
  wall_ts TIMESTAMP NOT NULL,
  kind TEXT NOT NULL,
  actor TEXT,
  payload JSON,
  lens TEXT
);
"""


def _ensure_table(con) -> None:
    con.execute(_SIM_EVENTS_DDL)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class WorldState:
    sim_now: datetime
    accel: float = 1.0  # synthetic minutes per wall second
    tick_count: int = 0
    last_growth_check_ghost: Optional[float] = None
    last_growth_check_at: Optional[datetime] = None
    # Behavior state per user. Schema:
    #   {
    #     "streak": [WIN|LOSS|DRAW, ...],            (last 5)
    #     "cooldown_until": datetime|None,
    #     "ticker_history": {symbol: count},          (lifetime per-user)
    #     "loss_tickers": {symbol: loss_count},       (where they got burned)
    #     "stars_offset": int,                        (calibration drift)
    #   }
    user_state: dict = field(default_factory=dict)
    # Most-recent news cascade. (symbol, direction, until_ts). New calls in the
    # ~2 sim hours after a cascade have a heightened probability of landing on
    # the cascade ticker (FOMO follow-on).
    recent_cascade: Optional[dict] = None
    # Recent high-Gyaani calls so lower-Gyaani users can shadow them. Each
    # entry: dict(symbol, direction, until). The window closes 60 sim-min
    # after the call so the shadow effect is bounded.
    recent_alpha_calls: list = field(default_factory=list)


def fresh_world() -> WorldState:
    return WorldState(sim_now=SIM_T0, accel=60.0)


# ---------------------------------------------------------------------------
# Behavior layers
# ---------------------------------------------------------------------------

# Sector map. The IndiaStox product surfaces tickers grouped by sector;
# users disproportionately call within sectors they understand.
SECTOR_OF = {
    "RELIANCE": "energy", "ONGC": "energy",
    "TCS": "IT", "INFY": "IT", "WIPRO": "IT", "HCLTECH": "IT",
    "HDFC": "banking", "ICICIBANK": "banking", "SBIN": "banking", "BAJFINANCE": "banking",
    "ITC": "FMCG",
}

# Tickers flagged Pre-IPO in the product. Mirrors metrics.definitions.PRE_IPO_TICKERS.
PRE_IPO_TICKERS = {"BAJFINANCE", "HCLTECH"}

# Occupation -> preferred sectors. Students lean into IT + Pre-IPO names;
# working professionals lean into banking + FMCG. Default is uniform.
SECTOR_AFFINITY = {
    "Student": ["IT", "IT", "energy", "banking"],
    "Working Professional": ["banking", "banking", "FMCG", "IT"],
}


def _activity_multiplier(sim_now: datetime) -> float:
    """Time-of-day + day-of-week rhythm. NSE is closed on Sat/Sun, so weekend
    volume drops to ~5% of weekday. Within a weekday, calls peak mid-session,
    dip at lunch, light overnight.
    """
    # Weekend: trading is closed; engagement is residual (forum chatter only).
    if sim_now.weekday() >= 5:  # Saturday=5, Sunday=6
        return 0.05
    h = sim_now.hour
    if 9 <= h < 11:
        return 1.6   # opening surge
    if 11 <= h < 13:
        return 1.3   # mid-morning
    if 13 <= h < 14:
        return 0.8   # lunch lull
    if 14 <= h < 16:
        return 1.5   # close ramp
    if 16 <= h < 20:
        return 0.7   # post-close commentary
    return 0.25      # overnight


def _watchlist_for_user(world: WorldState, user_id: str) -> list[str]:
    """Top tickers the user has historically called, ranked by frequency.

    Real retail concentrates: most users develop a 3-5 ticker watchlist and
    rarely venture outside it. This is the persisted view of that pattern.
    """
    hist = world.user_state.get(user_id, {}).get("ticker_history", {})
    return sorted(hist.keys(), key=lambda t: -hist[t])[:5]


def _record_call(world: WorldState, user_id: str, symbol: str) -> None:
    s = world.user_state.setdefault(user_id, {
        "streak": [], "cooldown_until": None,
        "ticker_history": {}, "loss_tickers": {}, "stars_offset": 0,
        "anchor_ticker": None,
    })
    s["ticker_history"][symbol] = s["ticker_history"].get(symbol, 0) + 1
    # Anchor on first call. Lock-in is intentional: real users do return
    # disproportionately to the first thing they touched.
    if s.get("anchor_ticker") is None:
        s["anchor_ticker"] = symbol


def _record_alpha_call(world: WorldState, symbol: str, direction: str) -> None:
    """High-Gyaani users move the cohort. Record their call so lower-mu users
    can shadow it within the next 60 sim-minutes."""
    world.recent_alpha_calls.append(dict(
        symbol=symbol,
        direction=direction,
        until=world.sim_now + timedelta(minutes=60),
    ))
    # Cap the list so memory stays bounded.
    if len(world.recent_alpha_calls) > 20:
        world.recent_alpha_calls = world.recent_alpha_calls[-20:]


def _is_leaderboard_sprint(sim_now: datetime) -> bool:
    """True during the last-day trading hours of the simulated week.

    Friday afternoon (weekday 4, hours 14-16 local) is when leaderboard
    rankings get locked for the week; high-rank users sprint to defend
    or seize position. Their activity multiplier 2x's in this window.
    """
    return sim_now.weekday() == 4 and 14 <= sim_now.hour < 16


def _synthetic_occupation(user_id: str) -> str:
    """Deterministic occupation fallback for baseline users (whose dim_user
    row has NULL occupation). Hashes user_id to {Student, Working Professional}
    so the sector-affinity branch still has signal to fire on."""
    h = int(hashlib.sha256(user_id.encode()).hexdigest()[:4], 16)
    return "Student" if h % 100 < 45 else "Working Professional"


def _alpha_call_for_user(world: WorldState, user_mu: float, rng: random.Random):
    """Return a recent high-Gyaani call to shadow, or None.

    Only lower-Gyaani users (mu below threshold) follow alpha calls; high-mu
    users move the cohort, they don't chase it.
    """
    if user_mu >= 1700:
        return None
    fresh = [a for a in world.recent_alpha_calls if a["until"] > world.sim_now]
    world.recent_alpha_calls = fresh  # gc stale entries
    if not fresh:
        return None
    return rng.choice(fresh)


def _ticker_for_user(
    rng: random.Random,
    world: WorldState,
    user_id: str,
    occupation: Optional[str],
    user_mu: float = 1500.0,
) -> tuple[str, str]:
    """Pick a ticker for a user, returning (symbol, reason).

    Decision tree (each branch consumes a fixed probability mass):
      18%  social proof: low-mu users shadow recent high-Gyaani calls.
      18%  loss aversion / double-down: re-call a ticker the user lost on.
      33%  FOMO follow-on: pick the recent news cascade ticker (within 2h).
      45%  anchor on first call: re-pick the user's first-ever ticker.
      78%  watchlist concentration: pick from top-5 historical tickers.
      95%  sector affinity (synthetic occupation if NULL).
      5%   wildcard uniform across the full symbol list.

    Higher-priority branches (lower r threshold) take precedence; users
    without the qualifying history fall through to the next gate.
    """
    s = world.user_state.get(user_id) or {}
    history = s.get("ticker_history", {})
    loss_tickers = s.get("loss_tickers", {})
    anchor = s.get("anchor_ticker")
    r = rng.random()

    if r < 0.18:
        alpha = _alpha_call_for_user(world, user_mu, rng)
        if alpha is not None:
            return alpha["symbol"], "social_proof"
    if r < 0.18 and any(c >= 1 for c in loss_tickers.values()):
        losers = [t for t, c in loss_tickers.items() if c >= 1]
        return rng.choice(losers), "loss_aversion"
    if r < 0.33 and world.recent_cascade is not None and world.recent_cascade["until"] > world.sim_now:
        return world.recent_cascade["symbol"], "fomo_followon"
    if r < 0.45 and anchor and sum(history.values()) >= 3:
        return anchor, "anchor"
    if r < 0.78 and sum(history.values()) >= 2:
        wl = _watchlist_for_user(world, user_id)
        if wl:
            return rng.choice(wl), "watchlist"
    occ = occupation if occupation in SECTOR_AFFINITY else _synthetic_occupation(user_id)
    if r < 0.95:
        sector = rng.choice(SECTOR_AFFINITY[occ])
        candidates = [t for t, sec in SECTOR_OF.items() if sec == sector]
        if candidates:
            return rng.choice(candidates), "sector_affinity"
    return rng.choice(STOCK_SYMBOLS), "wildcard"


def _direction_for_user(rng: random.Random, ticker: str, recent_losses: int) -> str:
    """Retail leans BULL by default; recent losers tilt further BULL (revenge)."""
    bull_p = 0.55 + (0.05 * min(recent_losses, 3))
    return "BULL" if rng.random() < bull_p else "BEAR"


def _calibrated_stars(rng: random.Random, true_skill: float, world: WorldState, user_id: str) -> int:
    """Confidence calibration drift. A user's stars track their recent outcome
    pattern, not just their latent skill: a WIN bumps the next-call stars up,
    a LOSS bumps them down. The drift is bounded so high-skill users stay
    well-calibrated and low-skill users stay overconfident.
    """
    base = rng.choices([1, 2, 3, 4, 5], weights=[20, 25, 25, 20, 10], k=1)[0]
    skill_adj = max(-2, min(2, round(true_skill * 1.0)))
    s = world.user_state.get(user_id) or {}
    streak = s.get("streak", [])
    if streak:
        last = streak[-1]
        if last == "WIN":
            s.setdefault("stars_offset", 0)
            s["stars_offset"] = min(2, s["stars_offset"] + 1)
        elif last == "LOSS":
            s.setdefault("stars_offset", 0)
            s["stars_offset"] = max(-2, s["stars_offset"] - 1)
    drift = (s.get("stars_offset") or 0)
    return max(1, min(5, base + skill_adj + drift))


def _on_cooldown(world: WorldState, user_id: str) -> bool:
    s = world.user_state.get(user_id)
    if not s:
        return False
    until = s.get("cooldown_until")
    return until is not None and until > world.sim_now


def _record_outcome(world: WorldState, user_id: str, outcome: str, symbol: str = "") -> None:
    """Update the per-user streak + per-ticker loss count. Three consecutive
    LOSSes triggers a 24h cooldown; per-ticker losses feed the loss-aversion
    /double-down pattern in `_ticker_for_user`.
    """
    s = world.user_state.setdefault(user_id, {
        "streak": [], "cooldown_until": None,
        "ticker_history": {}, "loss_tickers": {}, "stars_offset": 0,
    })
    s["streak"] = (s["streak"] + [outcome])[-5:]
    if outcome == "LOSS" and symbol:
        s["loss_tickers"][symbol] = s["loss_tickers"].get(symbol, 0) + 1
    if s["streak"][-3:] == ["LOSS", "LOSS", "LOSS"]:
        s["cooldown_until"] = world.sim_now + timedelta(hours=24)


def _recent_losses(world: WorldState, user_id: str) -> int:
    s = world.user_state.get(user_id)
    if not s:
        return 0
    return sum(1 for o in s["streak"] if o == "LOSS")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rng_for(world: WorldState, salt: str) -> random.Random:
    key = f"{world.tick_count}:{salt}:{world.sim_now.isoformat()}"
    seed = int(hashlib.sha256(key.encode()).hexdigest()[:12], 16)
    return random.Random(seed)


def _log_event(con, world: WorldState, kind: str, actor: str = "", payload: Optional[dict] = None, lens: str = "all") -> None:
    con.execute(
        """INSERT INTO sim_events (event_id, sim_ts, wall_ts, kind, actor, payload, lens)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            f"evt-{uuid.uuid4().hex[:16]}",
            world.sim_now,
            datetime.now(timezone.utc).replace(tzinfo=None),
            kind,
            actor,
            json.dumps(payload or {}, default=str),
            lens,
        ],
    )


def _make_persona(rng: random.Random) -> dict:
    first = rng.choice(FIRST_NAMES)
    last = rng.choice(LAST_NAMES)
    full = f"{first} {last}"
    persona_id = uuid.uuid4().hex
    user_id = str(uuid.UUID(int=int(hashlib.sha256(persona_id.encode()).hexdigest()[:32], 16)))
    channel = rng.choices(["unstop", "whatsapp_dark"], weights=[85, 15], k=1)[0]
    is_tier1 = rng.random() < 0.55
    city = rng.choice(TIER1_CITIES if is_tier1 else TIER2_CITIES)
    return dict(
        user_id=user_id,
        persona_id=persona_id,
        full_name=full,
        first_name=first,
        last_name=last,
        personal_email=f"{first.lower()}.{last.lower()}{rng.randint(10,99)}@gmail.com",
        college_email=None,
        phone_hash=hashlib.sha256(f"phone:{persona_id}".encode()).hexdigest(),
        device_fingerprint=str(uuid.UUID(int=rng.getrandbits(128))),
        city=city,
        city_tier="Tier-1" if is_tier1 else "Tier-2",
        device_type=rng.choices(["mobile", "desktop"], weights=[75, 25], k=1)[0],
        occupation="Student" if rng.random() < 0.45 else "Working Professional",
        age=rng.randint(19, 34),
        college=None,
        identity_confidence=1.0,  # single-source, by construction
        identity_flags=["sim_generated"],
        model_version="sim-v1.0.0",
        acquisition_source=channel,
        signup_time=None,  # filled below
        true_skill=rng.gauss(0.0, 1.0),
    )


# ---------------------------------------------------------------------------
# Tick
# ---------------------------------------------------------------------------

def tick(world: WorldState, *, advance_minutes: int = 60) -> dict:
    """Advance the world by `advance_minutes` synthetic minutes.

    Returns a counters dict summarizing what happened this tick.
    """
    counters = dict(joined=0, predictions=0, resolved=0, ghosted=0, watcher_fired=0)
    if not WAREHOUSE.exists():
        return counters

    rng_join = _rng_for(world, "join")
    rng_pred = _rng_for(world, "pred")
    rng_out = _rng_for(world, "out")

    new_sim_now = world.sim_now + timedelta(minutes=advance_minutes)

    con = duckdb.connect(str(WAREHOUSE), read_only=False)
    try:
        _ensure_table(con)

        # ---- 1. New joiners ----
        # 0–3 joiners per simulated hour, biased to mid-day.
        n_join = rng_join.choices([0, 1, 2, 3], weights=[20, 40, 30, 10], k=1)[0]
        for _ in range(n_join):
            p = _make_persona(rng_join)
            signup_time = world.sim_now + timedelta(
                minutes=rng_join.randint(0, max(1, advance_minutes - 1))
            )
            p["signup_time"] = signup_time
            con.execute(
                """INSERT INTO dim_user
                   (user_id, full_name, personal_email, college_email, phone_hash,
                    device_fingerprint, city, city_tier, device_type, occupation, age,
                    college, identity_confidence, identity_flags, model_version,
                    acquisition_source, signup_time, true_skill, _source_system)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [p["user_id"], p["full_name"], p["personal_email"], p["college_email"], p["phone_hash"],
                 p["device_fingerprint"], p["city"], p["city_tier"], p["device_type"], p["occupation"], p["age"],
                 p["college"], p["identity_confidence"], p["identity_flags"], p["model_version"],
                 p["acquisition_source"], p["signup_time"], p["true_skill"], "sim.world"],
            )
            con.execute(
                """INSERT INTO fact_acquisition
                   (acquisition_id, user_id, weekly_challenge_id, touchpoint_source,
                    utm_source, utm_campaign, touchpoint_at, _source_system)
                   VALUES (?, ?, NULL, ?, ?, NULL, ?, 'sim.world')""",
                [f"AQ-SIM-{p['user_id'][:12]}", p["user_id"], p["acquisition_source"],
                 p["acquisition_source"] if p["acquisition_source"] == "unstop" else None,
                 signup_time],
            )
            counters["joined"] += 1
            _log_event(con, world, "persona_joined",
                       actor=p["user_id"],
                       payload=dict(channel=p["acquisition_source"], city=p["city"],
                                    name=p["full_name"], tier=p["city_tier"]),
                       lens="growth")

        # ---- 2. Existing-user calls ----
        # Pick a random sample of active users (called in the last 7 sim days),
        # then filter out anyone on cooldown. The number of calls placed this
        # tick is scaled by the time-of-day rhythm.
        recent_cutoff = world.sim_now - timedelta(days=7)
        candidates = con.execute(
            """SELECT du.user_id, du.true_skill, du.occupation
               FROM dim_user du
               WHERE du.true_skill IS NOT NULL
                 AND du.signup_time IS NOT NULL
                 AND du.signup_time < ?
                 AND EXISTS (
                   SELECT 1 FROM fact_prediction p
                   WHERE p.user_id = du.user_id AND p.made_at >= ?
                 )
               ORDER BY RANDOM() LIMIT 80""",
            [world.sim_now, recent_cutoff],
        ).fetchall()
        # Drop cooldown users; they capitulated for the next 24h.
        candidates = [c for c in candidates if not _on_cooldown(world, c[0])]
        activity = _activity_multiplier(world.sim_now)
        base_target = rng_pred.randint(3, min(15, len(candidates) or 1))
        n_pred_target = max(1, min(len(candidates), int(round(base_target * activity))))

        # Leaderboard sprint: on Friday-afternoon close, the top quartile of
        # users by latent skill push out a second call this tick to defend
        # their rank before the weekly cutoff.
        sprint = _is_leaderboard_sprint(world.sim_now)
        sprint_set = set()
        if sprint and candidates:
            ranked = sorted(candidates, key=lambda c: float(c[1] or 0.0), reverse=True)
            sprint_set = {row[0] for row in ranked[: max(1, len(ranked) // 4)]}
            _log_event(con, world, "leaderboard_sprint", actor="market",
                       payload=dict(top_quartile=len(sprint_set), hour=world.sim_now.hour),
                       lens="growth")

        def _emit_call(user_id: str, true_skill: float, occupation: Optional[str], is_sprint_bonus: bool = False) -> None:
            ts = float(true_skill or 0.0)
            user_mu = 1500.0 + (ts * 100.0)  # synthetic mu from true_skill
            symbol, pick_reason = _ticker_for_user(rng_pred, world, user_id, occupation, user_mu=user_mu)
            recent_losses = _recent_losses(world, user_id)
            direction = _direction_for_user(rng_pred, symbol, recent_losses)
            stars = _calibrated_stars(rng_pred, ts, world, user_id)
            made_at = world.sim_now + timedelta(minutes=rng_pred.randint(0, max(1, advance_minutes - 1)))
            pred_id = str(uuid.UUID(int=rng_pred.getrandbits(128)))
            con.execute(
                """INSERT INTO fact_prediction
                   (prediction_id, user_id, stock_symbol, direction, confidence_stars,
                    made_at, outcome, pnl_points, accuracy_delta, resolved_at,
                    is_outcome_resolved, _source_system)
                   VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, FALSE, 'sim.world')""",
                [pred_id, user_id, symbol, direction, stars, made_at],
            )
            _record_call(world, user_id, symbol)
            # High-Gyaani calls become alpha calls that lower-mu users can shadow.
            if user_mu >= 1700:
                _record_alpha_call(world, symbol, direction)
            counters["predictions"] += 1
            payload = dict(
                symbol=symbol, direction=direction, stars=stars,
                true_skill=round(ts, 2), sector=SECTOR_OF.get(symbol, "other"),
                reason=pick_reason,
            )
            if symbol in PRE_IPO_TICKERS:
                payload["pre_ipo"] = True
            if recent_losses >= 2:
                payload["tilt"] = f"revenge_after_{recent_losses}_losses"
            if is_sprint_bonus:
                payload["sprint"] = True
            if user_mu >= 1700:
                payload["alpha"] = True
            _log_event(con, world, "prediction_made",
                       actor=user_id,
                       payload=payload,
                       lens="product")

        for user_id, true_skill, occupation in candidates[:n_pred_target]:
            _emit_call(user_id, true_skill, occupation)
        # Sprint bonus: each top-quartile user emits an additional call.
        if sprint_set:
            for user_id, true_skill, occupation in candidates:
                if user_id in sprint_set:
                    _emit_call(user_id, true_skill, occupation, is_sprint_bonus=True)

        # ---- 2b. Sentiment cascade. Periodically a news event clusters
        # ~6-10 calls on a single ticker within the same tick. Visible in
        # the event stream as a `news_cascade` event followed by a
        # cluster of `prediction_made` events on that symbol.
        if candidates and rng_pred.random() < 0.18:
            cascade_symbol = rng_pred.choice(STOCK_SYMBOLS)
            cascade_dir = rng_pred.choices(["BULL", "BEAR"], weights=[60, 40], k=1)[0]
            cascade_size = rng_pred.randint(6, 10)
            cascade_users = [c for c in candidates if c[0] not in {
                row[0] for row in candidates[:n_pred_target]
            }][:cascade_size]
            if cascade_users:
                _log_event(con, world, "news_cascade", actor="market",
                           payload=dict(
                               symbol=cascade_symbol,
                               sector=SECTOR_OF.get(cascade_symbol, "other"),
                               direction=cascade_dir,
                               users_affected=len(cascade_users),
                           ),
                           lens="product")
                # Record so subsequent calls within ~2 hours pick this up
                # via the FOMO follow-on branch in `_ticker_for_user`.
                world.recent_cascade = dict(
                    symbol=cascade_symbol,
                    direction=cascade_dir,
                    until=world.sim_now + timedelta(hours=2),
                )
                for user_id, true_skill, _occ in cascade_users:
                    pred_id = str(uuid.UUID(int=rng_pred.getrandbits(128)))
                    made_at = world.sim_now + timedelta(minutes=rng_pred.randint(0, max(1, advance_minutes - 1)))
                    stars = rng_pred.choices([3, 4, 5], weights=[30, 50, 20], k=1)[0]
                    con.execute(
                        """INSERT INTO fact_prediction
                           (prediction_id, user_id, stock_symbol, direction, confidence_stars,
                            made_at, outcome, pnl_points, accuracy_delta, resolved_at,
                            is_outcome_resolved, _source_system)
                           VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, FALSE, 'sim.world')""",
                        [pred_id, user_id, cascade_symbol, cascade_dir, stars, made_at],
                    )
                    _record_call(world, user_id, cascade_symbol)
                    counters["predictions"] += 1

        # ---- 3. Outcome resolutions ----
        # Any prediction whose made_at + 5d has passed resolves now.
        to_resolve = con.execute(
            """SELECT p.prediction_id, p.user_id, p.made_at, du.true_skill, p.stock_symbol, p.direction
               FROM fact_prediction p
               JOIN dim_user du ON du.user_id = p.user_id
               WHERE p.is_outcome_resolved = FALSE
                 AND p.made_at + INTERVAL '5 days' <= ?
               LIMIT 200""",
            [new_sim_now],
        ).fetchall()
        for pred_id, user_id, made_at, true_skill, symbol, direction in to_resolve:
            ts = float(true_skill or 0.0)
            p_win = max(0.22, min(0.62, 0.42 + ts * 0.10))
            p_draw = 0.08
            p_loss = 1.0 - p_win - p_draw
            outcome = rng_out.choices(["WIN", "LOSS", "DRAW"], weights=[p_win, p_loss, p_draw], k=1)[0]
            pnl = {"WIN": rng_out.uniform(0.5, 5.0),
                   "LOSS": -rng_out.uniform(0.5, 4.0),
                   "DRAW": 0.0}[outcome]
            resolved_at = made_at + timedelta(days=5)
            con.execute(
                """UPDATE fact_prediction SET outcome=?, pnl_points=?, accuracy_delta=?,
                                              resolved_at=?, is_outcome_resolved=TRUE
                   WHERE prediction_id = ?""",
                [outcome, round(pnl, 3), round(rng_out.uniform(-0.05, 0.05), 4),
                 resolved_at, pred_id],
            )
            counters["resolved"] += 1
            # Track the streak + per-ticker losses. Three consecutive LOSSes
            # triggers a 24h cooldown (capitulation). Per-ticker losses feed
            # the loss-aversion / double-down branch in _ticker_for_user.
            prior = world.user_state.get(user_id, {}).get("streak", [])
            _record_outcome(world, user_id, outcome, symbol=symbol)
            new_streak = world.user_state[user_id]["streak"]
            if new_streak[-3:] == ["LOSS", "LOSS", "LOSS"] and prior[-3:] != ["LOSS", "LOSS", "LOSS"]:
                _log_event(con, world, "user_cooled_off", actor=user_id,
                           payload=dict(last_ticker=symbol, streak=new_streak[-3:],
                                        cooldown_hours=24),
                           lens="cs")
            if rng_out.random() < 0.3:  # log a sample, not every one
                _log_event(con, world, "outcome_resolved",
                           actor=user_id,
                           payload=dict(symbol=symbol, direction=direction, outcome=outcome),
                           lens="product")

        # ---- 4. Tick metadata ----
        world.sim_now = new_sim_now
        world.tick_count += 1
        _log_event(con, world, "tick_complete", actor="world",
                   payload=dict(counters=counters, sim_now=str(new_sim_now),
                                tick_count=world.tick_count),
                   lens="all")
    finally:
        con.close()

    return counters
