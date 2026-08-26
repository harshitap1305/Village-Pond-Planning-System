"""
Terrain data schemas — the core data contract between ingestion (Module 2)
and all downstream geospatial processing (Modules 4-11).

ContourLine is the single type that crosses the boundary between
"reading a file" and "doing geospatial work". Everything downstream
receives List[ContourLine] and is completely format-agnostic.
"""

import math
from typing import List, Tuple

from pydantic import BaseModel, field_validator


class ContourLine(BaseModel):
    """
    A single elevation contour line in WGS84 coordinates.

    Attributes:
        elevation: Height in metres above sea level.
                   Read from KML <name> tag for this file format.
        points:    Ordered list of (longitude, latitude) pairs in WGS84 / EPSG:4326.
                   NOT reprojected — reprojection to metric CRS happens in Module 4.
    """

    elevation: float
    points: List[Tuple[float, float]]  # (lon, lat) — WGS84

    @field_validator("elevation")
    @classmethod
    def elevation_must_be_finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError(f"Elevation must be a finite number, got {v!r}")
        return v

    @field_validator("points")
    @classmethod
    def must_have_at_least_two_points(
        cls, v: List[Tuple[float, float]]
    ) -> List[Tuple[float, float]]:
        """A contour line needs at least 2 points to define a segment."""
        if len(v) < 2:
            raise ValueError(f"ContourLine must have at least 2 points, got {len(v)}")
        return v
