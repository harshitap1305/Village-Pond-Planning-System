"""
Flow accumulation algorithm.

Traces the D8 flow direction network to calculate the total number of
upstream cells draining into each cell.
"""

import numpy as np
from affine import Affine
from pysheds.grid import Grid
from pysheds.sview import Raster
from pysheds.view import ViewFinder

from src.schemas.dem import DEM


def compute_flow_accumulation(flow_dir: np.ndarray, dem: DEM) -> np.ndarray:
    """
    Compute flow accumulation from a D8 flow direction array.

    Args:
        flow_dir: 2D array of D8 direction codes (from Module 7).
        dem: The corresponding DEM (used for spatial properties).

    Returns:
        2D integer array (same shape) where each cell contains the count
        of all upstream cells draining into it (plus 1 for itself).
    """
    # 1. Setup spatial properties for pysheds
    # IMPORTANT: nodata must be 0 (not -9999.0) because flow direction is int32
    # and -9999.0 is not representable in int32. Code 0 already means "sink".
    transform = Affine(
        dem.cell_size, 0.0, dem.origin_x, 0.0, -dem.cell_size, dem.origin_y
    )
    vf = ViewFinder(affine=transform, shape=dem.array.shape, nodata=0, crs=dem.crs)

    # 2. Wrap the numpy array in a pysheds Raster
    # Ensure flow_dir is a supported integer type for pysheds
    fd_raster = Raster(flow_dir.astype(np.int32), viewfinder=vf)

    # 3. Initialize Grid
    grid = Grid()
    grid.viewfinder = vf

    # 4. Compute accumulation with a monkeypatch for a known pysheds bug in v0.3.x.
    # When cells flow out-of-bounds, pysheds routes them to a virtual sink node (index = fdir.size).
    # This causes np.bincount to return an array of size fdir.size + 1, causing an IndexError
    # when it's used to mask startnodes. We patch bincount to strictly truncate to minlength.
    orig_bincount = np.bincount

    def patched_bincount(x, weights=None, minlength=0):
        res = orig_bincount(x, weights=weights, minlength=minlength)
        if minlength > 0 and len(res) > minlength:
            return res[:minlength]
        return res

    np.bincount = patched_bincount
    try:
        accum_raster = grid.accumulation(fdir=fd_raster)
    finally:
        np.bincount = orig_bincount

    # 5. Extract the numpy array
    return np.asarray(accum_raster).astype(np.int32)


def top_accumulation_cells(accum: np.ndarray, percentile: float = 90.0) -> np.ndarray:
    """
    Identify the cells representing the major drainage channels.

    Args:
        accum: The flow accumulation array.
        percentile: The threshold (e.g., 90.0 means the top 10% highest cells).

    Returns:
        A boolean mask (same shape) where True indicates high accumulation.
    """
    threshold = np.percentile(accum, percentile)
    return accum >= threshold
