"""
Manual debug script: build and plot DEM from sample KML fixture.

Run: python scripts/debug_plot_dem.py
Saves: /tmp/dem_debug.png
"""

import matplotlib

matplotlib.use("Agg")
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from src.dem.builder import build_dem, validate_dem
from src.geometry.pointcloud import build_point_cloud
from src.terrain.kml_source import KMLTerrainSource
from src.terrain.validators import validate_contours

FIXTURE = Path("tests/fixtures/contours_1m.kml")
OUT = Path("/tmp/dem_debug.png")


def main() -> None:
    print("Parsing KML...")
    contours = KMLTerrainSource.from_file(FIXTURE).extract_contours()
    validate_contours(contours)
    print(
        f"  {len(contours)} contours, elevation {min(c.elevation for c in contours):.0f}-{max(c.elevation for c in contours):.0f} m"
    )

    print("Building point cloud...")
    pc = build_point_cloud(contours)
    print(f"  {len(pc.x)} points -> CRS {pc.crs}")

    print("Interpolating DEM (cell_size=2m)...")
    dem = build_dem(pc, cell_size=2.0)
    validate_dem(dem, contours)
    print(
        f"  DEM shape: {dem.shape}, elev range: {np.nanmin(dem.array):.1f}-{np.nanmax(dem.array):.1f} m"
    )

    print(f"Saving plot to {OUT}...")
    fig, ax = plt.subplots(figsize=(10, 10))
    img = ax.imshow(
        dem.array,
        cmap="terrain",
        origin="upper",
        vmin=np.nanmin(dem.array),
        vmax=np.nanmax(dem.array),
    )
    plt.colorbar(img, ax=ax, label="Elevation (m)")
    ax.set_title("Interpolated DEM - Village Pond Planning System")
    ax.set_xlabel("Column (x 2m)")
    ax.set_ylabel("Row (x 2m, N->S)")
    plt.tight_layout()
    plt.savefig(OUT, dpi=150)
    print("Done.")


if __name__ == "__main__":
    main()
