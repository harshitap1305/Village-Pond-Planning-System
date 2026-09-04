"""
Orchestrates the OSM built-up land exclusion mask for a single analysis run.

Public interface: :func:`build_land_exclusion_mask`.

SPATIAL SEMANTICS (critical for correct pond siting):
  The mask produced here marks cells that are structurally or legally
  incompatible with pond excavation (buildings, residential areas, etc.).
  It is applied **only to the bowl footprint** (depression cells) inside
  ``find_candidates`` — NOT to the upstream catchment area.

  Rationale: built-up land in the catchment is acceptable and even increases
  the runoff coefficient (paved/roof surfaces shed more water than bare soil).
  Only the physical pond site and the embankment location must be free.

Call chain:
  1. Read OSM XML from the in-memory cache populated by water_exclusion
     (same bbox key, same TTL). No additional HTTP call is made.
  2. Parse building/landuse polygons from the XML.
  3. Reproject to DEM metric CRS + apply builtup_buffer_margin_m safety buffer.
  4. Rasterize onto the DEM boolean grid.
  5. On any failure → return an all-False mask (fail-open: no constraint applied).
"""

import logging

import numpy as np
import pyproj
from shapely.ops import transform as shp_transform

from src.catchment.water_exclusion import _bbox_cache_key, _water_cache
from src.external.water.water_source import build_builtup_geometries
from src.geometry.water_mask import rasterize_water_mask
from src.schemas.water import LandMaskResult

_log = logging.getLogger(__name__)


def _unavailable_mask(dem) -> LandMaskResult:
    """Return a fail-open all-False mask when built-up data is unavailable."""
    return LandMaskResult(
        mask=np.zeros(dem.array.shape, dtype=bool),
        source="unavailable",
        feature_count=0,
    )


def build_land_exclusion_mask(
    dem,
    dem_bbox_wgs84: tuple[float, float, float, float],
    settings,
) -> LandMaskResult:
    """
    Build a boolean built-up land exclusion mask for the given DEM.

    Reuses the OSM XML already cached by :func:`build_water_exclusion_mask`
    for the same bounding box — no new Overpass request is made.

    Args:
        dem:             DEM object (has ``.array``, ``.origin_x``,
                         ``.origin_y``, ``.cell_size``, ``.crs`` attributes).
        dem_bbox_wgs84:  ``(south, west, north, east)`` in WGS84 decimal degrees.
        settings:        The global ``Settings`` instance.

    Returns:
        :class:`LandMaskResult` with the boolean mask and provenance metadata.
        The mask is all-False (fail-open) if OSM data is unavailable.
    """
    south, west, north, east = dem_bbox_wgs84
    cache_key = _bbox_cache_key(south, west, north, east)

    # ── 1. Read from water_exclusion cache (no HTTP call) ─────────────────────
    cached_entry = _water_cache.get(cache_key)
    if cached_entry is None:
        _log.warning(
            "OSM XML not yet cached for bbox %s — built-up exclusion skipped "
            "(water_exclusion must run first). Returning fail-open mask.",
            cache_key,
        )
        return _unavailable_mask(dem)

    response_xml, _ts = cached_entry
    _log.info("Built-up land: reusing cached OSM XML for bbox %s", cache_key)

    # ── 2. Parse built-up polygons from the XML ───────────────────────────────
    try:
        geometries = build_builtup_geometries(response_xml)
    except Exception as exc:  # noqa: BLE001 — intentional broad catch, fail-open
        _log.warning(
            "Built-up geometry parsing failed (%s) — returning fail-open mask.", exc
        )
        return _unavailable_mask(dem)

    _log.info("OSM built-up: %d polygon features found in bbox", len(geometries))

    if not geometries:
        # No built-up features in this bbox — all-False mask, source=osm is correct.
        return LandMaskResult(
            mask=np.zeros(dem.array.shape, dtype=bool),
            source="osm",
            feature_count=0,
        )

    # ── 3. Reproject + buffer into metric CRS ────────────────────────────────
    # Built-up polygons are reprojected from WGS84 into the DEM's metric CRS,
    # then buffered by builtup_buffer_margin_m (smaller than water margin, since
    # building edges are precise hard boundaries unlike diffuse waterway banks).
    try:
        epsg = int(dem.crs.split(":")[-1])
        transformer = pyproj.Transformer.from_crs(
            "EPSG:4326", f"EPSG:{epsg}", always_xy=True
        )

        def _project(x, y):
            return transformer.transform(x, y)

        buffered = []
        for poly in geometries:
            poly_m = shp_transform(_project, poly)
            poly_m = poly_m.buffer(settings.builtup_buffer_margin_m)
            if not poly_m.is_empty:
                buffered.append(poly_m)

    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "Built-up reproject/buffer failed (%s) — returning fail-open mask.", exc
        )
        return _unavailable_mask(dem)

    # ── 4. Rasterize onto the DEM grid ───────────────────────────────────────
    try:
        mask = rasterize_water_mask(buffered, dem)
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "Built-up rasterization failed (%s) — returning fail-open mask.", exc
        )
        return _unavailable_mask(dem)

    _log.info(
        "Built-up land mask: %d / %d cells masked (%.2f%%)",
        int(mask.sum()),
        mask.size,
        100.0 * mask.sum() / mask.size,
    )

    return LandMaskResult(
        mask=mask,
        source="osm",
        feature_count=len(geometries),
    )
