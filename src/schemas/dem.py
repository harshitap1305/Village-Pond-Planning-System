"""
DEM (Digital Elevation Model) schema.

A DEM is the central data structure for all terrain analysis. It is a
regular 2D grid of elevation values in a metric CRS. Everything downstream
(sink filling, slope, flow direction, accumulation) operates on a DEM.

The geotransform fields (origin_x, origin_y, cell_size) encode where the
grid is located in the projected CRS — needed to convert (row, col) indices
back to real-world (x, y) coordinates, which is essential in Module 9-11
for returning lat/lon coordinates to the API caller.
"""

from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, field_validator


class DEM(BaseModel):
    """
    A 2D elevation grid in a projected metric CRS.

    Attributes:
        array:      2D numpy array of elevations (float32). Shape: (rows, cols).
                    Rows increase Southward (top = max northing).
        origin_x:   Easting of the top-left corner in metres.
        origin_y:   Northing of the top-left corner in metres.
        cell_size:  Width/height of each cell in metres (square cells only).
        crs:        EPSG code string matching the PointCloud CRS.
        nodata:     Sentinel value for missing/invalid cells. Default -9999.0.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    array: Any
    origin_x: float
    origin_y: float
    cell_size: float
    crs: str
    nodata: float = -9999.0

    @field_validator("array")
    @classmethod
    def must_be_2d_numpy_array(cls, v: Any) -> np.ndarray:
        if not isinstance(v, np.ndarray):
            raise ValueError(f"array must be a numpy ndarray, got {type(v).__name__}")
        if v.ndim != 2:
            raise ValueError(f"array must be 2D, got {v.ndim}D array")
        return v

    @field_validator("cell_size")
    @classmethod
    def cell_size_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"cell_size must be positive, got {v}")
        return v

    @property
    def rows(self) -> int:
        return self.array.shape[0]

    @property
    def cols(self) -> int:
        return self.array.shape[1]

    @property
    def shape(self) -> tuple[int, int]:
        return self.array.shape
