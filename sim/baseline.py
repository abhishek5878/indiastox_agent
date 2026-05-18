"""Living-world baseline snapshot.

After `make all` the warehouse holds the W01 baseline. We snapshot that
file to `warehouse/indiastox.baseline.duckdb`. The Living World tab's
Reset button copies it back over `warehouse/indiastox.duckdb` — sub-second
restore so demos are reproducible without re-running the full pipeline.

Usage:
  make baseline          # snapshot current warehouse → baseline file
  python3 -m sim.baseline --restore   # copy baseline back over warehouse
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
WAREHOUSE = _REPO / "warehouse" / "indiastox.duckdb"
BASELINE = _REPO / "warehouse" / "indiastox.baseline.duckdb"


def snapshot() -> Path:
    if not WAREHOUSE.exists():
        print(f"ERROR: {WAREHOUSE} missing. Run `make all` first.", file=sys.stderr)
        sys.exit(2)
    shutil.copy2(WAREHOUSE, BASELINE)
    print(f"snapshot wrote {BASELINE}  ({BASELINE.stat().st_size:,} bytes)")
    return BASELINE


def restore() -> Path:
    if not BASELINE.exists():
        print(f"ERROR: {BASELINE} missing. Run `make baseline` first.", file=sys.stderr)
        sys.exit(2)
    shutil.copy2(BASELINE, WAREHOUSE)
    print(f"restored {WAREHOUSE} from {BASELINE.name}")
    return WAREHOUSE


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()
    if args.restore:
        restore()
    else:
        snapshot()


if __name__ == "__main__":
    main()
