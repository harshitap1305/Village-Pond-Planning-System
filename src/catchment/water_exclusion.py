"""
Orchestrates the OSM water exclusion mask for a single analysis run.

Public interface: :func:`build_water_exclusion_mask`.

Call chain:
  1. Check in-memory cache (keyed by rounded WGS84 bbox).
  2. Query Overpass (with mirror failover + retry) to get raw OSM elements.
  3. Parse elements → WGS84 Shapely geometries.
  4. Reproject to DEM metric CRS + buffer linear waterways.
  5. Rasterize onto the DEM boolean grid.
  6. On any Overpass failure → fall back to flat-area heuristic.
"""

import logging
import time

import numpy as np

from src.external.water.osm_client import OsmApiClient, OsmUnavailableError
from src.external.water.water_source import build_water_geometries, reproject_and_buffer
from src.geometry.water_mask import flat_area_heuristic_mask, rasterize_water_mask
from src.schemas.water import WaterMaskResult

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory cache: {rounded_bbox_tuple: (osm_xml_string, timestamp)}
# A 24-h TTL is enforced using the timestamp.
# ---------------------------------------------------------------------------
_water_cache: dict[tuple, tuple[str, float]] = {}


def _bbox_cache_key(south: float, west: float, north: float, east: float) -> tuple:
    """Round to 4 decimal places (~11 m) so nearby queries reuse the same entry."""
    return (round(south, 4), round(west, 4), round(north, 4), round(east, 4))


def build_water_exclusion_mask(
    dem,
    dem_bbox_wgs84: tuple[float, float, float, float],
    slope_deg: np.ndarray,
    settings,
) -> WaterMaskResult:
    """
    Build a boolean water exclusion mask for the given DEM.

    Args:
        dem:             DEM object (has ``.array``, ``.origin_x``, ``.origin_y``,
                         ``.cell_size``, ``.crs`` attributes).
        dem_bbox_wgs84:  ``(south, west, north, east)`` in WGS84 decimal degrees.
        slope_deg:       Slope array in degrees — used only by the fallback heuristic.
        settings:        The global ``Settings`` instance.

    Returns:
        :class:`WaterMaskResult` with the mask and provenance metadata.
    """
    south, west, north, east = dem_bbox_wgs84
    cache_key = _bbox_cache_key(south, west, north, east)
    now = time.monotonic()

    try:
        # ── 1. Cache lookup ──────────────────────────────────────────────────
        cached_entry = _water_cache.get(cache_key)
        if cached_entry is not None:
            response_xml, ts = cached_entry
            if now - ts < settings.water_cache_ttl_s:
                _log.info("OSM API cache hit for bbox %s", cache_key)
            else:
                _log.info("OSM API cache expired for bbox %s — re-querying", cache_key)
                cached_entry = None

        if cached_entry is None:
            # ── 2. OSM query (tenacity retry) ─────────
            client = OsmApiClient(
                endpoint=settings.osm_api_url,
                timeout_s=settings.osm_timeout_s,
            )
            _log.info("Querying OSM API for water features in bbox %s", cache_key)
            response_xml = client.query_water_features(south, west, north, east)
            _water_cache[cache_key] = (response_xml, now)

        # ── 3. Parse elements → WGS84 geometries ────────────────────────────
        geometries = build_water_geometries(response_xml, settings)
        _log.info("OSM: %d water features found", len(geometries))

        # ── 4. Reproject + buffer → metric-CRS polygons ──────────────────────
        epsg = int(dem.crs.split(":")[-1])
        buffered = reproject_and_buffer(geometries, settings, epsg)

        # ── 5. Rasterize → boolean DEM-grid mask ─────────────────────────────
        mask = rasterize_water_mask(buffered, dem)

        return WaterMaskResult(
            mask=mask,
            source="osm",
            feature_count=len(geometries),
        )

    except OsmUnavailableError as exc:
        _log.warning(
            "OSM API unavailable — falling back to flat-area heuristic. Reason: %s",
            exc,
        )
        mask = flat_area_heuristic_mask(slope_deg, dem.cell_size)
        return WaterMaskResult(
            mask=mask,
            source="flat_area_heuristic",
            feature_count=0,
        )
