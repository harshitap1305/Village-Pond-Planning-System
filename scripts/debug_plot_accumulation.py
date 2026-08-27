"""
Manual debug script: build and plot flow accumulation and stream network.

Run: PYTHONPATH=. python scripts/debug_plot_accumulation.py
Saves: /tmp/dem_accumulation_debug.png
"""

import matplotlib.pyplot as plt
import numpy as np

from src.dem.builder import build_dem
from src.dem.conditioning import fill_sinks
from src.geometry.pointcloud import build_point_cloud
from src.hydrology.flow_accumulation import (
    compute_flow_accumulation,
    top_accumulation_cells,
)
from src.hydrology.flow_direction import compute_flow_direction
from src.terrain.kml_source import KMLTerrainSource


def main():
    print("Reading KML...")
    source = KMLTerrainSource.from_file("tests/fixtures/contours_1m.kml")
    lines = source.extract_contours()

    print("Creating Point Cloud (UTM)...")
    pc = build_point_cloud(lines)

    print("Building raw DEM...")
    dem = build_dem(pc, cell_size=2.0)

    print("Filling sinks...")
    filled_dem = fill_sinks(dem)

    print("Computing Flow Direction (D8)...")
    fd = compute_flow_direction(filled_dem)

    print("Computing Flow Accumulation...")
    accum = compute_flow_accumulation(fd, filled_dem)

    print("Extracting top 90% drainage channels...")
    streams = top_accumulation_cells(accum, percentile=90.0)

    print("Plotting...")
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # Panel 1: Log Accumulation
    log_accum = np.log10(accum + 1)
    im1 = axes[0].imshow(log_accum, cmap="viridis")
    axes[0].set_title("Log(Flow Accumulation)")
    plt.colorbar(im1, ax=axes[0], label="log10(cells)")

    # Panel 2: Streams Mask
    axes[1].imshow(streams, cmap="Blues")
    axes[1].set_title("Top 10% Drainage Channels")

    plt.tight_layout()
    plt.savefig("/tmp/dem_accumulation_debug.png")
    print("Saved plot to /tmp/dem_accumulation_debug.png")
    print("Done.")


if __name__ == "__main__":
    main()
