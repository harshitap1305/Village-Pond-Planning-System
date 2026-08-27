"""
Tests for Module 4 — Point Cloud Extraction & Coordinate Normalization.

Test structure:
  TestPointCloudSchema      — Pydantic model validators
  TestDetectUTMEpsg         — CRS auto-detection
  TestBuildPointCloud       — reprojection + deduplication
  TestRealFixture           — integration against contours_1m.kml
"""

import math
from pathlib import Path

import pytest

from src.geometry.crs_utils import detect_utm_epsg
from src.geometry.pointcloud import build_point_cloud
from src.schemas.geometry import PointCloud
from src.schemas.terrain import ContourLine
from src.terrain.kml_source import KMLTerrainSource

FIXTURES = Path("tests/fixtures")


def make_contour(elevation: float, points: list) -> ContourLine:
    return ContourLine(elevation=elevation, points=points)


class TestPointCloudSchema:
    def test_valid_point_cloud_created(self):
        pc = PointCloud(x=[1.0, 2.0], y=[3.0, 4.0], z=[280.0, 281.0], crs="EPSG:32644")
        assert len(pc.x) == 2

    def test_rejects_mismatched_lengths(self):
        with pytest.raises(ValueError, match="equal length"):
            PointCloud(x=[1.0], y=[1.0, 2.0], z=[280.0], crs="EPSG:32644")

    def test_rejects_empty_lists(self):
        with pytest.raises(ValueError, match="at least one point"):
            PointCloud(x=[], y=[], z=[], crs="EPSG:32644")

    def test_crs_stored_as_string(self):
        pc = PointCloud(x=[1.0], y=[1.0], z=[1.0], crs="EPSG:32644")
        assert pc.crs == "EPSG:32644"


class TestDetectUTMEpsg:
    def test_chhattisgarh_india_is_32644(self):
        assert detect_utm_epsg(81.28, 21.26) == 32644

    def test_new_york_is_32618(self):
        assert detect_utm_epsg(-74.0, 40.7) == 32618

    def test_sydney_southern_hemisphere(self):
        assert detect_utm_epsg(151.2, -33.9) == 32756

    def test_prime_meridian_northern(self):
        assert detect_utm_epsg(0.0, 51.5) == 32631

    def test_northern_hemisphere_code_series(self):
        epsg = detect_utm_epsg(81.28, 21.26)
        assert 32601 <= epsg <= 32660

    def test_southern_hemisphere_code_series(self):
        epsg = detect_utm_epsg(81.28, -21.26)
        assert 32701 <= epsg <= 32760

    def test_north_vs_south_same_longitude(self):
        north = detect_utm_epsg(81.28, 10.0)
        south = detect_utm_epsg(81.28, -10.0)
        assert north - south == 32644 - 32744


class TestBuildPointCloud:
    def test_basic_reprojection_returns_point_cloud(self):
        contours = [
            make_contour(280.0, [(81.286, 21.263), (81.287, 21.264)]),
            make_contour(281.0, [(81.290, 21.270), (81.291, 21.271)]),
        ]
        pc = build_point_cloud(contours)
        assert isinstance(pc, PointCloud)

    def test_crs_is_epsg_32644_for_sample_region(self):
        contours = [make_contour(280.0, [(81.286, 21.263), (81.287, 21.264)])]
        pc = build_point_cloud(contours)
        assert pc.crs == "EPSG:32644"

    def test_coordinates_are_in_metric_range(self):
        contours = [
            make_contour(280.0, [(81.286, 21.263), (81.287, 21.264)]),
            make_contour(281.0, [(81.290, 21.270), (81.291, 21.271)]),
        ]
        pc = build_point_cloud(contours)
        assert all(100_000 < x < 1_000_000 for x in pc.x)
        assert all(100_000 < y < 10_000_000 for y in pc.y)

    def test_coordinates_are_not_in_degree_range(self):
        contours = [make_contour(280.0, [(81.286, 21.263), (81.287, 21.264)])]
        pc = build_point_cloud(contours)
        assert not any(-180 <= x <= 180 for x in pc.x)

    def test_elevation_values_preserved(self):
        contours = [
            make_contour(280.0, [(81.286, 21.263), (81.287, 21.264)]),
            make_contour(285.0, [(81.290, 21.270), (81.291, 21.271)]),
        ]
        pc = build_point_cloud(contours)
        assert set(pc.z) == {280.0, 285.0}

    def test_point_count_equals_total_vertices(self):
        contours = [
            make_contour(280.0, [(81.286, 21.263), (81.287, 21.264), (81.288, 21.265)]),
            make_contour(281.0, [(81.290, 21.270), (81.291, 21.271)]),
        ]
        pc = build_point_cloud(contours)
        assert len(pc.x) == 5

    def test_deduplication_removes_repeated_vertices(self):
        shared_point = (81.286, 21.263)
        contours = [
            make_contour(280.0, [shared_point, (81.287, 21.264)]),
            make_contour(281.0, [shared_point, (81.291, 21.271)]),
        ]
        pc = build_point_cloud(contours)
        assert len(pc.x) == 3

    def test_xyz_lists_have_equal_length(self):
        contours = [make_contour(280.0, [(81.286, 21.263), (81.287, 21.264)])]
        pc = build_point_cloud(contours)
        assert len(pc.x) == len(pc.y) == len(pc.z)

    def test_empty_contours_raises_value_error(self):
        with pytest.raises(ValueError, match="no coordinate points"):
            build_point_cloud([])

    def test_single_contour_works(self):
        contours = [make_contour(280.0, [(81.286, 21.263), (81.287, 21.264)])]
        pc = build_point_cloud(contours)
        assert len(pc.x) == 2


class TestRealFixture:
    @pytest.fixture
    def real_contours(self):
        path = FIXTURES / "contours_1m.kml"
        if not path.exists():
            pytest.skip("contours_1m.kml not present")
        return KMLTerrainSource.from_file(path).extract_contours()

    def test_point_count_is_large(self, real_contours):
        pc = build_point_cloud(real_contours)
        assert len(pc.x) > 100_000

    def test_crs_is_32644(self, real_contours):
        pc = build_point_cloud(real_contours)
        assert pc.crs == "EPSG:32644"

    def test_elevation_range_preserved(self, real_contours):
        pc = build_point_cloud(real_contours)
        assert min(pc.z) >= 267.0
        assert max(pc.z) <= 298.0

    def test_all_coordinates_metric(self, real_contours):
        pc = build_point_cloud(real_contours)
        assert min(pc.x) > 100_000
        assert min(pc.y) > 100_000

    def test_no_nan_in_output(self, real_contours):
        pc = build_point_cloud(real_contours)
        assert all(math.isfinite(v) for v in pc.x)
        assert all(math.isfinite(v) for v in pc.y)
        assert all(math.isfinite(v) for v in pc.z)
