"""
DEM conditioning: removing artificial sinks (depressions) so water can flow.

This module uses pysheds to fill pits in the interpolated DEM, ensuring
hydrological connectivity across the entire terrain surface.
"""

import numpy as np
from affine import Affine
from pysheds.grid import Grid
from pysheds.sview import Raster
from pysheds.view import ViewFinder

from src.schemas.dem import DEM


def fill_sinks(dem: DEM) -> DEM:
    """
    Fill artificial depressions in the DEM using the pysheds library.

    Args:
        dem: The raw interpolated DEM.

    Returns:
        A new DEM object with the same shape/geotransform, where all
        pits have been filled to match their lowest boundary elevation.
    """
    # 1. Create a ViewFinder mapping array space to geographic space
    transform = Affine(
        dem.cell_size, 0.0, dem.origin_x, 0.0, -dem.cell_size, dem.origin_y
    )
    vf = ViewFinder(
        affine=transform, shape=dem.array.shape, nodata=dem.nodata, crs=dem.crs
    )

    # 2. Wrap the numpy array in a pysheds Raster
    raster = Raster(dem.array, viewfinder=vf)

    # 3. Initialize Grid and set its viewfinder to match the raster
    grid = Grid()
    grid.viewfinder = vf

    # 4. Fill depressions
    filled_raster = grid.fill_depressions(raster)

    # 5. Extract the numpy array
    filled_array = np.asarray(filled_raster).astype(np.float32)

    return DEM(
        array=filled_array,
        origin_x=dem.origin_x,
        origin_y=dem.origin_y,
        cell_size=dem.cell_size,
        crs=dem.crs,
        nodata=dem.nodata,
    )
