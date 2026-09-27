"""
AnalysisService — orchestrates the full contour-to-catchment pipeline.

This class is the single entry point for the POST /analyzeContour endpoint.
It wires together all modules in the correct order. Every step is a pure
function unit-tested independently; this module is pure composition.

Pipeline order (15 steps):
  1. Validate file
  2. Parse KML/KMZ → ContourLines
  3. Validate contours (semantic checks)
  4. Build PointCloud
  5. Build raw DEM
  6. Fill sinks → filled_dem + slope
  6b. Build OSM water exclusion mask (fail-open)
  6c. Build OSM land exclusion mask (fail-open, reuses cached OSM XML)
  7. Candidate identification + conditioned routing (find_candidates)
  7b. Rainfall data for selected location (Open-Meteo → NASA POWER, fail-open)
  7c. Runoff estimation — SCS-CN method (fail-open if rainfall unavailable)
  7d. Pond dimensioning — IS 5477 storage reconciliation (fail-open)
  8. Watershed delineation for all candidates (multi-seed BFS)
  9. Polygonize catchment mask → WGS84 GeoJSON
  10. Compute catchment metrics + area consistency check
  11. Assemble and return AnalysisResult

Degradation chain:
  7b (rainfall) → 7c (runoff) → 7d (pond_design)
  Each step is fail-open: if it fails/is unavailable, its output is None
  and the pipeline continues. Machine-readable warning codes are recorded
  in AnalysisResult.warnings for each degraded step.

Note on flow routing:
  Steps 7+ use `conditioned_dem`/`flow_dir_cond`/`flow_accum_cond` returned
  by find_candidates as the single source of truth. There is no separate
  filled-DEM routing pass — that was removed in Module 9 v3 to ensure
  consistent catchment areas at every stage.
"""

import logging
import time

from pyproj import Transformer
from shapely.geometry import mapping

from src.catchment.candidates import find_candidates
from src.catchment.land_exclusion import build_land_exclusion_mask
from src.catchment.metrics import assert_area_consistency, compute_metrics
from src.catchment.polygonize import mask_to_polygon
from src.catchment.pond_design import PondDesign, recommend_pond_design
from src.catchment.rainfall_service import build_rainfall_stats
from src.catchment.water_exclusion import build_water_exclusion_mask
from src.config import settings
from src.dem.builder import build_dem, validate_dem
from src.dem.conditioning import fill_sinks
from src.dem.slope import compute_slope_deg
from src.geometry.pointcloud import build_point_cloud
from src.hydrology.runoff import RunoffEstimate, estimate_runoff
from src.hydrology.watershed import delineate_catchment
from src.schemas.response import (
    AnalysisMetadata,
    AnalysisResult,
    CatchmentResult,
    LandExclusionMetadata,
    WaterExclusionMetadata,
)
from src.terrain.kml_source import KMLTerrainSource
from src.terrain.validators import validate_contours, validate_file

_log = logging.getLogger(__name__)


class AnalysisService:
    """
    Stateless orchestrator for the village pond analysis pipeline.

    Instantiated once at application startup (module-level singleton).
    All state lives in the function arguments — safe for concurrent requests.
    """

    def run(
        self,
        file_bytes: bytes,
        filename: str,
        cell_size: float | None = None,
        pour_lat: float | None = None,
        pour_lon: float | None = None,
    ) -> AnalysisResult:
        """
        Run the full analysis pipeline on a KML/KMZ upload.

        Args:
            file_bytes: Raw bytes of the uploaded file.
            filename:   Original filename (used for format detection).
            cell_size:  Optional DEM cell size override in metres. Defaults to
                        settings.cell_size_m if None.
            pour_lat:   Optional latitude for manual pour-point override.
                        When provided (with pour_lon), the pipeline selects the
                        auto-detected candidate nearest to this coordinate instead
                        of always choosing candidates[0] (the highest-scoring one).
                        The snap is documented in AnalysisResult.warnings.
            pour_lon:   Optional longitude for manual pour-point override.
                        Must be provided together with pour_lat.

        Returns:
            AnalysisResult containing candidates, polygon, metrics, and
            hydrological outputs (rainfall, runoff, pond_design). Hydrological
            fields degrade gracefully — each is ``None`` if its data source
            failed; see ``AnalysisResult.warnings`` for machine-readable codes.

        Raises:
            TerrainParseError:    If the file cannot be parsed as KML/KMZ.
            InvalidGeometryError: If parsed contours fail geometry validation.
            FileTooLargeError:    If the file exceeds settings.max_upload_mb.
            ValueError:           If no pond candidates are found in the terrain.
        """
        # ── Timing — wall-clock start ─────────────────────────────────────────
        _t0 = time.perf_counter()

        # ── Warnings accumulator ──────────────────────────────────────────────
        # Populated throughout the pipeline when a step degrades gracefully.
        # Exposed as AnalysisResult.warnings for the frontend to display.
        _warnings: list[str] = []
        # ── 1. File-level validation ──────────────────────────────────────────
        _log.info(
            "Starting analysis: filename=%s size_bytes=%d", filename, len(file_bytes)
        )
        validate_file(filename, len(file_bytes))

        # ── 2. Parse KML/KMZ ─────────────────────────────────────────────────
        source = KMLTerrainSource(file_bytes, filename=filename)
        contours = source.extract_contours()
        _log.info("Parsed %d contour lines", len(contours))

        # ── 3. Semantic validation ────────────────────────────────────────────
        validate_contours(contours)

        # ── 4. Build point cloud ──────────────────────────────────────────────
        pc = build_point_cloud(contours)
        _log.info("Point cloud: %d points, CRS=%s", len(pc.x), pc.crs)

        # ── 5. Build raw DEM ──────────────────────────────────────────────────
        raw_dem = build_dem(pc, cell_size=cell_size)
        validate_dem(raw_dem, contours)
        _log.info(
            "DEM: %dx%d, cell_size=%.1fm, CRS=%s",
            raw_dem.rows,
            raw_dem.cols,
            raw_dem.cell_size,
            raw_dem.crs,
        )

        # ── 6. Fill sinks + compute slope ─────────────────────────────────────
        # slope is computed on filled_dem (no routing ambiguity there).
        # Filled_dem itself is passed to find_candidates for the depth diff.
        filled_dem = fill_sinks(raw_dem)
        slope = compute_slope_deg(filled_dem)
        _log.info("Sinks filled, slope computed")

        # ── 6b. Build OSM water exclusion mask ────────────────────────────────
        # Compute the WGS84 bounding box of the raw DEM so Overpass can query it.
        # The DEM origin is the top-left corner in metric CRS; we compute the
        # four corners and project them to WGS84 to get the tight bbox.
        epsg = int(raw_dem.crs.split(":")[-1])
        to_wgs = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
        # origin_x, origin_y is the top-left corner of the DEM in metric coords.
        x_min = raw_dem.origin_x
        y_min = raw_dem.origin_y - raw_dem.rows * raw_dem.cell_size  # bottom edge
        x_max = raw_dem.origin_x + raw_dem.cols * raw_dem.cell_size  # right edge
        y_max = raw_dem.origin_y  # top edge
        lon_min, lat_min = to_wgs.transform(x_min, y_min)
        lon_max, lat_max = to_wgs.transform(x_max, y_max)
        dem_bbox_wgs84 = (lat_min, lon_min, lat_max, lon_max)  # (S, W, N, E)

        water_result = build_water_exclusion_mask(
            dem=raw_dem,
            dem_bbox_wgs84=dem_bbox_wgs84,
            slope_deg=slope,
            settings=settings,
        )
        _log.info(
            "Water exclusion: source=%s features=%d masked_cells=%d",
            water_result.source,
            water_result.feature_count,
            int(water_result.mask.sum()),
        )

        # ── 6c. Build OSM built-up land exclusion mask ────────────────────────
        # Reuses the same OSM XML already cached by step 6b above — no new
        # HTTP call is made. The mask covers building footprints and residential/
        # commercial/industrial landuse polygons.
        # Applied only to the BOWL FOOTPRINT in find_candidates, NOT to the
        # upstream catchment — built-up land there is acceptable and even
        # increases the runoff coefficient.
        land_result = build_land_exclusion_mask(
            dem=raw_dem,
            dem_bbox_wgs84=dem_bbox_wgs84,
            settings=settings,
        )
        _log.info(
            "Land exclusion: source=%s features=%d masked_cells=%d",
            land_result.source,
            land_result.feature_count,
            int(land_result.mask.sum()),
        )

        # ── 7. Candidate identification + conditioned routing ─────────────────
        # find_candidates returns (candidates, conditioned_dem, flow_dir_cond,
        # flow_accum_cond). The conditioned routing outputs are the single source
        # of truth for ALL downstream steps — no separate routing pass needed.
        candidates, _cond_dem, flow_dir_cond, flow_accum_cond = find_candidates(
            raw_dem,
            filled_dem,
            water_mask=water_result.mask,
            land_mask=land_result.mask,
            slope_deg=slope,
        )
        if not candidates:
            raise ValueError(
                "No suitable pond candidates found in the provided terrain. "
                "The terrain may have no closed depressions larger than "
                "min_depression_area_sqm with catchment >= min_catchment_area_ha."
            )

        # ── Pour-point override: snap to nearest auto-detected candidate ──────
        # When a user specifies a manual pour point we do NOT use an arbitrary
        # DEM cell — we snap to the nearest existing candidate bowl. This keeps
        # all downstream calculations (watershed, pond design) grounded in a
        # real topographic depression, and is disclosed in the warnings list.
        if pour_lat is not None and pour_lon is not None:
            selected = _find_nearest_candidate(candidates, pour_lat, pour_lon)
            _warnings.append("pour_point_overridden")
            _log.info(
                "Pour-point override: user=(%.6f, %.6f) → snapped to candidate (%.6f, %.6f) score=%.4f",
                pour_lat,
                pour_lon,
                selected.lat,
                selected.lon,
                selected.score,
            )
        else:
            selected = candidates[0]

        _log.info(
            "Found %d candidates; selected lat=%.6f lon=%.6f score=%.4f",
            len(candidates),
            selected.lat,
            selected.lon,
            selected.score,
        )

        # ── 7b. Rainfall data for selected location ───────────────────────────
        # Called AFTER candidate selection — we need the lat/lon of the winning site.
        # Fail-open: if both APIs unavailable, rainfall=None, rest of pipeline unaffected.
        rainfall_stats = build_rainfall_stats(
            lat=selected.lat,
            lon=selected.lon,
            settings=settings,
        )
        if rainfall_stats is None:
            _warnings.append("rainfall_unavailable")
            _log.warning("Rainfall unavailable — warning added, pipeline continues.")

        # ── 7c. Runoff estimation for selected catchment ──────────────────────
        # Applies SCS-CN method to the 10-year monthly rainfall from Step 7b.
        #
        # builtup_fraction: fraction of DEM-bbox cells classified as built-up.
        # NOTE: This is an approximation — the land mask covers the full DEM
        # bounding box, not just the delineated catchment (which isn't available
        # until Step 8). In practice, the bias is small (<5% CN impact) and the
        # direction is safe: overestimating builtup → higher CN → higher runoff
        # estimate → conservative (safe) pond design.
        #
        # Fail-open: None if rainfall_stats is unavailable.
        runoff_estimate: RunoffEstimate | None = None
        if rainfall_stats is not None:
            builtup_fraction = (
                float(land_result.mask.sum()) / float(land_result.mask.size)
                if land_result.mask.size > 0
                else 0.0
            )
            try:
                runoff_estimate = estimate_runoff(
                    catchment_area_ha=selected.catchment_area_ha,
                    rainfall_stats=rainfall_stats,
                    builtup_fraction=builtup_fraction,
                    hsg=settings.default_hsg,
                    runoff_coefficient_fallback=settings.runoff_coefficient_fallback,
                )
                if runoff_estimate.method == "rational_annual_fallback":
                    _warnings.append("runoff_using_rational_fallback")
            except Exception as exc:  # noqa: BLE001
                _log.warning(
                    "Runoff estimation failed (%s) — runoff will be null.", exc
                )
                _warnings.append("runoff_unavailable")
        else:
            _warnings.append("runoff_unavailable")

        # ── 7d. Pond dimensioning ─────────────────────────────────────────────
        # Reconciles hydrological supply (Module 3) with topographic capacity
        # (Phase 2) to recommend physical pond dimensions.
        # Fail-open: None if runoff_estimate is unavailable.
        pond_design: PondDesign | None = None
        if runoff_estimate is not None:
            try:
                pond_design = recommend_pond_design(
                    runoff_estimate=runoff_estimate,
                    topographic_storage_m3=selected.estimated_storage_m3,
                    depression_area_ha=selected.depression_area_ha,
                    settings=settings,
                )
            except Exception as exc:  # noqa: BLE001
                _log.warning("Pond design failed (%s) — pond_design will be null.", exc)
                _warnings.append("pond_design_unavailable")
        else:
            _warnings.append("pond_design_unavailable")

        # ── 8 & 9. Watershed delineation & Polygonization for all candidates ──
        # NOTE on cache thread-safety: _rainfall_cache and the OSM cache in
        # water_exclusion.py are module-level dicts accessed from run_in_threadpool
        # threads. Python's GIL prevents dict corruption; the worst-case race
        # (two threads both miss cache simultaneously) causes a redundant API call,
        # not a correctness bug. No lock is needed for correctness.
        for cand in candidates:
            cand_mask = delineate_catchment(
                flow_dir_cond, seed_cells=cand.bowl_sink_rcs
            )
            cand_poly = mask_to_polygon(cand_mask, filled_dem)
            cand.catchment_polygon_geojson = mapping(cand_poly)

        # For the top candidate (selected_location), we also compute detailed metrics
        # and do the consistency check using its mask.
        mask = delineate_catchment(flow_dir_cond, seed_cells=selected.bowl_sink_rcs)
        polygon = mask_to_polygon(mask, filled_dem)
        _log.info(
            "Top catchment mask: %d cells, valid=%s", int(mask.sum()), polygon.is_valid
        )

        # ── 10. Compute metrics + area consistency check ───────────────────────
        metrics = compute_metrics(mask, filled_dem, slope)
        accum_sum = int(sum(flow_accum_cond[rc] for rc in selected.bowl_sink_rcs))
        assert_area_consistency(
            metrics, accum_sum, num_seeds=len(selected.bowl_sink_rcs)
        )
        _log.info(
            "Metrics: area_ha=%.4f, elev_mean=%.1f, slope_mean=%.1f",
            metrics.area_ha,
            metrics.elevation_stats["mean"],
            metrics.slope_stats["mean"],
        )

        # ── 11. Assemble response ─────────────────────────────────────────────
        processing_time_ms = round((time.perf_counter() - _t0) * 1000, 1)
        _log.info(
            "Pipeline complete: %.0f ms, warnings=%s",
            processing_time_ms,
            _warnings or "none",
        )
        return AnalysisResult(
            candidate_locations=candidates,
            selected_location=selected,
            catchment=CatchmentResult(
                area_ha=metrics.area_ha,
                polygon_geojson=mapping(polygon),
                elevation_stats=metrics.elevation_stats,
                slope_stats=metrics.slope_stats,
            ),
            metadata=AnalysisMetadata(
                dem_rows=raw_dem.rows,
                dem_cols=raw_dem.cols,
                dem_cell_size_m=raw_dem.cell_size,
                crs_used=raw_dem.crs,
                contour_count=len(contours),
                processing_time_ms=processing_time_ms,
            ),
            water_exclusion=WaterExclusionMetadata(
                source=water_result.source,
                excluded_feature_count=water_result.feature_count,
                attribution=water_result.attribution,
            ),
            land_exclusion=LandExclusionMetadata(
                source=land_result.source,
                excluded_feature_count=land_result.feature_count,
                builtup_cells_masked=int(land_result.mask.sum()),
                attribution=land_result.attribution,
            ),
            rainfall=rainfall_stats,
            runoff=runoff_estimate,
            pond_design=pond_design,
            warnings=_warnings,
        )


# Module-level singleton — import this in routes.py
analysis_service = AnalysisService()


def _find_nearest_candidate(
    candidates: list,
    lat: float,
    lon: float,
) -> object:
    """
    Snap a user-specified map click to the nearest auto-detected candidate.

    Uses simple Euclidean distance in lat/lon space — acceptable here because
    the DEM footprint is small (< 10 km) and the CRS distortion is negligible
    at Indian latitudes compared to the diameter of typical candidate clusters.

    Args:
        candidates: Ranked list of CandidatePoint objects from find_candidates().
        lat:        User-clicked latitude in WGS84 decimal degrees.
        lon:        User-clicked longitude in WGS84 decimal degrees.

    Returns:
        The candidate whose (lat, lon) is closest to the clicked point.
    """
    import math

    return min(candidates, key=lambda c: math.hypot(c.lat - lat, c.lon - lon))
