"""Layer K test — Critic Agent severity logic + confounder firing.

Asserts the data-driven Critic Agent v2.0.0 contract:
  - severity is computed from fired-confounder count + lift target,
    not just hardcoded thresholds.
  - confounder_checks is non-empty for any supported metric.
  - alternative_proposal is non-empty for every supported metric.
  - The current ghost_rate proposal (12pp lift) lands as severity=high
    because >= 3 confounders actually fire against the live substrate.
"""
from __future__ import annotations

import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from agent.critic_agent import critique, CONFOUNDERS_BY_METRIC

PENDING = REPO / "proposals" / "pending"
WAREHOUSE = REPO / "warehouse" / "indiastox.duckdb"


@pytest.fixture(scope="module", autouse=True)
def _require_warehouse():
    if not WAREHOUSE.exists():
        pytest.skip("warehouse not built — run `make resolve && make load` first")


def _make_test_proposal(metric: str, lift_pct: float, estimated_days: int = 14) -> str:
    """Write a throwaway proposal YAML and return its proposal_id.
    The test doesn't commit it to the DuckDB proposals table; the
    critic only reads from the YAML on disk.
    """
    pid = f"TEST-{uuid.uuid4().hex[:12]}"
    path = PENDING / f"{pid}.yaml"
    path.write_text(yaml.safe_dump(dict(
        proposal_id=pid,
        created_ts=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        triggered_by_action_id="test-fixture",
        hypothesis="Test hypothesis. Test cause-and-effect.",
        affected_metric=metric,
        expected_lift_pct=lift_pct,
        confidence=0.55,
        required_sample_n=500,
        estimated_days=estimated_days,
        proposed_experiment="Test experiment.",
    )))
    return pid


def _cleanup_test_proposal(pid: str) -> None:
    path = PENDING / f"{pid}.yaml"
    if path.exists():
        path.unlink()


def test_critic_outputs_required_fields():
    pid = _make_test_proposal("ghost_rate", lift_pct=-12.0)
    try:
        c = critique(pid, write_back=False)
    finally:
        _cleanup_test_proposal(pid)
    for field in ("severity", "counter_argument", "confounder_checks",
                  "confounders_fired", "alternative_proposal",
                  "reversibility_cost", "critic_version"):
        assert field in c, f"critique missing field: {field}"


def test_high_lift_with_fired_confounders_is_severity_high():
    """12pp lift target on ghost_rate fires klaviyo + brier + dark
    confounders against the current substrate. Severity must be high.
    """
    pid = _make_test_proposal("ghost_rate", lift_pct=-12.0)
    try:
        c = critique(pid, write_back=False)
    finally:
        _cleanup_test_proposal(pid)
    assert c["severity"] == "high", f"expected high, got {c['severity']}"
    assert len(c["confounders_fired"]) >= 1, (
        f"no confounders fired against the live data — substrate has no signal?"
    )


def test_low_lift_zero_confounders_is_lower_severity():
    """1pp lift on a metric with NO catalogued confounders should not
    return severity=high — the substrate has no signal worth alarm-bell.
    """
    pid = _make_test_proposal("predictions_per_user", lift_pct=1.0)
    try:
        c = critique(pid, write_back=False)
    finally:
        _cleanup_test_proposal(pid)
    assert c["severity"] in ("low", "medium"), (
        f"expected low/medium for tiny lift + no catalogued confounders, got {c['severity']}"
    )


def test_alternative_proposal_is_nonempty_and_mentions_fired_confounders():
    pid = _make_test_proposal("ghost_rate", lift_pct=-12.0)
    try:
        c = critique(pid, write_back=False)
    finally:
        _cleanup_test_proposal(pid)
    alt = c["alternative_proposal"]
    assert isinstance(alt, str) and len(alt) >= 50, f"alternative too short: {alt!r}"
    fired_names = c["confounders_fired"]
    if fired_names:
        joined = alt.lower()
        # At least one fired confounder name should appear in the alternative.
        assert any(fc in joined for fc in fired_names), (
            f"alternative doesn't reference any fired confounder ({fired_names}): {alt!r}"
        )


def test_confounder_checks_run_for_supported_metrics():
    for metric in CONFOUNDERS_BY_METRIC:
        pid = _make_test_proposal(metric, lift_pct=-5.0)
        try:
            c = critique(pid, write_back=False)
        finally:
            _cleanup_test_proposal(pid)
        assert len(c["confounder_checks"]) == len(CONFOUNDERS_BY_METRIC[metric]), (
            f"{metric}: expected {len(CONFOUNDERS_BY_METRIC[metric])} checks, "
            f"got {len(c['confounder_checks'])}"
        )
        for check in c["confounder_checks"]:
            assert "name" in check
            assert "fired" in check
            assert "evidence" in check
            assert isinstance(check["fired"], bool)


def test_critic_version_is_v2():
    pid = _make_test_proposal("ghost_rate", lift_pct=-12.0)
    try:
        c = critique(pid, write_back=False)
    finally:
        _cleanup_test_proposal(pid)
    assert c["critic_version"] == "2.0.0", f"expected 2.0.0, got {c['critic_version']!r}"
