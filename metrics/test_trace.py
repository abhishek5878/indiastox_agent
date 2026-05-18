"""Layer J test — every metric returns a 3-step `trace` field.

Asserts the "Why this number?" contract: every tool surfaces a
3-step natural-language trace alongside the numeric value. The trace
is the agent's calibrated explanation; a missing or malformed trace
breaks the substrate's load-bearing-explanation guarantee.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from metrics.definitions import (
    weekly_active_posters,
    time_to_first_action,
    unstop_to_participation_rate,
    ghost_rate,
    dark_channel_fraction,
    channel_cac_bounds,
    brier_score,
    gyaani_graduation_rate,
    predictions_per_user,
    email_click_to_signup,
    metric_gameability_index,
)
from metrics.skill import get_skill_distribution

WAREHOUSE = REPO / "warehouse" / "indiastox.duckdb"
WEEK = "2024-W01"


@pytest.fixture(scope="module", autouse=True)
def _require_warehouse():
    if not WAREHOUSE.exists():
        pytest.skip("warehouse not built — run `make resolve && make load` first")


# (metric_fn, args) pairs covering all 12 tools.
METRICS = [
    (weekly_active_posters,         [WEEK]),
    (time_to_first_action,          [WEEK]),
    (unstop_to_participation_rate,  [WEEK]),
    (ghost_rate,                    [WEEK]),
    (dark_channel_fraction,         [WEEK]),
    (channel_cac_bounds,            [WEEK]),
    (brier_score,                   [WEEK]),
    (gyaani_graduation_rate,        [WEEK]),
    (predictions_per_user,          [WEEK]),
    (email_click_to_signup,         []),
    (get_skill_distribution,        [None, None]),
    (metric_gameability_index,      []),
]


@pytest.mark.parametrize("fn, args", METRICS, ids=lambda x: getattr(x, "__name__", repr(x)) if callable(x) else repr(x))
def test_trace_has_exactly_3_steps(fn, args):
    r = fn(*args)
    assert isinstance(r.trace, list), f"{fn.__name__}: trace must be a list"
    assert len(r.trace) == 3, f"{fn.__name__}: trace has {len(r.trace)} step(s), expected 3"


@pytest.mark.parametrize("fn, args", METRICS, ids=lambda x: getattr(x, "__name__", repr(x)) if callable(x) else repr(x))
def test_trace_steps_are_nonempty_strings(fn, args):
    r = fn(*args)
    for i, step in enumerate(r.trace, 1):
        assert isinstance(step, str), f"{fn.__name__}: trace[{i}] is {type(step).__name__}, not str"
        assert step.strip(), f"{fn.__name__}: trace[{i}] is empty/whitespace"
        assert len(step) >= 20, f"{fn.__name__}: trace[{i}] is too short ({len(step)} chars) — be specific"


def test_ghost_rate_trace_names_biggest_contributor():
    """Step 2 of ghost_rate's trace names the biggest-contributing channel.
    This is the load-bearing 'why this number?' format the brief expects.
    """
    r = ghost_rate(WEEK, acquisition_source="all")
    step2 = r.trace[1].lower()
    assert (
        "biggest contributor" in step2 or "biggest channel" in step2 or "single-cohort" in step2
    ), f"step2 doesn't surface the breakdown anchor: {r.trace[1]!r}"


def test_weekly_active_posters_trace_cites_confidence_rationale():
    """Step 3 should explain WHERE confidence came from (identity floor + window)."""
    r = weekly_active_posters(WEEK)
    step3 = r.trace[2].lower()
    assert "confidence" in step3
    assert "identity floor" in step3 or "probabilistic" in step3


def test_gameability_index_trace_names_all_three_axes():
    r = metric_gameability_index()
    blob = " ".join(r.trace).lower()
    for axis in ("definition_hash_drift", "source_table_drift", "value_outlier_drift"):
        assert axis in blob, f"trace missing axis {axis!r}"
