"""
Rasterize buffered water geometries onto the DEM grid (boolean water mask)
and provide the flat-area-heuristic fallback used when OSM is unavailable.
"""

import logging

import numpy as np
from affine import Affine
from rasterio.features import rasterize
from scipy import ndimage
from shapely.ops import unary_union

_log = logging.getLogger(__name__)


def rasterize_water_mask(buffered_geoms: list, dem) -> np.ndarray:
    """
    Burn buffered water polygons into a boolean grid matching the DEM.

    Args:
        buffered_geoms: Metric-CRS Shapely polygons from
                        :func:`src.external.water.water_source.reproject_and_buffer`.
        dem:            DEM object with ``.array``, ``.origin_x``, ``.origin_y``,
                        ``.cell_size`` attributes.

    Returns:
        Boolean numpy array — ``True`` where a cell overlaps a water feature.
    """
    if not buffered_geoms:
        _log.debug("No water geometries to rasterize — returning empty mask")
        return np.zeros(dem.array.shape, dtype=bool)

    merged = unary_union(buffered_geoms)

    # Affine transform: (cell_size, 0, origin_x_left_edge, 0, -cell_size, origin_y_top_edge)
    # origin_x / origin_y in the DEM are the top-left corner of the grid in metric CRS.
    aff = Affine(dem.cell_size, 0, dem.origin_x, 0, -dem.cell_size, dem.origin_y)

    mask = rasterize(
        [(merged, 1)],
        out_shape=dem.array.shape,
        transform=aff,
        fill=0,
        dtype="uint8",
    )
    result = mask.astype(bool)
    _log.debug(
        "Water mask: %d / %d cells masked (%.2f%%)",
        result.sum(),
        result.size,
        100.0 * result.sum() / result.size,
    )
    return result


def flat_area_heuristic_mask(
    slope_deg: np.ndarray,
    cell_size: float,
    slope_threshold_deg: float = 0.5,
    min_area_ha: float = 1.0,
) -> np.ndarray:
    """
    Flag large contiguous near-flat regions as probable existing water bodies.

    This is the fallback used **only when Overpass is completely unavailable**.
    It is intentionally conservative (high threshold) to avoid flagging gently-
    graded agricultural fields. Its limitations are documented in the API response
    via ``water_exclusion.source == "flat_area_heuristic"``.

    Args:
        slope_deg:            Slope array in degrees (same shape as DEM).
        cell_size:            DEM cell size in metres.
        slope_threshold_deg:  Cells below this slope are "flat" (default 0.5°).
        min_area_ha:          Minimum contiguous flat region to flag (default 1 ha).

    Returns:
        Boolean numpy array — ``True`` where a large flat region was detected.
    """
    flat = slope_deg <= slope_threshold_deg
    labeled, n = ndimage.label(flat)
    min_cells = int((min_area_ha * 10_000) / (cell_size**2))

    mask = np.zeros_like(flat, dtype=bool)
    for i in range(1, n + 1):
        region = labeled == i
        if region.sum() >= min_cells:
            mask |= region

    _log.debug(
        "Flat-area heuristic: %d regions >= %.1f ha; mask sum=%d",
        n,
        min_area_ha,
        mask.sum(),
    )
    return mask
