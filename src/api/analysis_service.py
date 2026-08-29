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
  5. Build DEM (Module 5)
  6. Fill sinks + compute slope (Module 6)
  7. Compute flow direction (Module 7)
  8. Compute flow accumulation (Module 8)
  9. Find pond candidates (Module 9)
  10. Back-project selected candidate to (row, col)
  11. Delineate catchment mask via BFS (Module 10)
  12. Convert mask to WGS84 polygon (Module 10)
  13. Compute catchment metrics (Module 11)
  14. Assemble and return AnalysisResult
"""

import logging

from pyproj import Transformer
from shapely.geometry import mapping

from src.catchment.candidates import find_candidates
from src.catchment.metrics import assert_area_consistency, compute_metrics
from src.catchment.polygonize import mask_to_polygon
from src.dem.builder import build_dem, validate_dem
from src.dem.conditioning import fill_sinks
from src.dem.slope import compute_slope_deg
from src.geometry.pointcloud import build_point_cloud
from src.hydrology.flow_accumulation import compute_flow_accumulation
from src.hydrology.flow_direction import compute_flow_direction
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

        # ── 5. Build DEM ──────────────────────────────────────────────────────
        dem = build_dem(pc, cell_size=cell_size)
        validate_dem(dem, contours)
        _log.info(
            "DEM: %dx%d, cell_size=%.1fm, CRS=%s",
            dem.rows,
            dem.cols,
            dem.cell_size,
            dem.crs,
        )

        # ── 6. Condition DEM + slope ──────────────────────────────────────────
        dem = fill_sinks(dem)
        slope = compute_slope_deg(dem)
        _log.info("DEM conditioned (sinks filled), slope computed")

        # ── 7–8. Flow routing ─────────────────────────────────────────────────
        flow_dir = compute_flow_direction(dem)
        flow_accum = compute_flow_accumulation(flow_dir, dem)
        _log.info("Flow direction and accumulation computed")

        # ── 9. Candidate identification ───────────────────────────────────────
        candidates = find_candidates(dem, flow_accum, slope)
        if not candidates:
            raise ValueError(
                "No suitable pond candidates found in the provided terrain. "
                "The terrain may be too steep or lack sufficient drainage area. "
                "Try adjusting max_candidate_slope_deg or accumulation_percentile_threshold."
            )
        selected = candidates[0]
        _log.info(
            "Found %d candidates; selected lat=%.6f lon=%.6f",
            len(candidates),
            selected.lat,
            selected.lon,
        )

        # ── 10. Back-project selected candidate lat/lon → (row, col) ─────────
        t = Transformer.from_crs("EPSG:4326", dem.crs, always_xy=True)
        x_utm, y_utm = t.transform(selected.lon, selected.lat)
        col = int((x_utm - dem.origin_x) / dem.cell_size)
        row = int((dem.origin_y - y_utm) / dem.cell_size)
        _log.info("Pour point (row=%d, col=%d)", row, col)

        # ── 11. Watershed delineation ─────────────────────────────────────────
        mask = delineate_catchment(flow_dir, pour_point_rc=(row, col))
        _log.info("Catchment mask: %d cells", int(mask.sum()))

        # ── 12. Polygonize catchment ──────────────────────────────────────────
        polygon = mask_to_polygon(mask, dem)
        _log.info(
            "Catchment polygon: %s, valid=%s", polygon.geom_type, polygon.is_valid
        )

        # ── 13. Compute metrics ───────────────────────────────────────────────
        metrics = compute_metrics(mask, dem, slope)
        assert_area_consistency(metrics, int(flow_accum[row, col]))
        _log.info(
            "Metrics: area_ha=%.4f, elev_mean=%.1f, slope_mean=%.1f",
            metrics.area_ha,
            metrics.elevation_stats["mean"],
            metrics.slope_stats["mean"],
        )

        # ── 14. Assemble response ─────────────────────────────────────────────
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
                dem_rows=dem.rows,
                dem_cols=dem.cols,
                dem_cell_size_m=dem.cell_size,
                crs_used=dem.crs,
                contour_count=len(contours),
            ),
        )


# Module-level singleton — import this in routes.py
analysis_service = AnalysisService()
