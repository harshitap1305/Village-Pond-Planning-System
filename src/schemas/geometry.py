"""
Geometry schemas — typed containers for projected point data.

PointCloud holds the 3D point representation of a terrain surface
after reprojection from WGS84 (lon/lat degrees) into a local metric
CRS (UTM). All downstream modules (DEM builder, slope, flow, metrics)
consume this object — they never touch raw ContourLine coordinates.
"""

from typing import List

from pydantic import BaseModel, model_validator


class PointCloud(BaseModel):
    """
    A collection of 3D terrain points in a projected metric CRS.

    Attributes:
        x:   Easting in metres (UTM)
        y:   Northing in metres (UTM)
        z:   Elevation in metres above sea level
        crs: EPSG code string, e.g. "EPSG:32644"

    All three lists must have the same length.
    """

    x: List[float]
    y: List[float]
    z: List[float]
    crs: str

    @model_validator(mode="after")
    def lists_must_have_equal_length(self) -> "PointCloud":
        if not (len(self.x) == len(self.y) == len(self.z)):
            raise ValueError(
                f"x, y, z must have equal length. "
                f"Got len(x)={len(self.x)}, len(y)={len(self.y)}, len(z)={len(self.z)}"
            )
        return self

    @model_validator(mode="after")
    def must_have_at_least_one_point(self) -> "PointCloud":
        if len(self.x) == 0:
            raise ValueError("PointCloud must contain at least one point.")
        return self
