from pathlib import Path

import pytest
from shapely.geometry import shape

from src.api.analysis_service import analysis_service

FIXTURE = Path("tests/fixtures/contours_1m.kml")


@pytest.fixture(scope="module")
def pipeline_result():
    """Run the full pipeline once per module — expensive (~60s)."""
    return analysis_service.run(FIXTURE.read_bytes(), "contours_1m.kml")


@pytest.mark.integration
class TestFullPipeline:
    def test_result_has_candidates(self, pipeline_result):
        assert len(pipeline_result.candidate_locations) > 0

    def test_selected_location_is_best_candidate(self, pipeline_result):
        assert (
            pipeline_result.selected_location == pipeline_result.candidate_locations[0]
        )

    def test_catchment_area_positive(self, pipeline_result):
        assert pipeline_result.catchment.area_ha > 0

    def test_elevation_stats_within_contour_range(self, pipeline_result):
        # Min elevation in catchment must be >= min contour elevation (with small tolerance)
        assert (
            pipeline_result.catchment.elevation_stats["min"] >= 260.0
        )  # contours start at 267m (tolerance)
        assert (
            pipeline_result.catchment.elevation_stats["max"] <= 310.0
        )  # contours end at 298m (tolerance)

    def test_catchment_polygon_is_valid_geojson(self, pipeline_result):
        polygon = shape(pipeline_result.catchment.polygon_geojson)
        assert polygon.is_valid

    def test_catchment_polygon_is_in_india(self, pipeline_result):
        polygon = shape(pipeline_result.catchment.polygon_geojson)
        lon, lat = polygon.centroid.x, polygon.centroid.y
        # Rough bounding box for Chhattisgarh
        assert 80.0 < lon < 84.0
        assert 17.0 < lat < 24.0

    def test_metadata_is_populated(self, pipeline_result):
        m = pipeline_result.metadata
        assert m.dem_rows > 0
        assert m.dem_cols > 0
        assert m.dem_cell_size_m > 0
        assert m.crs_used.startswith("EPSG:")
        assert m.contour_count > 0

    def test_idempotency(self):
        kml = FIXTURE.read_bytes()
        r1 = analysis_service.run(kml, "contours_1m.kml")
        r2 = analysis_service.run(kml, "contours_1m.kml")
        assert r1.candidate_locations == r2.candidate_locations
        assert r1.catchment.area_ha == r2.catchment.area_ha
        assert r1.catchment.polygon_geojson == r2.catchment.polygon_geojson
