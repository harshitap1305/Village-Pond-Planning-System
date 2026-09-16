import json
from pathlib import Path
from unittest.mock import patch

import pytest
from shapely.geometry import shape

from src.api.analysis_service import analysis_service

FIXTURE = Path("tests/fixtures/contours_1m.kml")

# ---------------------------------------------------------------------------
# API mocks — integration tests must not hit live servers.
# ---------------------------------------------------------------------------
_EMPTY_OSM = '<?xml version="1.0" encoding="UTF-8"?><osm version="0.6"></osm>'
_MOCK_RAINFALL = json.dumps(
    {
        "daily": {
            # Jul: 800mm total → daily avg 25.8mm > Ia=20.76mm (CN=71) → produces runoff
            # Aug: 750mm total → daily avg 24.2mm > Ia → produces runoff
            # Nov: 10mm total  → daily avg 0.33mm < Ia → zero runoff
            # This gives annual_avg_mm=1560, wet_season=1550, dry_season=10
            "time": ["2023-07-15", "2023-08-15", "2023-11-15"],
            "precipitation_sum": [800.0, 750.0, 10.0],
        }
    }
)


@pytest.fixture(scope="module")
def pipeline_result():
    """Run the full pipeline once per module — expensive (~60s).
    External APIs are mocked so the test is self-contained and offline."""
    with (
        patch(
            "src.catchment.water_exclusion.OsmApiClient.query_water_features",
            return_value=_EMPTY_OSM,
        ),
        patch(
            "src.catchment.rainfall_service.OpenMeteoClient.get_daily_rainfall",
            return_value=_MOCK_RAINFALL,
        ),
    ):
        return analysis_service.run(FIXTURE.read_bytes(), "contours_1m.kml")


@pytest.mark.integration
class TestFullPipeline:
    def test_result_has_candidates(self, pipeline_result):
        assert len(pipeline_result.candidate_locations) > 0

    def test_selected_location_is_best_candidate(self, pipeline_result):
        # Compare public fields only (bowl_sink_rcs is an internal routing field excluded from eq)
        s = pipeline_result.selected_location
        b = pipeline_result.candidate_locations[0]
        assert s.lat == b.lat and s.lon == b.lon and s.score == b.score

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

    def test_candidate_new_fields_present(self, pipeline_result):
        """New depression-method fields must be populated on every candidate."""
        for c in pipeline_result.candidate_locations:
            assert c.estimated_storage_m3 > 0
            assert c.depression_area_ha > 0
            assert 0.0 <= c.score <= 1.0
            assert c.depression_depth_m > 0

    def test_water_exclusion_metadata_present(self, pipeline_result):
        """water_exclusion block must always be present in the response."""
        we = pipeline_result.water_exclusion
        assert we.source in {"osm", "flat_area_heuristic", "unavailable"}
        assert we.excluded_feature_count >= 0
        assert "OpenStreetMap" in we.attribution

    def test_water_exclusion_source_is_osm(self, pipeline_result):
        """The mock returns a successful (empty) Overpass response — source must be osm."""
        assert pipeline_result.water_exclusion.source == "osm"

    def test_land_exclusion_metadata_present(self, pipeline_result):
        """land_exclusion block must always be present in the response."""
        le = pipeline_result.land_exclusion
        assert le.source in {"osm", "unavailable"}
        assert le.excluded_feature_count >= 0
        assert le.builtup_cells_masked >= 0
        assert "OpenStreetMap" in le.attribution

    def test_land_exclusion_source_is_osm(self, pipeline_result):
        """The mock XML is cached by water_exclusion — land_exclusion must reuse it.
        Empty XML means feature_count=0 and builtup_cells_masked=0, source=osm."""
        assert pipeline_result.land_exclusion.source == "osm"
        assert pipeline_result.land_exclusion.excluded_feature_count == 0
        assert pipeline_result.land_exclusion.builtup_cells_masked == 0

    def test_rainfall_stats_present(self, pipeline_result):
        """rainfall block must be present and correctly populated by the mock."""
        rf = pipeline_result.rainfall
        assert rf is not None
        assert rf.source == "open_meteo_era5_land"
        # Mock: Jul=800mm, Aug=750mm, Nov=10mm → annual=1560, wet=1550, dry=10
        assert rf.annual_avg_mm == 1560.0
        assert rf.wet_season_avg_mm == 1550.0
        assert rf.dry_season_avg_mm == 10.0

    def test_runoff_estimate_present(self, pipeline_result):
        """runoff block must be present when rainfall data is available."""
        ru = pipeline_result.runoff
        assert ru is not None

    def test_runoff_annual_volume_positive(self, pipeline_result):
        """Annual runoff volume must be > 0 when rainfall is non-zero."""
        assert pipeline_result.runoff.annual_avg_m3 > 0.0

    def test_runoff_method_and_cn_populated(self, pipeline_result):
        """method and curve_number must be set to valid values."""
        ru = pipeline_result.runoff
        assert ru.method in {"scs_cn_monthly_distributed", "rational_annual_fallback"}
        assert 0 < ru.curve_number <= 100

    def test_pond_design_present(self, pipeline_result):
        """pond_design block must be present when runoff data is available."""
        assert pipeline_result.pond_design is not None

    def test_pond_design_depth_in_valid_range(self, pipeline_result):
        """Recommended water depth must be within the [1.5m, 4.0m] engineering range."""
        pd = pipeline_result.pond_design
        assert 1.5 <= pd.water_depth_m <= 4.0

    def test_pond_design_constrained_by_populated(self, pipeline_result):
        """constrained_by must be one of the four known values."""
        pd = pipeline_result.pond_design
        assert pd.constrained_by in {
            "hydrology",
            "topography",
            "depth_min",
            "depth_max",
        }

    def test_idempotency(self):
        kml = FIXTURE.read_bytes()
        with (
            patch(
                "src.catchment.water_exclusion.OsmApiClient.query_water_features",
                return_value=_EMPTY_OSM,
            ),
            patch(
                "src.catchment.rainfall_service.OpenMeteoClient.get_daily_rainfall",
                return_value=_MOCK_RAINFALL,
            ),
        ):
            r1 = analysis_service.run(kml, "contours_1m.kml")
            r2 = analysis_service.run(kml, "contours_1m.kml")
        assert r1.candidate_locations == r2.candidate_locations
        assert r1.catchment.area_ha == r2.catchment.area_ha
        assert r1.catchment.polygon_geojson == r2.catchment.polygon_geojson
        assert r1.rainfall.annual_avg_mm == r2.rainfall.annual_avg_mm
        assert r1.runoff.annual_avg_m3 == r2.runoff.annual_avg_m3
        assert r1.pond_design.water_depth_m == r2.pond_design.water_depth_m
