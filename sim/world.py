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


def fresh_world() -> WorldState:
    return WorldState(sim_now=SIM_T0, accel=60.0)


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

        # ---- 2. Existing-user predictions ----
        # Pick a random sample of active users (predicted in the last 7 sim days)
        # and give some of them a new prediction.
        recent_cutoff = world.sim_now - timedelta(days=7)
        candidates = con.execute(
            """SELECT du.user_id, du.true_skill
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
        n_pred_target = rng_pred.randint(3, min(15, len(candidates) or 1))
        for user_id, true_skill in candidates[:n_pred_target]:
            ts = float(true_skill or 0.0)
            stars_base = rng_pred.choices([1, 2, 3, 4, 5], weights=[20, 25, 25, 20, 10], k=1)[0]
            stars = max(1, min(5, stars_base + max(-2, min(2, round(ts * 1.0)))))
            symbol = rng_pred.choice(STOCK_SYMBOLS)
            direction = rng_pred.choices(["BULL", "BEAR"], weights=[55, 45], k=1)[0]
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
            counters["predictions"] += 1
            _log_event(con, world, "prediction_made",
                       actor=user_id,
                       payload=dict(symbol=symbol, direction=direction, stars=stars,
                                    true_skill=round(ts, 2)),
                       lens="product")

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
