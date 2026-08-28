"""
Converts boolean catchment masks to WGS84 Shapely Polygons.
"""

import numpy as np
from affine import Affine
from pyproj import Transformer
from rasterio.features import shapes as rasterio_shapes
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform
from shapely.ops import unary_union

from src.config import settings
from src.schemas.dem import DEM


def _reproject_geometry(geom: BaseGeometry, transformer: Transformer) -> BaseGeometry:
    """Helper to reproject any Shapely geometry using a pyproj Transformer."""
    return shapely_transform(transformer.transform, geom)


def mask_to_polygon(mask: np.ndarray, dem: DEM) -> BaseGeometry:
    """
    Converts a boolean catchment mask to a WGS84 Shapely Polygon.

    Args:
        mask: Boolean mask of the catchment.
        dem: The source DEM used for geotransform context.

    Returns:
        A Shapely Polygon (or MultiPolygon) in WGS84 coordinates.
    """
    # 1. Setup transform for vectorization (pixel -> UTM)
    transform = Affine(
        dem.cell_size, 0.0, dem.origin_x, 0.0, -dem.cell_size, dem.origin_y
    )
    uint_mask = mask.astype(np.uint8)

    # 2. Raster mask -> Shapely polygons (in UTM/metric CRS)
    polys = []
    for geom_dict, value in rasterio_shapes(
        uint_mask, mask=(uint_mask == 1), transform=transform
    ):
        if value == 1:
            polys.append(shape(geom_dict))

    if not polys:
        raise ValueError("Catchment mask produced no polygon geometry.")

    # 3. Merge fragments (handles non-contiguous masks)
    merged = unary_union(polys)

    # 4. Simplify to reduce vertex count for map rendering
    simplified = merged.simplify(tolerance=settings.polygon_simplify_tolerance_m)

    # 5. Reproject UTM -> WGS84
    transformer = Transformer.from_crs(dem.crs, "EPSG:4326", always_xy=True)
    reprojected = _reproject_geometry(simplified, transformer)

    return reprojected
