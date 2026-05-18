"""Verify metrics/skill.update_glicko2 against Glickman's published worked example.

Glickman, M.E. (2012), Example of the Glicko-2 System
http://www.glicko.net/glicko/glicko2.pdf — Section "Example calculation".

Starting from rating=1500, RD=200, vol=0.06, after matches against three
opponents (1400 RD=30 WIN, 1550 RD=100 LOSS, 1700 RD=300 LOSS) with
system parameter τ=0.5, the paper's expected result is:

    rating ≈ 1464.06
    RD     ≈ 151.52
    vol    ≈ 0.05999

This test pins our implementation to that.
"""
from __future__ import annotations

import math

import pytest

from metrics.skill import GlickoRating, update_glicko2, _update_volatility


def test_glickman_2012_worked_example_volatility():
    """Volatility step alone — the Illinois iteration result."""
    # Pre-Step-5 values from the paper (Section 4.1 example):
    #   phi (post-scale) ≈ 1.1513
    #   v ≈ 1.7785
    #   delta ≈ -0.4834
    #   sigma (prior) = 0.06
    new_sigma = _update_volatility(
        sigma=0.06,
        delta=-0.4834,
        phi=1.1513,
        v=1.7785,
        tau=0.5,
    )
    assert math.isclose(new_sigma, 0.05999, abs_tol=0.0001), (
        f"new sigma drifted from paper: got {new_sigma:.6f}, expected ~0.05999"
    )


def test_glickman_2012_worked_example_full_update():
    """Full update — rating + RD + vol must all match the paper."""
    prior = GlickoRating(rating=1500.0, rd=200.0, vol=0.06)
    matches = [
        (1400.0, 30.0,  1.0),  # WIN against 1400 RD=30
        (1550.0, 100.0, 0.0),  # LOSS against 1550 RD=100
        (1700.0, 300.0, 0.0),  # LOSS against 1700 RD=300
    ]
    out = update_glicko2(prior, matches)
    assert math.isclose(out.rating, 1464.06, abs_tol=0.5), (
        f"rating drift: got {out.rating:.2f}, expected ~1464.06"
    )
    assert math.isclose(out.rd, 151.52, abs_tol=0.5), (
        f"RD drift: got {out.rd:.2f}, expected ~151.52"
    )
    assert math.isclose(out.vol, 0.05999, abs_tol=0.0001), (
        f"vol drift: got {out.vol:.6f}, expected ~0.05999"
    )


def test_no_matches_widens_rd_only():
    """No games in a rating period: RD widens by sqrt(phi^2 + sigma^2); rating + vol unchanged."""
    prior = GlickoRating(rating=1500.0, rd=200.0, vol=0.06)
    out = update_glicko2(prior, matches=[])
    assert out.rating == prior.rating
    assert out.vol == prior.vol
    assert out.rd > prior.rd  # RD must widen
    # The post-update phi = sqrt(phi^2 + sigma^2) (Step 6 alone).
    # In the Glicko-2 scale: phi = 200/173.7178 ≈ 1.1513
    # new_phi = sqrt(1.1513^2 + 0.06^2) ≈ 1.1528
    # new_rd  = new_phi * 173.7178 ≈ 200.27
    assert math.isclose(out.rd, 200.27, abs_tol=0.5)
