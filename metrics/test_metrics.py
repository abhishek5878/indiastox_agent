"""Pytest tests for the metric layer.

Three tests per metric:
  - determinism (same inputs → same output)
  - monotonicity / sensitivity (changing a parameter moves the result the expected way)
  - logical consistency (relationships between metrics hold)

These do NOT mock the database. The brief is explicit: tests that assert
join, identity, or metric logic must hit a real DuckDB. The pipeline must
have been run (`make resolve`) before these run.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from metrics.definitions import (
    weekly_active_posters,
    time_to_first_action,
    unstop_to_participation_rate,
    ghost_rate,
)

REPO = Path(__file__).resolve().parents[1]
WAREHOUSE = REPO / "warehouse" / "indiastox.duckdb"
WEEK = "2024-W01"


@pytest.fixture(scope="module", autouse=True)
def _require_warehouse():
    if not WAREHOUSE.exists():
        pytest.skip("warehouse not built — run `make resolve` first")


# ---------------------------------------------------------------------------
# weekly_active_posters
# ---------------------------------------------------------------------------

class TestWeeklyActivePosters:
    def test_deterministic(self):
        a = weekly_active_posters(WEEK)
        b = weekly_active_posters(WEEK)
        assert a.value == b.value
        assert a.definition_version == b.definition_version
        assert a.computation_sql == b.computation_sql

    def test_higher_confidence_gate_reduces_or_holds_value(self):
        """Raising min_identity_confidence cannot increase the count."""
        low = weekly_active_posters(WEEK, min_identity_confidence=0.30)
        high = weekly_active_posters(WEEK, min_identity_confidence=0.90)
        assert high.value <= low.value, (
            f"strict gate ({high.value}) should not exceed lax gate ({low.value})"
        )

    def test_confidence_interval_bounds_value(self):
        r = weekly_active_posters(WEEK)
        assert r.confidence_interval is not None
        lo, hi = r.confidence_interval
        assert lo <= r.value <= hi


# ---------------------------------------------------------------------------
# time_to_first_action
# ---------------------------------------------------------------------------

class TestTimeToFirstAction:
    def test_deterministic(self):
        a = time_to_first_action(WEEK)
        b = time_to_first_action(WEEK)
        assert a.value == b.value
        assert a.computation_sql == b.computation_sql

    def test_breakdowns_present(self):
        r = time_to_first_action(WEEK)
        assert r.breakdowns is not None
        assert "device_type" in r.breakdowns
        assert "city_tier" in r.breakdowns

    def test_non_negative(self):
        """A first-prediction event cannot occur before the signup event."""
        r = time_to_first_action(WEEK)
        assert r.value >= 0, f"time_to_first_action returned negative: {r.value}"


# ---------------------------------------------------------------------------
# unstop_to_participation_rate
# ---------------------------------------------------------------------------

class TestUnstopToParticipationRate:
    def test_deterministic(self):
        a = unstop_to_participation_rate(WEEK)
        b = unstop_to_participation_rate(WEEK)
        assert a.value == b.value

    def test_in_zero_one(self):
        r = unstop_to_participation_rate(WEEK)
        assert 0.0 <= r.value <= 1.0

    def test_participations_le_signups(self):
        r = unstop_to_participation_rate(WEEK)
        b = r.breakdowns or {}
        signups = b.get("signups", 0)
        participations = b.get("participations", 0)
        assert participations <= signups


# ---------------------------------------------------------------------------
# ghost_rate
# ---------------------------------------------------------------------------

class TestGhostRate:
    def test_deterministic(self):
        a = ghost_rate(WEEK)
        b = ghost_rate(WEEK)
        assert a.value == b.value

    def test_in_zero_one(self):
        r = ghost_rate(WEEK)
        assert 0.0 <= r.value <= 1.0

    def test_ghost_and_participation_count_disjoint_for_unstop(self):
        """Among the Unstop cohort, ghosts (no predictions ever within 7d) and
        participants (predicted within 7d of their challenge_signup) are disjoint
        sets — a user can't simultaneously have made zero predictions AND have
        predicted within 7d. So: ghost_count + participations <= cohort_size.

        We check this at the count level (not the rate level) because the two
        metrics use different denominators on purpose: ghost_rate is over the
        full acquired cohort, unstop_to_participation_rate is over those who
        signed up for the challenge. Comparing rates directly is apples to
        oranges; comparing counts is the real invariant.
        """
        g = ghost_rate(WEEK, acquisition_source="unstop")
        p = unstop_to_participation_rate(WEEK)
        cohort = g.breakdowns["cohort_size"]
        ghost_count = g.breakdowns["ghost_count"]
        signups = p.breakdowns["signups"]
        participations = p.breakdowns["participations"]
        # Sanity: signups <= cohort (you can't have more signups than acquired).
        assert signups <= cohort, f"signups({signups}) > cohort({cohort})"
        # The disjoint invariant.
        assert ghost_count + participations <= cohort, (
            f"ghost_count({ghost_count}) + participations({participations}) > cohort({cohort})"
        )
