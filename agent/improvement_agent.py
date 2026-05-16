"""Post-eval improvement agent — closes the eval loop on itself.

Runs immediately after `make eval`. Reads the latest scorecard. For every
question that scored < 3/3, identifies the failure category (tool /
reasoning / calibration) and proposes a concrete, applicable change.

Writes two artifacts:
  - PROPOSED_IMPROVEMENTS.md  — human-readable review surface
  - data/proposed_improvements.json — machine-readable, consumed by
                                       `make promote-improvement LINE=N`

Failure categorization:
  - accuracy=0 + numeric ground truth      → tool/SQL drift (data layer)
  - accuracy=0 + unknowable / skill_winner → reasoning (agent interpretation)
  - calibration=0                          → calibration markers missing
  - action=0                               → action markers missing
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

RESULTS_DIR = _REPO / "eval" / "results"
IMPROV_MD = _REPO / "PROPOSED_IMPROVEMENTS.md"
IMPROV_JSON = _REPO / "data" / "proposed_improvements.json"


def latest_run() -> Optional[dict]:
    runs = sorted(RESULTS_DIR.glob("run_*.json"))
    if not runs:
        return None
    return json.loads(runs[-1].read_text())


def classify(q: dict) -> list[dict]:
    """Yield zero-or-more proposed improvements for a single question's scores."""
    out: list[dict] = []
    qid = q["id"]
    text = q["text"]
    scores = q["scores"]
    gt_kind = q.get("ground_truth_kind", "numeric")

    if scores["accuracy"] == 0:
        if gt_kind == "numeric":
            out.append(dict(
                question_id=qid,
                kind="tool_drift",
                category="tool",
                rationale=(
                    f"{qid} numeric accuracy=0 means the agent's number doesn't match "
                    f"the independent SQL within tolerance. Most often: parameter "
                    f"encoding drift (timestamptz vs timestamp literal) between "
                    f"the metric function and the YAML ground-truth SQL."
                ),
                proposed_change=dict(
                    target="metrics/definitions.py",
                    change_type="investigate_tz_handling",
                    note=(
                        "Add a `start_naive` / `end_naive` conversion in `_week_bounds` "
                        "and pass naive datetimes to DuckDB when the underlying column is "
                        "TIMESTAMP-without-TZ. Verify by comparing single-query results "
                        "with `eval/canonical_questions.yaml` Q03 / Q04 SQL side-by-side."
                    ),
                ),
            ))
        elif gt_kind.startswith("skill_winner") or gt_kind == "unknowable":
            out.append(dict(
                question_id=qid,
                kind="reasoning",
                category="reasoning",
                rationale=(
                    f"{qid} ground truth is non-numeric ({gt_kind}). Accuracy=0 means "
                    f"the agent's None or text answer didn't match the expected "
                    f"acknowledgement. Tighten the agent's `value=None` semantics so "
                    f"the eval credits 'correctly says it can't answer'."
                ),
                proposed_change=dict(
                    target="agent/growth_agent.py",
                    change_type="acknowledgement_handling",
                    note=(
                        "In handler for the failing question, when no significant signal "
                        "exists, set `value=None` AND include a known-acknowledgement "
                        "string in `calibration` (e.g. 'no significant segment difference' "
                        "for skill_winner questions). Adjust eval scoring rule if needed."
                    ),
                ),
            ))

    if scores["calibration"] == 0:
        out.append(dict(
            question_id=qid,
            kind="calibration_markers_missing",
            category="calibration",
            rationale=(
                f"{qid} calibration=0: required substrings absent in the agent's "
                f"calibration string. The agent has the data (confidence + window_open "
                f"are populated on every MetricResult) but the surface text doesn't "
                f"name them by their canonical keywords."
            ),
            proposed_change=dict(
                target="agent/growth_agent.py",
                change_type="enrich_calibration_template",
                note=(
                    "Update `_calibration_string` to explicitly include the words "
                    "'confidence', 'window_open', 'sample_n', and 'interpretation:' "
                    "as labels — not just the values. The agent reads these out to a "
                    "human downstream; keywords matter."
                ),
            ),
        ))

    if scores["action"] == 0:
        out.append(dict(
            question_id=qid,
            kind="action_markers_missing",
            category="action",
            rationale=(
                f"{qid} action=0: the proposed next-step lacks the required "
                f"keywords. Either the action is generic (no anchor to the number) "
                f"or it omits the canonical word the eval was looking for."
            ),
            proposed_change=dict(
                target="agent/growth_agent.py",
                change_type="enrich_action_template",
                note=(
                    f"For {qid}, ensure the action text mentions the canonical "
                    f"keyword from the YAML's action_markers. Anchor the action "
                    f"directly to the metric value (e.g. 'because ghost_rate is "
                    f"X%' rather than 'monitor weekly')."
                ),
            ),
        ))

    return out


def run() -> dict:
    run_data = latest_run()
    if not run_data:
        print("No eval runs found. Run `make eval` first.", file=sys.stderr)
        return dict(generated_at=None, improvements=[])

    improvements: list[dict] = []
    for q in run_data["results"]:
        for imp in classify(q):
            improvements.append(imp)

    payload = dict(
        generated_at=datetime.now(timezone.utc).isoformat(),
        eval_run=run_data.get("ts"),
        total_score=run_data.get("total_score"),
        max_total=run_data.get("max_total"),
        improvements=improvements,
    )

    IMPROV_JSON.parent.mkdir(parents=True, exist_ok=True)
    IMPROV_JSON.write_text(json.dumps(payload, indent=2, default=str))

    lines = [
        "# Proposed improvements — agent-written",
        "",
        f"After eval run `{run_data.get('ts')}` (score: "
        f"{run_data.get('total_score')}/{run_data.get('max_total')}), the agent identified "
        f"{len(improvements)} concrete improvement(s).",
        "",
        "Apply an improvement with: `make promote-improvement LINE=<N>` "
        "(N = 1-indexed position below).",
        "",
    ]
    for i, imp in enumerate(improvements, 1):
        c = imp["proposed_change"]
        lines += [
            f"## {i}. {imp['question_id']} — {imp['kind']} ({imp['category']})",
            "",
            f"**Rationale.** {imp['rationale']}",
            "",
            f"**Target.** `{c['target']}`",
            "",
            f"**Change type.** `{c['change_type']}`",
            "",
            f"**Note.** {c['note']}",
            "",
        ]

    IMPROV_MD.write_text("\n".join(lines))
    print(f"wrote {IMPROV_MD}  ({len(improvements)} improvements)", file=sys.stderr)
    print(f"wrote {IMPROV_JSON}", file=sys.stderr)
    return payload


if __name__ == "__main__":
    run()
