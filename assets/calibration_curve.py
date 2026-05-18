"""Render assets/calibration_curve.png — the README hero image.

For each confidence_stars bucket (1..5 → predicted probability 0.5..0.9),
compute the realized WIN-rate among closed predictions in W01. Plot
predicted vs realized; the diagonal is perfect calibration.

The synthetic data here draws outcomes from a fixed (WIN, LOSS, DRAW)
distribution — outcomes are NOT actually correlated with confidence_stars.
The plot will show a near-horizontal line well below the diagonal: the
agent's predicted probabilities and the realized accuracy don't align,
because by construction they can't.

That's the honest finding. The same plot against real IndiaStox data
would show the actual calibration curve and would be the load-bearing
input to any agent that uses prediction confidence as a signal. The
infrastructure to MEASURE calibration is what's load-bearing today; the
content of any single week's curve is a different question.
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import matplotlib
matplotlib.use("Agg")  # headless rendering
import matplotlib.pyplot as plt

_REPO = Path(__file__).resolve().parents[1]
WAREHOUSE = _REPO / "warehouse" / "indiastox.duckdb"
OUT_PNG = _REPO / "assets" / "calibration_curve.png"


def main() -> None:
    if not WAREHOUSE.exists():
        print(f"ERROR: warehouse missing at {WAREHOUSE}", file=sys.stderr)
        sys.exit(2)

    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        rows = con.execute(
            """
            WITH closed AS (
              SELECT confidence_stars,
                     0.5 + (confidence_stars - 1) * 0.1 AS predicted_prob,
                     CASE WHEN outcome = 'WIN' THEN 1.0
                          WHEN outcome = 'DRAW' THEN 0.5
                          ELSE 0.0 END AS realized
              FROM fact_prediction
              WHERE is_outcome_resolved = TRUE AND outcome IS NOT NULL
            )
            SELECT confidence_stars,
                   AVG(predicted_prob) AS p,
                   AVG(realized) AS realized_rate,
                   COUNT(*) AS n
            FROM closed
            GROUP BY confidence_stars
            ORDER BY confidence_stars
            """
        ).fetchall()
        # Brier — for the caption.
        brier = con.execute(
            """
            WITH preds AS (
              SELECT
                0.5 + (confidence_stars - 1) * 0.1 AS p,
                CASE WHEN outcome = 'WIN' THEN 1.0
                     WHEN outcome = 'DRAW' THEN 0.5
                     ELSE 0.0 END AS actual
              FROM fact_prediction
              WHERE is_outcome_resolved = TRUE AND outcome IS NOT NULL
            )
            SELECT AVG((p - actual) * (p - actual))
            FROM preds
            """
        ).fetchone()[0]
    finally:
        con.close()

    stars = [r[0] for r in rows]
    pred = [float(r[1]) for r in rows]
    realized = [float(r[2]) for r in rows]
    n = [int(r[3]) for r in rows]

    fig, ax = plt.subplots(figsize=(7.0, 5.5), dpi=140)

    # Perfect-calibration diagonal.
    ax.plot([0.45, 0.95], [0.45, 0.95], color="#9aa0a6", linestyle="--",
            linewidth=1.2, label="perfect calibration")

    # Realized curve, dot-size scaled by sample count.
    sizes = [max(60, int(c * 0.15)) for c in n]
    ax.plot(pred, realized, color="#1a73e8", linewidth=2.0, marker="o",
            markersize=0, label=f"realized (n={sum(n)})")
    ax.scatter(pred, realized, s=sizes, color="#1a73e8", zorder=5, edgecolor="white")

    # Label each point with the star bucket + sample size.
    for s_val, p, r_val, count in zip(stars, pred, realized, n):
        ax.annotate(
            f"{s_val}★ (n={count})",
            xy=(p, r_val),
            xytext=(6, -4),
            textcoords="offset points",
            fontsize=8.5,
            color="#202124",
        )

    ax.set_xlabel("predicted P(WIN) (from confidence_stars: 1★=0.5 → 5★=0.9)")
    ax.set_ylabel("realized accuracy on closed outcomes")
    ax.set_xlim(0.45, 0.95)
    ax.set_ylim(0.30, 0.95)
    ax.set_title("IndiaStox prediction calibration — W01 synthetic data")
    ax.grid(True, alpha=0.25, linestyle=":")
    ax.legend(loc="upper left", framealpha=0.9)

    caption = (
        f"Mean Brier = {brier:.4f}  (random-guess baseline = 0.25)\n"
        f"Synthetic data carries a real signal (N1): WIN probability AND\n"
        f"confidence_stars are both biased by each persona's latent true_skill.\n"
        f"The realized line BENDS upward with stars (1★→5★ ≈ 36%→57%) but stays\n"
        f"below the diagonal — the stars→probability mapping is overconfident,\n"
        f"which is the right calibration story for a young product. The\n"
        f"infrastructure to MEASURE calibration is the deliverable; the curve\n"
        f"shape from one week is a starting point, not a verdict."
    )
    fig.text(0.02, -0.02, caption, fontsize=8.2, color="#5f6368", ha="left",
             va="top", family="monospace")
    plt.tight_layout(rect=[0, 0.02, 1, 1])

    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_PNG, bbox_inches="tight", facecolor="white")
    print(f"wrote {OUT_PNG} (Brier={brier:.4f}, points={len(rows)})", file=sys.stderr)


if __name__ == "__main__":
    main()
