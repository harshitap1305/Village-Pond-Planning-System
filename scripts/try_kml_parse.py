#!/usr/bin/env python3
"""
Manual sanity-check script: parse contours_1m.kml and print summary statistics.

Run from project root (with venv activated):
    python scripts/try_kml_parse.py

Expected output:
  Parsed 1355 contour lines  (LineString Placemarks only)
  The other 1355 Placemarks are Point label markers -- correctly skipped.
  Elevation range: 267.0 -- 298.0 m  (32 unique levels)
  Total coordinate points: ~159,000

This script is NOT part of the test suite -- it's a quick manual QA tool.
Run it whenever you change the parser to catch regressions before committing.
"""

import sys
from pathlib import Path

# Allow running from project root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.terrain.kml_source import KMLTerrainSource

FIXTURE = Path("tests/fixtures/contours_1m.kml")


def main() -> None:
    if not FIXTURE.exists():
        print(f"ERROR: fixture not found at {FIXTURE}")
        print("Make sure you run this from the project root directory.")
        sys.exit(1)

    size_kb = FIXTURE.stat().st_size / 1024
    print(f"Parsing {FIXTURE}  ({size_kb:.1f} KB)...")

    source = KMLTerrainSource.from_file(FIXTURE)
    contours = source.extract_contours()

    elevations = [c.elevation for c in contours]
    unique_elevs = sorted(set(elevations))
    total_points = sum(len(c.points) for c in contours)
    terrain_elevs = [e for e in unique_elevs if e > 10]  # filter the 1.0 outlier

    print(f"\n{'='*55}")
    print(f"  Total contour lines parsed  : {len(contours)}")
    print(f"  Unique elevation levels     : {len(unique_elevs)}")
    print(
        f"  Full elevation range        : {min(elevations):.1f} – {max(elevations):.1f} m"
    )
    if terrain_elevs:
        print(
            f"  Core terrain range          : {min(terrain_elevs):.1f} – {max(terrain_elevs):.1f} m"
        )
    print(f"  Total coordinate points     : {total_points:,}")
    print(f"  Avg points per contour      : {total_points / len(contours):.1f}")
    print(f"\n  All unique elevations: {unique_elevs}")
    print(
        f"\n  First contour  →  elev={contours[0].elevation}, "
        f"pts={len(contours[0].points)}, "
        f"first_pt=({contours[0].points[0][0]:.5f}, {contours[0].points[0][1]:.5f})"
    )
    print(f"{'='*55}")

    # Hard assertions — fail loudly if something is wrong
    assert len(contours) == 1355, (
        f"Expected 1355 LineString contours, got {len(contours)}\n"
        f"(The KML also has 1355 Point label Placemarks which are correctly skipped)"
    )
    assert (
        min(elevations) == 267.0
    ), f"Expected min elevation = 267.0, got {min(elevations)}"
    assert (
        max(elevations) == 298.0
    ), f"Expected max elevation = 298.0, got {max(elevations)}"
    assert all(
        len(c.points) >= 2 for c in contours
    ), "Some contours have fewer than 2 points!"

    print("\nAll assertions passed ✓")
    print("Parser is working correctly against the real fixture.")


if __name__ == "__main__":
    main()
