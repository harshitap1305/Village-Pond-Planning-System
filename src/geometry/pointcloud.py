"""
Point cloud construction from contour lines.

build_point_cloud() is the single function that converts the WGS84 (lon/lat)
ContourLine objects from Module 2 into a metric PointCloud suitable for
DEM interpolation and all downstream hydrology.

Key design decisions:
  - CRS is auto-detected from the centroid (no hard-coded EPSG code).
  - De-duplication removes repeated coordinate pairs (some KML exporters
    repeat the closing vertex of a ring, which can bias interpolation).
  - pyproj.Transformer with always_xy=True ensures (lon, lat) -> (x, y)
    ordering regardless of the EPSG axis convention.
"""

from typing import List

import numpy as np
from pyproj import Transformer

from src.geometry.crs_utils import detect_utm_epsg
from src.schemas.geometry import PointCloud
from src.schemas.terrain import ContourLine


def build_point_cloud(contours: List[ContourLine]) -> PointCloud:
    """
    Convert a list of WGS84 contour lines into a projected metric PointCloud.

    Pipeline:
      1. Flatten all (lon, lat, elevation) triples from every contour vertex.
      2. Auto-detect UTM zone from the centroid of all points.
      3. Reproject every (lon, lat) -> (x, y) in metres using pyproj.
      4. De-duplicate coincident (x, y) pairs (keep first occurrence).
      5. Wrap in a PointCloud model.

    Args:
        contours: List of ContourLine objects.

    Returns:
        PointCloud with x, y in metres (UTM), z in metres elevation.

    Raises:
        ValueError: If contours is empty (no points to project).
    """
    lons, lats, elevs = [], [], []
    for contour in contours:
        for lon, lat in contour.points:
            lons.append(lon)
            lats.append(lat)
            elevs.append(contour.elevation)

    if not lons:
        raise ValueError(
            "Cannot build PointCloud: no coordinate points found in contours."
        )

    centroid_lon = float(np.mean(lons))
    centroid_lat = float(np.mean(lats))
    epsg = detect_utm_epsg(centroid_lon, centroid_lat)
    target_crs = f"EPSG:{epsg}"

    # always_xy=True forces (lon, lat) input order. Without this, some CRSes default to (lat, lon)
    transformer = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
    xs, ys = transformer.transform(lons, lats)

    seen: dict[tuple, int] = {}
    unique_xs, unique_ys, unique_zs = [], [], []

    for x, y, z in zip(xs, ys, elevs):
        key = (round(x, 3), round(y, 3))
        if key not in seen:
            seen[key] = len(unique_xs)
            unique_xs.append(float(x))
            unique_ys.append(float(y))
            unique_zs.append(float(z))

    return PointCloud(x=unique_xs, y=unique_ys, z=unique_zs, crs=target_crs)
