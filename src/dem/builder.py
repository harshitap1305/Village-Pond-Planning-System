"""
DEM construction via spatial interpolation of a scattered point cloud.

build_dem() takes the metric PointCloud from Module 4 and rasterizes it
into a regular elevation grid using scipy.interpolate.griddata.
"""

import numpy as np
from scipy.interpolate import griddata

from src.config import settings
from src.schemas.dem import DEM
from src.schemas.geometry import PointCloud
from src.schemas.terrain import ContourLine


def build_dem(
    pc: PointCloud,
    cell_size: float | None = None,
) -> DEM:
    """
    Interpolate a PointCloud into a regular DEM grid.
    """
    if cell_size is None:
        cell_size = settings.cell_size_m

    buf = settings.dem_buffer_cells * cell_size

    x_min = min(pc.x) - buf
    x_max = max(pc.x) + buf
    y_min = min(pc.y) - buf
    y_max = max(pc.y) + buf

    x_coords = np.arange(x_min, x_max + cell_size, cell_size)
    y_coords = np.arange(y_max, y_min - cell_size, -cell_size)
    xi, yi = np.meshgrid(x_coords, y_coords)

    points = np.column_stack([pc.x, pc.y])
    values = np.array(pc.z)

    # Pass 1: Linear interpolation
    grid_linear = griddata(points, values, (xi, yi), method="linear")

    # Pass 2: Nearest-neighbour fill for border NaN cells
    nan_mask = np.isnan(grid_linear)
    if nan_mask.any():
        grid_nearest = griddata(points, values, (xi, yi), method="nearest")
        grid_linear[nan_mask] = grid_nearest[nan_mask]

    return DEM(
        array=grid_linear.astype(np.float32),
        origin_x=float(x_min),
        origin_y=float(y_max),
        cell_size=cell_size,
        crs=pc.crs,
    )


def validate_dem(dem: DEM, contours: list[ContourLine]) -> None:
    """
    Sanity-check the DEM against the source contour elevation range.
    """
    source_elevs = [c.elevation for c in contours]
    src_min = min(source_elevs)
    src_max = max(source_elevs)
    elev_range = src_max - src_min

    tolerance = max(elev_range * 0.05, 1.0)

    dem_min = float(np.nanmin(dem.array))
    dem_max = float(np.nanmax(dem.array))

    if dem_min < src_min - tolerance:
        raise ValueError(
            f"DEM minimum elevation {dem_min:.1f}m is below source minimum "
            f"{src_min:.1f}m (tolerance: {tolerance:.1f}m). "
            "Possible interpolation blow-up at edges."
        )
    if dem_max > src_max + tolerance:
        raise ValueError(
            f"DEM maximum elevation {dem_max:.1f}m exceeds source maximum "
            f"{src_max:.1f}m (tolerance: {tolerance:.1f}m). "
            "Possible interpolation blow-up at edges."
        )
