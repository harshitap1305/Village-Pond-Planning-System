"""
AnalysisService — orchestrates the full contour-to-catchment pipeline.

This class is the single entry point for the POST /analyzeContour endpoint.
It wires together all modules (2–11) in the correct order. Every step is a
pure function unit-tested independently; this module is pure composition.

Pipeline order:
  1. Validate file (Module 3)
  2. Parse KML/KMZ → ContourLines (Module 2)
  3. Validate contours (Module 3)
  4. Build PointCloud (Module 4)
  5. Build raw DEM (Module 5)
  6. Fill sinks → filled_dem + slope (Module 6)
  7. Find pond candidates — returns conditioned routing outputs (Module 9)
  8. Delineate catchment mask via multi-seed BFS (Module 10)
  9. Convert mask to WGS84 polygon (Module 10)
  10. Compute catchment metrics + consistency check (Module 11)
  11. Assemble and return AnalysisResult

Note on flow routing:
  Steps 7+ use `conditioned_dem`/`flow_dir_cond`/`flow_accum_cond` returned
  by find_candidates as the single source of truth. There is no separate
  filled-DEM routing pass — that was removed in Module 9 v3 to ensure
  consistent catchment areas at every stage.
"""

import logging

from shapely.geometry import mapping

from src.catchment.candidates import find_candidates
from src.catchment.metrics import assert_area_consistency, compute_metrics
from src.catchment.polygonize import mask_to_polygon
from src.dem.builder import build_dem, validate_dem
from src.dem.conditioning import fill_sinks
from src.dem.slope import compute_slope_deg
from src.geometry.pointcloud import build_point_cloud
from src.hydrology.watershed import delineate_catchment
from src.schemas.response import AnalysisMetadata, AnalysisResult, CatchmentResult
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
    ) -> AnalysisResult:
        """
        Run the full analysis pipeline on a KML/KMZ upload.

        Args:
            file_bytes: Raw bytes of the uploaded file.
            filename:   Original filename (used for format detection).
            cell_size:  Optional DEM cell size override in metres. Defaults to
                        settings.cell_size_m if None.

        Returns:
            AnalysisResult containing candidates, polygon, and metrics.

        Raises:
            TerrainParseError:    If the file cannot be parsed as KML/KMZ.
            InvalidGeometryError: If parsed contours fail geometry validation.
            FileTooLargeError:    If the file exceeds settings.max_upload_mb.
            ValueError:           If no pond candidates are found in the terrain.
        """
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

        # ── 7. Candidate identification + conditioned routing ─────────────────
        # find_candidates returns (candidates, conditioned_dem, flow_dir_cond,
        # flow_accum_cond). The conditioned routing outputs are the single source
        # of truth for ALL downstream steps — no separate routing pass needed.
        candidates, _cond_dem, flow_dir_cond, flow_accum_cond = find_candidates(
            raw_dem, filled_dem
        )
        if not candidates:
            raise ValueError(
                "No suitable pond candidates found in the provided terrain. "
                "The terrain may have no closed depressions larger than "
                "min_depression_area_sqm with catchment >= min_catchment_area_ha."
            )
        selected = candidates[0]
        _log.info(
            "Found %d candidates; selected lat=%.6f lon=%.6f score=%.4f",
            len(candidates),
            selected.lat,
            selected.lon,
            selected.score,
        )

        # ── 8 & 9. Watershed delineation & Polygonization for all candidates ──
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
            ),
        )


# Module-level singleton — import this in routes.py
analysis_service = AnalysisService()
