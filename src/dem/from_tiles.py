"""
DEM builder that downloads free SRTM elevation data from AWS Terrarium tiles.

Instead of requiring a KML/KMZ contour upload, this module accepts a lat/lon
bounding box and downloads pre-processed SRTM elevation tiles directly from
AWS's public Open Data programme — no API key or account required.

Data source: AWS Elevation Tiles (Terrarium format)
  URL:        https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png
  Format:     256×256 PNG, RGB-encoded elevation
  Resolution: zoom 12 → ~38 m/pixel;  zoom 13 → ~19 m/pixel
  Coverage:   Global
  Licence:    Public Domain (SRTM / NED derivatives)

Decoding formula (Mapzen Terrarium spec):
  elevation_m = (R × 256 + G + B / 256) − 32768

Accuracy note (for the technical report):
  Resolution is ~38 m/pixel at zoom 12, compared with 1–2 m/pixel from
  user-supplied KMZ contour maps. This is suitable for regional site selection
  but not for final embankment engineering. Precision is stated in the API
  response metadata and surfaced to the user in the front-end.
"""

from __future__ import annotations

import logging
import math
from io import BytesIO

import httpx
import numpy as np
from PIL import Image
from pyproj import Transformer

from src.schemas.dem import DEM

_log = logging.getLogger(__name__)

# ── Tile parameters ────────────────────────────────────────────────────────────
_BASE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium"
_ZOOM = 12  # ~38 m/pixel — good balance of resolution vs. tile count
_TILE_PX = 256  # pixels per tile side (standard slippy-map tile)
# Approximate ground resolution in metres at zoom 12 at the equator
# (actual resolution varies with latitude, but negligible for our use-case).
_APPROX_RES_M = 40_075_016.686 / (2**_ZOOM * _TILE_PX)  # ≈ 38.2 m


# ── Coordinate helpers ─────────────────────────────────────────────────────────


def _deg2tile(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    """Convert WGS84 (lat, lon) to slippy-map tile (x, y) at the given zoom."""
    lat_r = math.radians(lat)
    n = 2**zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int(
        (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n
    )
    return x, y


def _tile2deg(x: int, y: int, zoom: int) -> tuple[float, float]:
    """Return the NW corner (lat, lon) of slippy-map tile (x, y)."""
    n = 2**zoom
    lon = x / n * 360.0 - 180.0
    lat_r = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    lat = math.degrees(lat_r)
    return lat, lon


def _download_tile(client: httpx.Client, z: int, x: int, y: int) -> np.ndarray:
    """
    Download a single Terrarium tile and decode it to a float32 elevation array.

    Returns a (256, 256) float32 NumPy array in metres.
    Raises httpx.HTTPError on network failure.
    """
    url = f"{_BASE_URL}/{z}/{x}/{y}.png"
    resp = client.get(url, timeout=15.0)
    resp.raise_for_status()

    img = Image.open(BytesIO(resp.content)).convert("RGB")
    data = np.array(img, dtype=np.float32)
    r, g, b = data[:, :, 0], data[:, :, 1], data[:, :, 2]
    return (r * 256.0 + g + b / 256.0) - 32768.0


# ── Public interface ───────────────────────────────────────────────────────────


def build_dem_from_bbox(
    south: float,
    west: float,
    north: float,
    east: float,
) -> DEM:
    """
    Build a DEM by downloading and stitching Terrarium elevation tiles.

    The returned DEM uses a UTM CRS automatically selected for the bounding
    box centre, matching the projection used by the existing KML pipeline.
    This means all downstream modules (fill_sinks, find_candidates, etc.) work
    identically on this DEM without modification.

    Args:
        south: Southern latitude boundary (WGS84 decimal degrees).
        west:  Western longitude boundary (WGS84 decimal degrees).
        north: Northern latitude boundary (WGS84 decimal degrees).
        east:  Eastern longitude boundary (WGS84 decimal degrees).

    Returns:
        A :class:`~src.schemas.dem.DEM` object ready for the analysis pipeline.

    Raises:
        httpx.HTTPError: If any tile download fails.
        ValueError:      If the bounding box is degenerate.
    """
    if north <= south or east <= west:
        raise ValueError(
            f"Degenerate bounding box: south={south}, north={north}, "
            f"west={west}, east={east}"
        )

    # ── Tile range ────────────────────────────────────────────────────────────
    # NW corner → min tile coords;  SE corner → max tile coords
    x_min_t, y_min_t = _deg2tile(north, west, _ZOOM)
    x_max_t, y_max_t = _deg2tile(south, east, _ZOOM)

    n_x = x_max_t - x_min_t + 1
    n_y = y_max_t - y_min_t + 1
    total_tiles = n_x * n_y

    _log.info(
        "Terrarium tile download: zoom=%d, x=%d–%d, y=%d–%d (%d tiles)",
        _ZOOM,
        x_min_t,
        x_max_t,
        y_min_t,
        y_max_t,
        total_tiles,
    )

    # ── Download and stitch ───────────────────────────────────────────────────
    stitched = np.zeros((n_y * _TILE_PX, n_x * _TILE_PX), dtype=np.float32)

    with httpx.Client() as client:
        for j, ty in enumerate(range(y_min_t, y_max_t + 1)):
            for i, tx in enumerate(range(x_min_t, x_max_t + 1)):
                tile_arr = _download_tile(client, _ZOOM, tx, ty)
                row0 = j * _TILE_PX
                col0 = i * _TILE_PX
                stitched[row0 : row0 + _TILE_PX, col0 : col0 + _TILE_PX] = tile_arr

    # ── Georeference the stitched raster ─────────────────────────────────────
    # Top-left corner of the tile mosaic in WGS84
    tile_north, tile_west = _tile2deg(x_min_t, y_min_t, _ZOOM)
    tile_south, tile_east = _tile2deg(x_max_t + 1, y_max_t + 1, _ZOOM)

    # Pixel size in degrees
    deg_per_px_lat = (tile_north - tile_south) / (n_y * _TILE_PX)
    deg_per_px_lon = (tile_east - tile_west) / (n_x * _TILE_PX)

    # ── Clip to requested bounding box (pixel-level) ──────────────────────────
    row_start = max(0, int((tile_north - north) / deg_per_px_lat))
    row_end = min(stitched.shape[0], int((tile_north - south) / deg_per_px_lat) + 1)
    col_start = max(0, int((west - tile_west) / deg_per_px_lon))
    col_end = min(stitched.shape[1], int((east - tile_west) / deg_per_px_lon) + 1)

    clipped = stitched[row_start:row_end, col_start:col_end]
    _log.info(
        "Stitched raster: %dx%d → clipped to bbox: %dx%d",
        stitched.shape[1],
        stitched.shape[0],
        clipped.shape[1],
        clipped.shape[0],
    )

    # ── Project to UTM ────────────────────────────────────────────────────────
    # Pick the UTM zone for the centre of the bounding box — same logic as
    # the existing KML pipeline in geometry/pointcloud.py.
    centre_lon = (west + east) / 2.0
    centre_lat = (south + north) / 2.0
    utm_zone = int((centre_lon + 180) / 6) + 1
    utm_epsg = 32600 + utm_zone if centre_lat >= 0 else 32700 + utm_zone
    crs_str = f"EPSG:{utm_epsg}"

    to_utm = Transformer.from_crs("EPSG:4326", crs_str, always_xy=True)

    # Compute the clipped raster's NW corner lat/lon
    nw_lat = tile_north - row_start * deg_per_px_lat
    nw_lon = tile_west + col_start * deg_per_px_lon

    # Convert the four corners to UTM to get origin_x, origin_y and cell_size_m
    origin_x, origin_y = to_utm.transform(nw_lon, nw_lat)

    # Cell size in metres — average of x and y directions
    # (at moderate latitudes these differ by < 1%)
    se_lon = nw_lon + clipped.shape[1] * deg_per_px_lon
    se_lat = nw_lat - clipped.shape[0] * deg_per_px_lat
    se_x, se_y = to_utm.transform(se_lon, se_lat)

    cell_size_x = abs(se_x - origin_x) / clipped.shape[1]
    cell_size_y = abs(origin_y - se_y) / clipped.shape[0]
    cell_size_m = (cell_size_x + cell_size_y) / 2.0

    _log.info(
        "DEM from tiles: %dx%d, cell_size=%.1fm, CRS=%s",
        clipped.shape[1],
        clipped.shape[0],
        cell_size_m,
        crs_str,
    )

    return DEM(
        array=clipped,
        origin_x=origin_x,
        origin_y=origin_y,
        cell_size=cell_size_m,
        crs=crs_str,
    )
