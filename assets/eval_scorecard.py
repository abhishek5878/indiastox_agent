"""Eval scorecard as a 3x10 heatmap. Reads the latest run from eval/results/.

Cell colors:
  0 (miss)  → red
  1 (hit)   → green
The total (X/30) is the subtitle. The 3 dimensions (accuracy, calibration,
action) are the rows; the 10 canonical questions are the columns.

  make eval-scorecard
  open assets/eval_scorecard.png
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

RESULTS_DIR = _REPO / "eval" / "results"
OUT = _REPO / "assets" / "eval_scorecard.png"


def latest_run() -> dict:
    runs = sorted(RESULTS_DIR.glob("run_*.json"))
    if not runs:
        print(f"ERROR: no eval runs in {RESULTS_DIR}. Run `make eval` first.", file=sys.stderr)
        sys.exit(2)
    return json.loads(runs[-1].read_text())


def render() -> None:
    data = latest_run()
    results = data["results"]
    qids = [r["id"] for r in results]
    dims = ["accuracy", "calibration", "action"]

    # Build the 3xN matrix.
    grid = np.array([[r["scores"][d] for r in results] for d in dims], dtype=float)
    max_per_cell = 1.0

    fig, ax = plt.subplots(figsize=(12.5, 4.0))
    cmap = plt.cm.RdYlGn
    im = ax.imshow(grid, cmap=cmap, vmin=0, vmax=max_per_cell, aspect="auto")

    ax.set_xticks(range(len(qids)))
    ax.set_xticklabels(qids, fontsize=10)
    ax.set_yticks(range(len(dims)))
    ax.set_yticklabels(dims, fontsize=11)

    for i, d in enumerate(dims):
        for j, qid in enumerate(qids):
            val = grid[i, j]
            ax.text(j, i, f"{int(val)}", ha="center", va="center", fontsize=12,
                    color="black" if val >= 0.5 else "white", weight="bold")

    # Column totals (per-question score) along the top.
    col_totals = grid.sum(axis=0).astype(int)
    for j, tot in enumerate(col_totals):
        ax.text(j, -0.7, f"{tot}/3", ha="center", va="bottom", fontsize=10,
                color="#1f7a1f" if tot == 3 else "#a35200" if tot == 2 else "#990000",
                weight="bold")

    total = data["total_score"]
    max_total = data["max_total"]
    fm6_pass = "FM6 PASS (<28)" if total < 28 else "FM6 FAIL (>=28 - eval too easy?)"
    ax.set_title(
        f"Agent eval scorecard — {total}/{max_total}   {fm6_pass}\n"
        f"per-Q totals shown above; 0=miss (red), 1=hit (green)",
        fontsize=12, weight="bold", pad=22,
    )

    # Quiet outer frame.
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(axis="x", length=0)
    ax.tick_params(axis="y", length=0)

    fig.text(
        0.01, 0.01,
        "Q10 is unknowable from 1 week of data — the agent answers 'insufficient data, "
        "wide CI, propose 4-week incrementality test' and is correctly credited 3/3.   "
        "Q03/Q04 accuracy=0 from a 1pp TZ-parameter drift caught by the eval, not the linter.",
        fontsize=8, color="#666",
    )

    plt.tight_layout(rect=(0, 0.04, 1, 1))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUT, dpi=140, bbox_inches="tight")
    print(f"wrote {OUT}  ({total}/{max_total}, latest run: {RESULTS_DIR.name}/{sorted(RESULTS_DIR.glob('run_*.json'))[-1].name})")


if __name__ == "__main__":
    render()
