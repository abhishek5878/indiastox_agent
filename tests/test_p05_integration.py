"""Pytest tests for P0.5 — substrate-into-events wiring.

Verifies the code-path wiring without requiring a regenerated warehouse:
  - _make_persona (sim/world.py) produces archetype_slug + archetype-driven
    true_skill matching the canonical hash mapping.
  - generate.py imports substrate symbols and bumps model_version.
  - gen_backend_events is callable with a small synthetic personas frame
    and exercises the full substrate path (init_user_state →
    compose_all_layers → apply_event).
  - The new _pick_ticker_biased helper produces non-uniform results when
    given non-uniform bias maps.

Warehouse-level tests (archetype-stratified ghost rates) live elsewhere;
they require `make all` to have run.
"""
from __future__ import annotations

import random
from datetime import datetime

import pandas as pd

from sim.archetypes import ARCHETYPES, archetype_by_slug, archetype_for_persona
from sim.world import _make_persona


def test_world_make_persona_has_archetype_slug() -> None:
    rng = random.Random(42)
    p = _make_persona(rng)
    assert "archetype_slug" in p
    assert p["archetype_slug"] in {a.slug for a in ARCHETYPES}


def test_world_make_persona_archetype_matches_hash() -> None:
    rng = random.Random(42)
    p = _make_persona(rng)
    expected = archetype_for_persona(p["persona_id"]).slug
    assert p["archetype_slug"] == expected


def test_world_make_persona_true_skill_matches_archetype_distribution() -> None:
    """Across 2k synthetic make_persona draws, the empirical mean per
    archetype should be within 4σ/√n of its true_skill_mean."""
    import math
    import statistics

    samples_per_arch: dict[str, list[float]] = {a.slug: [] for a in ARCHETYPES}
    for i in range(2000):
        rng = random.Random(i)
        p = _make_persona(rng)
        samples_per_arch[p["archetype_slug"]].append(p["true_skill"])

    for arch in ARCHETYPES:
        sample = samples_per_arch[arch.slug]
        if len(sample) < 30:
            continue
        empirical_mean = statistics.fmean(sample)
        tolerance = 4 * arch.true_skill_std / math.sqrt(len(sample))
        assert abs(empirical_mean - arch.true_skill_mean) < tolerance, (
            f"{arch.slug}: empirical={empirical_mean:.3f} "
            f"expected={arch.true_skill_mean:.3f} ±{tolerance:.3f}"
        )


def test_generate_imports_substrate() -> None:
    """generate.py must successfully import the substrate-consumer symbols.
    Catches a circular-import or missing-symbol bug without running the
    heavy Nemotron loader."""
    import generate

    for sym in (
        "archetype_for_persona",
        "sample_initial_true_skill",
        "compose_all_layers",
        "init_user_state",
        "apply_event",
        "CallMadeEvent",
        "OutcomeResolvedEvent",
    ):
        assert hasattr(generate, sym), f"generate.py missing import: {sym}"


def test_generate_model_version_bumped() -> None:
    from pathlib import Path

    src = Path("generate.py").read_text()
    assert 'model_version="generator-v1.1.0"' in src


def test_pick_ticker_biased_respects_bias() -> None:
    """A 10x sector bias on 'IT' should produce visibly more IT picks
    than uniform on 1000 draws."""
    from generate import _pick_ticker_biased, SECTOR_OF

    rng = random.Random(42)
    biased_picks = [_pick_ticker_biased(rng, (("IT", 10.0),), ()) for _ in range(1000)]
    biased_it = sum(1 for t in biased_picks if SECTOR_OF.get(t) == "IT")

    rng = random.Random(42)
    uniform_picks = [_pick_ticker_biased(rng, (), ()) for _ in range(1000)]
    uniform_it = sum(1 for t in uniform_picks if SECTOR_OF.get(t) == "IT")

    assert biased_it > uniform_it * 1.5, (
        f"biased IT picks ({biased_it}) should clearly exceed uniform ({uniform_it})"
    )


def test_gen_backend_events_substrate_driven_smoke() -> None:
    """End-to-end smoke: a tiny synthetic personas frame produces events
    via the substrate path. Verifies no import errors, no exceptions, and
    that the output events carry archetype_slug.
    """
    from generate import gen_backend_events

    rows = []
    # Pick 4 personas with stable hash-derived ids; archetype_slug is
    # filled the same way build_personas would set it.
    for i in range(4):
        pid = f"persona-test-{i:05d}"
        rows.append(dict(
            persona_id=pid,
            idx=i,
            first_name="Test", last_name="User",
            full_name="Test User",
            age=25, occupation="Student", state="MH", district="Mumbai",
            city="Mumbai", city_tier="Tier-1",
            college="iit-bombay", college_email=f"test{i}@iitb.ac.in",
            personal_email=f"test{i}@gmail.com",
            device_fingerprint=f"dev-{i}",
            device_type="mobile",
            phone_hash=f"phone-{i}",
            acquisition_channel="unstop",
            identity_pattern="trivial",
            pair_partner_idx=None,
            true_skill=0.0,
            archetype_slug=archetype_for_persona(pid).slug,
            model_version="generator-v1.1.0",
        ))
    df = pd.DataFrame(rows)

    events, outcomes = gen_backend_events(df)
    assert len(events) > 0
    signups = [e for e in events if e["event_type"] == "user_signup"]
    assert len(signups) == 4
    for s in signups:
        assert s.get("archetype_slug") in {a.slug for a in ARCHETYPES}


def test_gen_backend_events_ghost_archetype_makes_fewer_predictions() -> None:
    """Aggregate signal: many ghost-risk-junior personas should produce
    fewer prediction events per persona than many alpha-generator personas.
    This is the load-bearing claim — substrate drives event behavior.
    """
    from generate import gen_backend_events

    def _build_for_archetype(slug: str, n: int) -> pd.DataFrame:
        rows = []
        # Find n persona_ids that hash to this archetype.
        i = 0
        found = 0
        while found < n:
            pid = f"persona-{slug}-{i:05d}"
            if archetype_for_persona(pid).slug == slug:
                rows.append(dict(
                    persona_id=pid, idx=found,
                    first_name="A", last_name="B", full_name="A B",
                    age=25, occupation="Student", state="MH", district="Mumbai",
                    city="Mumbai", city_tier="Tier-1",
                    college="iit-bombay", college_email=f"a{found}@iitb.ac.in",
                    personal_email=f"a{found}@gmail.com",
                    device_fingerprint=f"dev-{found}",
                    device_type="mobile",
                    phone_hash=f"phone-{found}",
                    acquisition_channel="unstop",
                    identity_pattern="trivial",
                    pair_partner_idx=None,
                    true_skill=0.0,
                    archetype_slug=slug,
                    model_version="generator-v1.1.0",
                ))
                found += 1
            i += 1
            if i > 50000:
                break  # safety
        return pd.DataFrame(rows)

    ghost_df = _build_for_archetype("ghost_risk_junior", 50)
    alpha_df = _build_for_archetype("alpha_generator", 50)

    ghost_events, _ = gen_backend_events(ghost_df)
    alpha_events, _ = gen_backend_events(alpha_df)

    ghost_preds = sum(1 for e in ghost_events if e["event_type"] == "prediction_made")
    alpha_preds = sum(1 for e in alpha_events if e["event_type"] == "prediction_made")

    assert alpha_preds > ghost_preds * 2, (
        f"alpha_generator made {alpha_preds} predictions; "
        f"ghost_risk_junior made {ghost_preds}. Substrate not driving spread."
    )
