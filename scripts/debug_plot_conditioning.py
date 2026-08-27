"""
Manual debug script: plot sink-filled DEM and slope.

Run: python scripts/debug_plot_conditioning.py
Saves: /tmp/dem_conditioning_debug.png
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from src.dem.builder import build_dem, validate_dem
from src.dem.conditioning import fill_sinks
from src.dem.slope import compute_slope_deg
from src.geometry.pointcloud import build_point_cloud
from src.terrain.kml_source import KMLTerrainSource
from src.terrain.validators import validate_contours

FIXTURE = Path("tests/fixtures/contours_1m.kml")
OUT = Path("/tmp/dem_conditioning_debug.png")


def main() -> None:
    print("Building raw DEM...")
    contours = KMLTerrainSource.from_file(FIXTURE).extract_contours()
    validate_contours(contours)
    pc = build_point_cloud(contours)
    dem = build_dem(pc, cell_size=2.0)
    validate_dem(dem, contours)

    print("Filling sinks...")
    filled_dem = fill_sinks(dem)

    # Calculate difference to see where pits were filled
    diff = filled_dem.array - dem.array
    max_fill = np.nanmax(diff)
    print(f"  Max fill depth: {max_fill:.2f} m")

    print("Computing slope...")
    slope = compute_slope_deg(filled_dem)
    print(f"  Slope range: {np.nanmin(slope):.1f} - {np.nanmax(slope):.1f} degrees")

    print(f"Saving plot to {OUT}...")
    fig, axes = plt.subplots(1, 2, figsize=(16, 8))

    # Plot 1: Fill Depth (where pits were)
    img1 = axes[0].imshow(diff, cmap="Reds", origin="upper")
    plt.colorbar(img1, ax=axes[0], label="Fill Depth (m)")
    axes[0].set_title(f"Sink Filling Depth (Max: {max_fill:.2f}m)")

    # Plot 2: Slope
    img2 = axes[1].imshow(slope, cmap="viridis", origin="upper", vmin=0, vmax=30)
    plt.colorbar(img2, ax=axes[1], label="Slope (degrees)")
    axes[1].set_title("Topographic Slope")

    for ax in axes:
        ax.set_xlabel("Column (x 2m)")
        ax.set_ylabel("Row (x 2m, N->S)")

    plt.tight_layout()
    plt.savefig(OUT, dpi=150)
    print("Done.")


if __name__ == "__main__":
    main()
