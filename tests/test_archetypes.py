"""Pytest tests for sim/archetypes.py — P0.1 deliverable.

Tests cover the three things the task plan calls out as done-when:
  (1) Population weights sum to 1.0 and slugs are unique (module-load invariants).
  (2) Hash-based assignment is stable: same persona_id always → same archetype.
  (3) Distribution over 10k synthetic persona_ids matches target shares within
      tolerance.

Plus sanity checks on goal / sector / true_skill sampling.
"""
from __future__ import annotations

import math
import statistics
import uuid

import pytest

from sim.archetypes import (
    ALL_SECTORS,
    ARCHETYPES,
    GOALS,
    Archetype,
    archetype_by_slug,
    archetype_for_persona,
    sample_initial_true_skill,
)


# ---------------------------------------------------------------------------
# Module-load invariants
# ---------------------------------------------------------------------------


def test_weights_sum_to_one() -> None:
    total = sum(a.weight for a in ARCHETYPES)
    assert abs(total - 1.0) < 1e-9, f"weights sum to {total}, expected 1.0"


def test_slugs_unique() -> None:
    slugs = [a.slug for a in ARCHETYPES]
    assert len(slugs) == len(set(slugs)), "duplicate archetype slugs"


def test_twenty_archetypes() -> None:
    assert len(ARCHETYPES) == 20, f"expected 20 archetypes, got {len(ARCHETYPES)}"


def test_all_goals_valid() -> None:
    for a in ARCHETYPES:
        assert a.primary_goal in GOALS, f"{a.slug} has invalid goal {a.primary_goal}"


def test_all_sectors_valid() -> None:
    for a in ARCHETYPES:
        for sec in a.sector_affinity:
            assert sec in ALL_SECTORS, f"{a.slug} has invalid sector {sec}"


# ---------------------------------------------------------------------------
# Stable assignment
# ---------------------------------------------------------------------------


def test_assignment_stable_across_calls() -> None:
    pid = "persona-12345"
    first = archetype_for_persona(pid)
    for _ in range(50):
        assert archetype_for_persona(pid) is first


def test_assignment_stable_across_persona_ids() -> None:
    pids = [f"persona-{i:05d}" for i in range(100)]
    assignments_1 = [archetype_for_persona(p).slug for p in pids]
    assignments_2 = [archetype_for_persona(p).slug for p in pids]
    assert assignments_1 == assignments_2


# ---------------------------------------------------------------------------
# Population distribution
# ---------------------------------------------------------------------------


def _sample_population(n: int) -> dict[str, int]:
    counts: dict[str, int] = {a.slug: 0 for a in ARCHETYPES}
    for i in range(n):
        pid = f"persona-{i:08d}"
        arch = archetype_for_persona(pid)
        counts[arch.slug] += 1
    return counts


def test_distribution_within_tolerance() -> None:
    """Sample 10k synthetic persona_ids and check each archetype's share is
    within 1pp (absolute) of its target weight.

    1pp is generous: for the smallest archetype (weight=0.02, n=10000),
    expected count is 200 with std ≈ 14. A 1pp absolute deviation is 100,
    well above 6σ — so this test failing means something is actually wrong,
    not bad luck.
    """
    counts = _sample_population(10_000)
    n = 10_000
    for arch in ARCHETYPES:
        share = counts[arch.slug] / n
        assert abs(share - arch.weight) < 0.01, (
            f"{arch.slug}: share={share:.4f} target={arch.weight:.4f} "
            f"|diff|={abs(share - arch.weight):.4f} > 0.01"
        )


def test_distribution_works_with_uuid_persona_ids() -> None:
    """Real personas in the warehouse use 32-char uuid-derived ids; verify
    the hash-based bucketing is uniform for that input shape as well."""
    counts: dict[str, int] = {a.slug: 0 for a in ARCHETYPES}
    for _ in range(5_000):
        pid = uuid.uuid4().hex
        counts[archetype_for_persona(pid).slug] += 1
    for arch in ARCHETYPES:
        share = counts[arch.slug] / 5_000
        assert abs(share - arch.weight) < 0.02, (
            f"uuid distribution drifted for {arch.slug}: share={share:.4f} "
            f"target={arch.weight:.4f}"
        )


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


def test_archetype_by_slug_roundtrip() -> None:
    for a in ARCHETYPES:
        found = archetype_by_slug(a.slug)
        assert found is a


def test_archetype_by_slug_unknown() -> None:
    with pytest.raises(KeyError):
        archetype_by_slug("not_an_archetype")


# ---------------------------------------------------------------------------
# True-skill sampling
# ---------------------------------------------------------------------------


def test_true_skill_sample_stable() -> None:
    pid = "persona-skill-test"
    first = sample_initial_true_skill(pid)
    for _ in range(20):
        assert sample_initial_true_skill(pid) == first


def test_true_skill_population_mean_matches_archetype() -> None:
    """For each archetype, draw a population of personas hash-assigned to it
    and verify the empirical mean true_skill is within 4σ/√n of the archetype's
    true_skill_mean. This catches a bug where archetype assignment and
    skill sampling decouple (e.g. all personas get N(0,1) regardless of
    archetype).
    """
    samples_per_archetype: dict[str, list[float]] = {a.slug: [] for a in ARCHETYPES}
    for i in range(50_000):
        pid = f"persona-skill-pop-{i:08d}"
        arch = archetype_for_persona(pid)
        if len(samples_per_archetype[arch.slug]) < 1000:
            samples_per_archetype[arch.slug].append(sample_initial_true_skill(pid))

    for arch in ARCHETYPES:
        sample = samples_per_archetype[arch.slug]
        if len(sample) < 50:
            continue  # 2%-weight archetypes may not hit 50 in 50k draws; skip
        empirical_mean = statistics.fmean(sample)
        tolerance = 4 * arch.true_skill_std / math.sqrt(len(sample))
        assert abs(empirical_mean - arch.true_skill_mean) < tolerance, (
            f"{arch.slug}: empirical_mean={empirical_mean:.3f} "
            f"expected={arch.true_skill_mean:.3f} ±{tolerance:.3f} "
            f"(n={len(sample)})"
        )


def test_archetype_dataclass_frozen() -> None:
    """Archetypes are immutable; mutating should raise FrozenInstanceError."""
    a = ARCHETYPES[0]
    with pytest.raises(Exception):  # noqa: B017  (dataclass FrozenInstanceError)
        a.weight = 999  # type: ignore[misc]
