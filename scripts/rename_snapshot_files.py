"""Safely rename legacy data_YYYY-MM-DD.csv snapshots to voyage_snapshot_*.csv.

Preview is the default. Pass --apply to perform the rename after checking all
planned destinations for collisions. Prediction files are deliberately ignored.
Run from any working directory:
    python scripts/rename_snapshot_files.py
    python scripts/rename_snapshot_files.py --apply
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT_DIR = PROJECT_ROOT / "data" / "snapshots" / "split_by_date"
LEGACY_FILENAME_RE = re.compile(r"^data_(\d{4}-\d{2}-\d{2})\.csv$")


def plan_renames(snapshot_dir: Path) -> list[tuple[Path, Path]]:
    """Return all matching legacy source/destination pairs in stable order."""
    planned = []
    if not snapshot_dir.is_dir():
        return planned

    for source in sorted(snapshot_dir.glob("data_*.csv")):
        match = LEGACY_FILENAME_RE.fullmatch(source.name)
        if match:
            destination = snapshot_dir / f"voyage_snapshot_{match.group(1)}.csv"
            planned.append((source, destination))
    return planned


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform renames (without this flag, the script only previews)",
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=DEFAULT_SNAPSHOT_DIR,
        help="override the snapshot directory (primarily useful for testing)",
    )
    args = parser.parse_args()

    snapshot_dir = args.snapshot_dir.resolve()
    if not snapshot_dir.is_dir():
        print(f"Snapshot directory does not exist: {snapshot_dir}", file=sys.stderr)
        return 2

    planned = plan_renames(snapshot_dir)
    if not planned:
        print(f"No legacy data_YYYY-MM-DD.csv files found in {snapshot_dir}")
        return 0

    # Check every destination before changing any file: no partial run due to a
    # name collision, and never overwrite an existing standardized snapshot.
    collisions = [(src, dst) for src, dst in planned if dst.exists() and dst != src]
    if collisions:
        print("Rename aborted; destination file(s) already exist:", file=sys.stderr)
        for source, destination in collisions:
            print(f"  {source.name} -> {destination.name}", file=sys.stderr)
        return 1

    for source, destination in planned:
        action = "RENAME" if args.apply else "WOULD RENAME"
        print(f"{action}: {source.name} -> {destination.name}")

    if not args.apply:
        print("Preview only; rerun with --apply to perform these renames.")
        return 0

    for source, destination in planned:
        source.rename(destination)
    print(f"Renamed {len(planned)} snapshot file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
