"""Synthetic data generator.

Two stages, deterministic by seed:

  python3 generate.py --step=personas   # samples 2k personas from Nemotron, derives keys
  python3 generate.py --step=events     # writes the five raw/* sources + outcomes_week01

Personas are the ground truth. Events are derived from personas; the identity
fuzz baked in here is the test the resolver must pass.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import random
import re
import sys
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

REPO = Path(__file__).resolve().parent
DATA_DIR = REPO / "data"
RAW_DIR = REPO / "raw"

# Deterministic root seed. Sub-streams use offsets so changing one stream
# doesn't perturb the others (numpy-style "splittable" RNG by hand).
SEED = 42

N_PERSONAS = 2000
WEEK_OF = "2024-W01"
WEEKLY_CHALLENGE_ID = "WC-2024-W01"

# Channel mix:
#   15% WhatsApp dark — single-source (only backend signup, no UTM, no Klaviyo)
#   85% Unstop — multi-source with identity fuzz applied (70/20/10 trivial/fuzzy/shared-device)
N_DARK = 300                # 15% of 2000
N_UNSTOP = N_PERSONAS - N_DARK  # 1700
N_TRIVIAL = 1190            # 70% of 1700
N_FUZZY = 340               # 20% of 1700
N_SHARED_DEVICE = 170       # 10% of 1700 — 85 pairs

# Tier-1 cities — the brief's definition. Tier-2 = everything else.
TIER1_CITIES = {"Mumbai", "Delhi", "Bengaluru", "Bangalore", "Hyderabad", "Chennai", "Pune"}

COLLEGES = ["iitb", "iitd", "iitk", "bits-pilani", "vit", "manipal", "srm", "nit-trichy", "dtu", "iiit-hyd"]

EMAIL_PROVIDERS_WEIGHTED = (
    ["gmail.com"] * 60
    + ["yahoo.com"] * 15
    + ["outlook.com"] * 10
    + ["rediffmail.com"] * 10
    + ["hotmail.com"] * 5
)

STOCK_SYMBOLS = [
    "RELIANCE", "TCS", "INFY", "HDFC", "WIPRO",
    "ICICIBANK", "BAJFINANCE", "SBIN", "HCLTECH", "ITC",
]

# IST is UTC+5:30.
IST = timezone(timedelta(hours=5, minutes=30))
WEEK_START_IST = datetime(2024, 1, 1, 0, 0, 0, tzinfo=IST)  # Mon


# ---------------------------------------------------------------------------
# Personas
# ---------------------------------------------------------------------------

def _slug(s: str) -> str:
    """Lowercase ASCII slug for email local parts."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "", s).lower()
    return s


def _extract_name(persona_text: str) -> tuple[str, str]:
    """Pull first/last from a `persona` paragraph like 'Bhai Shekh, a 23-year-old ...'."""
    if not persona_text:
        return ("Anon", "User")
    head = persona_text.split(",", 1)[0].strip()
    # Remove honorifics that Nemotron sometimes prepends.
    head = re.sub(r"^(Mr|Mrs|Ms|Dr|Shri|Smt|Bhai|Devi)\b\.?\s+", "", head, flags=re.IGNORECASE)
    parts = [p for p in re.split(r"\s+", head) if p]
    if not parts:
        return ("Anon", "User")
    if len(parts) == 1:
        return (parts[0], "User")
    return (parts[0], parts[-1])


def _device_type(occupation: str, rng: random.Random) -> str:
    occ = (occupation or "").lower()
    if "student" in occ:
        return rng.choices(["mobile", "desktop"], weights=[85, 15], k=1)[0]
    if any(k in occ for k in ["engineer", "manager", "analyst", "consultant", "developer"]):
        return rng.choices(["mobile", "desktop"], weights=[60, 40], k=1)[0]
    return rng.choices(["mobile", "desktop"], weights=[70, 30], k=1)[0]


def _city_tier(city: str) -> str:
    if not city:
        return "Tier-2"
    return "Tier-1" if any(t in city for t in TIER1_CITIES) else "Tier-2"


def _load_nemotron_sample(n: int, seed: int) -> list[dict]:
    """Stream the en_IN split until we have n usable personas (with a parseable name).

    Streaming avoids materialising the full split.
    """
    from datasets import load_dataset

    ds = load_dataset("nvidia/Nemotron-Personas-India", split="en_IN", streaming=True)
    out: list[dict] = []
    # Take more than n so we can discard rows with unparseable names while
    # remaining deterministic.
    take = int(n * 1.2)
    for i, rec in enumerate(itertools.islice(ds, take)):
        out.append(rec)
        if len(out) >= take:
            break
    rng = random.Random(seed)
    rng.shuffle(out)
    return out[:n]


def build_personas() -> pd.DataFrame:
    rng_personas = random.Random(SEED + 1)
    rng_devices = random.Random(SEED + 2)
    rng_emails = random.Random(SEED + 3)
    rng_patterns = random.Random(SEED + 4)

    print(f"Loading {N_PERSONAS} personas from nvidia/Nemotron-Personas-India en_IN ...", file=sys.stderr)
    raw = _load_nemotron_sample(N_PERSONAS, SEED + 1)
    print(f"  got {len(raw)} raw records", file=sys.stderr)

    rows: list[dict] = []
    for idx, rec in enumerate(raw):
        first, last = _extract_name(rec.get("persona") or rec.get("professional_persona") or "")
        city = rec.get("district") or rec.get("state") or "Unknown"
        occupation = rec.get("occupation") or "Unknown"
        age = rec.get("age")
        try:
            age = int(age) if age is not None else None
        except (TypeError, ValueError):
            age = None

        # Channel + identity-pattern bucketing — deterministic by position.
        #
        #   idx ∈ [0, N_DARK)                           → whatsapp_dark, no Unstop row, no Klaviyo
        #   idx ∈ [N_DARK, N_DARK+N_TRIVIAL)            → unstop, trivial email match
        #   idx ∈ [..., N_DARK+N_TRIVIAL+N_FUZZY)       → unstop, fuzzy (name typo, different email)
        #   idx ∈ [...]                                 → unstop, shared_device pair
        boundaries = (N_DARK, N_DARK + N_TRIVIAL, N_DARK + N_TRIVIAL + N_FUZZY)
        if idx < boundaries[0]:
            channel = "whatsapp_dark"
            pattern = "dark"
            pair_partner = None
        elif idx < boundaries[1]:
            channel = "unstop"
            pattern = "trivial"
            pair_partner = None
        elif idx < boundaries[2]:
            channel = "unstop"
            pattern = "fuzzy"
            pair_partner = None
        else:
            channel = "unstop"
            offset = idx - boundaries[2]
            pair_idx = offset // 2
            pattern = f"shared_device:pair-{pair_idx}"
            partner_offset = 1 if offset % 2 == 0 else -1
            pair_partner = idx + partner_offset

        # Stable persona_id derived from Nemotron uuid if present, else position.
        persona_id = rec.get("uuid") or f"persona-{idx:05d}"
        # Ensure no dashes form invalid UUIDs downstream.
        persona_id = persona_id.replace("-", "")

        college = rng_personas.choice(COLLEGES)
        first_slug = _slug(first) or f"user{idx}"
        last_slug = _slug(last) or "x"
        college_email = f"{first_slug}.{last_slug}@{college}.ac.in"

        # device_fingerprint: shared for the 100 pairs; unique otherwise.
        if pattern.startswith("shared_device:"):
            device_fingerprint = f"device-pair-{pattern.split('pair-')[1]}"
        else:
            device_fingerprint = str(uuid.UUID(int=rng_devices.getrandbits(128)))

        # personal_email per pattern.
        if pattern == "fuzzy":
            # Different local part — random digits, possibly a different first-name slug.
            two_digits = f"{rng_emails.randint(10, 99)}"
            provider = rng_emails.choice(EMAIL_PROVIDERS_WEIGHTED)
            personal_email = f"{first_slug}{two_digits}@{provider}"
        else:
            # Trivial: same first.last, gmail (per brief — "domain swapped to Gmail").
            personal_email = f"{first_slug}.{last_slug}@gmail.com"

        device_type = _device_type(occupation, rng_devices)
        phone_hash = hashlib.sha256(f"phone:{persona_id}:{SEED}".encode()).hexdigest()

        rows.append(
            dict(
                persona_id=persona_id,
                idx=idx,
                first_name=first,
                last_name=last,
                full_name=f"{first} {last}".strip(),
                age=age,
                occupation=occupation,
                state=rec.get("state"),
                district=rec.get("district"),
                city=city,
                city_tier=_city_tier(city),
                college=college,
                college_email=college_email,
                personal_email=personal_email,
                device_fingerprint=device_fingerprint,
                device_type=device_type,
                phone_hash=phone_hash,
                acquisition_channel=channel,  # "unstop" | "whatsapp_dark"
                identity_pattern=pattern,
                pair_partner_idx=pair_partner,
                model_version="generator-v1.0.0",
            )
        )

    df = pd.DataFrame(rows)
    return df


def step_personas() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df = build_personas()
    out = DATA_DIR / "personas.parquet"
    df.to_parquet(out, index=False)
    print(f"wrote {out}  rows={len(df)}  unique_devices={df['device_fingerprint'].nunique()}", file=sys.stderr)

    # Stats — these are the ground-truth knobs we'll later verify against.
    by_pattern = df["identity_pattern"].apply(lambda p: "shared_device" if p.startswith("shared_device:") else p).value_counts()
    print("identity_pattern counts:", dict(by_pattern), file=sys.stderr)
    print("city_tier counts:", dict(df["city_tier"].value_counts()), file=sys.stderr)


# ---------------------------------------------------------------------------
# Event generators (Step 2 — five sources + deferred outcomes)
# ---------------------------------------------------------------------------

def _utc(dt: datetime) -> str:
    """RFC3339-ish UTC string."""
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _registration_time(rng: random.Random) -> datetime:
    """Mon-Tue, weighted toward Mon 9am-2pm IST."""
    hour_weights = [0] * 24
    # Mon
    for h in range(9, 14):
        hour_weights[h] = 8  # peak window
    for h in range(7, 21):
        if hour_weights[h] == 0:
            hour_weights[h] = 2
    mon_total = sum(hour_weights)

    # 70% Mon, 30% Tue. Tue more diffuse.
    is_mon = rng.random() < 0.7
    day_offset = 0 if is_mon else 1
    if is_mon:
        hour = rng.choices(range(24), weights=hour_weights, k=1)[0]
    else:
        hour = rng.choices(range(24), weights=[2 if 8 <= h <= 20 else 0 for h in range(24)], k=1)[0]
    minute = rng.randint(0, 59)
    second = rng.randint(0, 59)
    return WEEK_START_IST + timedelta(days=day_offset, hours=hour, minutes=minute, seconds=second)


def write_unstop_csv(personas: pd.DataFrame) -> Path:
    rng = random.Random(SEED + 10)
    out = RAW_DIR / "unstop_week01.csv"
    fieldnames = [
        "unstop_id", "full_name", "college_email", "college_name", "city",
        "registration_time", "weekly_challenge_id", "utm_source", "utm_campaign",
        "browser_fingerprint",  # tracking-pixel artifact; needed for fuzzy match
    ]
    # Only Unstop-channel personas appear here. WhatsApp dark users are
    # invisible to this source by design.
    unstop_personas = personas[personas["acquisition_channel"] == "unstop"]
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for _, p in unstop_personas.iterrows():
            full_name = p["full_name"]
            # 20% fuzzy users: introduce a name typo in Unstop. The backend
            # still has the canonical name.
            if p["identity_pattern"] == "fuzzy" and rng.random() < 1.0:
                style = rng.choice(["swap", "middle_initial"])
                if style == "swap":
                    full_name = f"{p['last_name']} {p['first_name']}".strip()
                else:
                    mid = chr(ord("A") + rng.randint(0, 25))
                    full_name = f"{p['first_name']} {mid}. {p['last_name']}".strip()
            reg_time = _registration_time(rng)
            w.writerow(dict(
                unstop_id=f"UN-{int(p['idx']):05d}",
                full_name=full_name,
                college_email=p["college_email"],
                college_name=p["college"].upper(),
                city=p["city"],
                registration_time=_utc(reg_time),
                weekly_challenge_id=WEEKLY_CHALLENGE_ID,
                utm_source="unstop",
                utm_campaign="weekly-challenge-jan-w1",
                browser_fingerprint=p["device_fingerprint"],
            ))
    return out


def _write_ndjson(path: Path, rows: Iterable[dict]) -> int:
    n = 0
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
            n += 1
    return n


def gen_backend_events(personas: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """Returns (current_events, deferred_outcomes)."""
    rng_signup = random.Random(SEED + 11)
    rng_predict = random.Random(SEED + 12)
    rng_outcome = random.Random(SEED + 13)
    rng_challenge = random.Random(SEED + 14)

    events: list[dict] = []
    outcomes: list[dict] = []

    for _, p in personas.iterrows():
        canonical_user_id = str(uuid.UUID(int=int(hashlib.sha256(p["persona_id"].encode()).hexdigest()[:32], 16)))

        # user_signup. Mon-Wed within the week.
        signup_time = WEEK_START_IST + timedelta(
            days=rng_signup.randint(0, 2),
            hours=rng_signup.randint(8, 22),
            minutes=rng_signup.randint(0, 59),
        )
        platform = "android" if p["device_type"] == "mobile" else rng_signup.choices(["web", "ios"], weights=[70, 30], k=1)[0]
        events.append(dict(
            event_type="user_signup",
            user_id=canonical_user_id,
            personal_email=p["personal_email"],
            full_name=p["full_name"],
            phone_hash=p["phone_hash"],
            device_fingerprint=p["device_fingerprint"],
            signup_time=_utc(signup_time),
            referral_code=None,
            platform=platform,
            acquisition_channel=p["acquisition_channel"],  # "unstop" | "whatsapp_dark"
        ))

        # challenge_signup — 92% of Unstop users sign up for the challenge in
        # the app within 6h of their Unstop registration. The other 8% sign
        # up later or never. (For our universe all personas are Unstop users.)
        if rng_challenge.random() < 0.92:
            challenge_time = signup_time + timedelta(
                hours=rng_challenge.randint(0, 5),
                minutes=rng_challenge.randint(0, 59),
            )
            events.append(dict(
                event_type="challenge_signup",
                user_id=canonical_user_id,
                weekly_challenge_id=WEEKLY_CHALLENGE_ID,
                signup_time=_utc(challenge_time),
            ))
        else:
            challenge_time = None

        # predictions — power-law-ish: 30% make 0 (ghosts), 40% make 1-2,
        # 20% make 3-5, 10% make 5-10.
        bucket = rng_predict.choices([0, 1, 2, 3], weights=[30, 40, 20, 10], k=1)[0]
        if bucket == 0:
            n_pred = 0
        elif bucket == 1:
            n_pred = rng_predict.randint(1, 2)
        elif bucket == 2:
            n_pred = rng_predict.randint(3, 5)
        else:
            n_pred = rng_predict.randint(5, 10)

        for _ in range(n_pred):
            # made_at within 7 days of signup; if no challenge_signup, still
            # spread predictions later in the week.
            anchor = challenge_time if challenge_time else signup_time
            made_at = anchor + timedelta(
                hours=rng_predict.randint(0, 24 * 6),
                minutes=rng_predict.randint(0, 59),
            )
            prediction_id = str(uuid.UUID(int=rng_predict.getrandbits(128)))
            events.append(dict(
                event_type="prediction_made",
                user_id=canonical_user_id,
                prediction_id=prediction_id,
                stock_symbol=rng_predict.choice(STOCK_SYMBOLS),
                direction=rng_predict.choices(["BULL", "BEAR"], weights=[55, 45], k=1)[0],
                confidence_stars=rng_predict.randint(1, 5),
                made_at=_utc(made_at),
            ))

            # Deferred outcome: resolved_at = made_at + 5 days (the brief's
            # deferred-join pattern). Goes to a separate file.
            resolved_at = made_at + timedelta(days=5)
            outcome = rng_outcome.choices(["WIN", "LOSS", "DRAW"], weights=[42, 50, 8], k=1)[0]
            pnl = {"WIN": rng_outcome.uniform(0.5, 5.0), "LOSS": -rng_outcome.uniform(0.5, 4.0), "DRAW": 0.0}[outcome]
            outcomes.append(dict(
                event_type="prediction_outcome",
                prediction_id=prediction_id,
                user_id=canonical_user_id,
                outcome=outcome,
                pnl_points=round(pnl, 3),
                accuracy_delta=round(rng_outcome.uniform(-0.05, 0.05), 4),
                resolved_at=_utc(resolved_at),
            ))

    return events, outcomes


def gen_posthog(personas: pd.DataFrame) -> list[dict]:
    """PostHog frontend events. 15% of users' sessions never identify."""
    rng = random.Random(SEED + 20)
    events: list[dict] = []

    for _, p in personas.iterrows():
        anon_id = str(uuid.UUID(int=rng.getrandbits(128)))
        never_identifies = rng.random() < 0.15

        canonical_user_id = str(uuid.UUID(int=int(hashlib.sha256(p["persona_id"].encode()).hexdigest()[:32], 16)))

        # Each user has 2-6 sessions. Within each session, 3-8 events.
        n_sessions = rng.randint(2, 6)
        for s_idx in range(n_sessions):
            session_id = str(uuid.UUID(int=rng.getrandbits(128)))
            # Sessions spread across the week.
            base = WEEK_START_IST + timedelta(
                days=rng.randint(0, 6),
                hours=rng.randint(8, 22),
                minutes=rng.randint(0, 59),
            )
            n_evt = rng.randint(3, 8)
            funnel = ["$pageview", "challenge_page_view", "challenge_cta_clicked", "signup_modal_opened", "signup_completed"]
            for e_idx in range(n_evt):
                ev = funnel[e_idx] if e_idx < len(funnel) else "$pageview"
                # If never_identifies, distinct_id == anon_id forever.
                # If identifies, the signup_completed event flips distinct_id to the user_id.
                if never_identifies:
                    distinct_id = anon_id
                else:
                    distinct_id = canonical_user_id if e_idx >= 4 else anon_id

                events.append(dict(
                    event_type=ev,
                    anonymous_id=anon_id,
                    distinct_id=distinct_id,
                    session_id=session_id,
                    timestamp=_utc(base + timedelta(seconds=e_idx * rng.randint(20, 180))),
                    properties=dict(
                        current_url=f"/challenge?utm_source=unstop&s={s_idx}",
                        utm_source="unstop" if s_idx == 0 else rng.choice(["unstop", "organic", "direct"]),
                    ),
                ))

        # Shared-device pairs: force overlapping sessions in the same 30-min
        # window so Pass 3 has overlap to detect. Use a deterministic
        # late-week timestamp tied to the pair index.
        if isinstance(p["identity_pattern"], str) and p["identity_pattern"].startswith("shared_device:"):
            pair_idx = int(p["identity_pattern"].split("pair-")[1])
            overlap_base = WEEK_START_IST + timedelta(
                days=4 + (pair_idx % 3),
                hours=14,
                minutes=(pair_idx * 7) % 30,
            )
            session_id = f"shared-session-{pair_idx}-{p['idx']}"
            for e_idx in range(3):
                events.append(dict(
                    event_type="$pageview",
                    anonymous_id=anon_id,
                    distinct_id=canonical_user_id,
                    session_id=session_id,
                    timestamp=_utc(overlap_base + timedelta(minutes=e_idx * 4)),
                    properties=dict(current_url="/portfolio", shared_device=True),
                ))

    return events


def gen_klaviyo(personas: pd.DataFrame) -> list[dict]:
    """Email funnel. 5% of email_opened events have timestamp BEFORE email_sent (clock skew).

    Only generated for personas with a known channel (Unstop). WhatsApp-dark
    users have no email-funnel touchpoint by design.
    """
    rng = random.Random(SEED + 30)
    out: list[dict] = []
    campaign_id = "WC-JAN-W1"
    visible_personas = personas[personas["acquisition_channel"] == "unstop"]

    for _, p in visible_personas.iterrows():
        klaviyo_id = f"KL-{p['persona_id'][:10]}"
        sent_at = WEEK_START_IST + timedelta(
            days=rng.randint(0, 1),
            hours=rng.randint(9, 18),
            minutes=rng.randint(0, 59),
        )
        out.append(dict(
            event_type="email_sent",
            email=p["personal_email"],
            klaviyo_profile_id=klaviyo_id,
            campaign_id=campaign_id,
            timestamp=_utc(sent_at),
        ))

        # Open rate ~ 40%.
        if rng.random() < 0.40:
            # 5% of opens have timestamp BEFORE the sent event (clock skew).
            if rng.random() < 0.05:
                opened_at = sent_at - timedelta(seconds=rng.randint(30, 90))
            else:
                opened_at = sent_at + timedelta(
                    minutes=rng.randint(2, 60 * 24),
                )
            out.append(dict(
                event_type="email_opened",
                email=p["personal_email"],
                klaviyo_profile_id=klaviyo_id,
                campaign_id=campaign_id,
                timestamp=_utc(opened_at),
            ))

            # Click rate of opens ~ 20%.
            if rng.random() < 0.20:
                clicked_at = opened_at + timedelta(seconds=rng.randint(10, 600))
                out.append(dict(
                    event_type="email_clicked",
                    email=p["personal_email"],
                    klaviyo_profile_id=klaviyo_id,
                    campaign_id=campaign_id,
                    timestamp=_utc(clicked_at),
                ))

    return out


def gen_ga4(personas: pd.DataFrame, n_sessions: int = 3500) -> list[dict]:
    """Anonymous GA4 sessions — no user_id link. Some land on /challenge organically."""
    rng = random.Random(SEED + 40)
    out: list[dict] = []
    for _ in range(n_sessions):
        start = WEEK_START_IST + timedelta(
            days=rng.randint(0, 6),
            hours=rng.randint(0, 23),
            minutes=rng.randint(0, 59),
        )
        duration = rng.randint(20, 60 * 10)
        out.append(dict(
            ga4_client_id=str(uuid.UUID(int=rng.getrandbits(128))),
            session_id=str(uuid.UUID(int=rng.getrandbits(128))),
            session_start=_utc(start),
            session_end=_utc(start + timedelta(seconds=duration)),
            device_category=rng.choices(["mobile", "desktop", "tablet"], weights=[68, 28, 4], k=1)[0],
            traffic_source=rng.choices(["organic", "direct", "referral", "paid_search"], weights=[40, 30, 15, 15], k=1)[0],
            landing_page=rng.choices(["/challenge", "/", "/signup"], weights=[40, 35, 25], k=1)[0],
            country="IN",
            city=rng.choice(list(TIER1_CITIES) + ["Jaipur", "Lucknow", "Kanpur", "Indore", "Bhopal", "Surat"]),
        ))
    return out


def step_events() -> None:
    if not (DATA_DIR / "personas.parquet").exists():
        print("ERROR: data/personas.parquet missing. Run `make personas` first.", file=sys.stderr)
        sys.exit(2)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    personas = pd.read_parquet(DATA_DIR / "personas.parquet")
    print(f"personas loaded: {len(personas)} rows", file=sys.stderr)

    # 1. Unstop
    path = write_unstop_csv(personas)
    print(f"wrote {path}  rows={sum(1 for _ in path.open()) - 1}", file=sys.stderr)

    # 2. Backend (split into current events vs deferred outcomes)
    backend, outcomes = gen_backend_events(personas)
    n = _write_ndjson(RAW_DIR / "backend_events.ndjson", backend)
    print(f"wrote raw/backend_events.ndjson  events={n}", file=sys.stderr)
    n = _write_ndjson(RAW_DIR / "outcomes_week01.ndjson", outcomes)
    print(f"wrote raw/outcomes_week01.ndjson  outcomes={n}  (deferred join, resolved_at = made_at + 5d)", file=sys.stderr)

    # 3. PostHog
    posthog = gen_posthog(personas)
    n = _write_ndjson(RAW_DIR / "posthog_events.ndjson", posthog)
    print(f"wrote raw/posthog_events.ndjson  events={n}", file=sys.stderr)

    # 4. Klaviyo
    klaviyo = gen_klaviyo(personas)
    n = _write_ndjson(RAW_DIR / "klaviyo_events.ndjson", klaviyo)
    print(f"wrote raw/klaviyo_events.ndjson  events={n}", file=sys.stderr)

    # 5. GA4
    ga4 = gen_ga4(personas)
    n = _write_ndjson(RAW_DIR / "ga4_sessions.ndjson", ga4)
    print(f"wrote raw/ga4_sessions.ndjson  sessions={n}", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="IndiaStox weekend prototype synthetic-data generator")
    parser.add_argument("--step", choices=["personas", "events", "all"], required=True)
    args = parser.parse_args()

    if args.step in ("personas", "all"):
        step_personas()
    if args.step in ("events", "all"):
        step_events()


if __name__ == "__main__":
    main()
