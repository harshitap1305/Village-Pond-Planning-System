"""
Tests for Module 5 — DEM Construction via Interpolation.
"""

from pathlib import Path

import numpy as np
import pytest

from src.dem.builder import build_dem, validate_dem
from src.geometry.pointcloud import build_point_cloud
from src.schemas.dem import DEM
from src.schemas.geometry import PointCloud
from src.schemas.terrain import ContourLine
from src.terrain.kml_source import KMLTerrainSource

FIXTURES = Path("tests/fixtures")


def make_toy_pc(scale: float = 1000.0) -> PointCloud:
    return PointCloud(
        x=[scale + 0, scale + 50, scale + 100, scale + 0, scale + 50, scale + 100],
        y=[scale + 0, scale + 0, scale + 0, scale + 100, scale + 100, scale + 100],
        z=[280.0, 280.5, 281.0, 280.0, 280.5, 281.0],
        crs="EPSG:32644",
    )


class TestDEMSchema:
    def test_valid_dem_created(self):
        arr = np.zeros((10, 10), dtype=np.float32)
        dem = DEM(
            array=arr, origin_x=0.0, origin_y=100.0, cell_size=2.0, crs="EPSG:32644"
        )
        assert dem.shape == (10, 10)

    def test_rejects_1d_array(self):
        with pytest.raises(ValueError, match="2D"):
            DEM(
                array=np.zeros(10),
                origin_x=0.0,
                origin_y=100.0,
                cell_size=2.0,
                crs="EPSG:32644",
            )

    def test_rejects_non_numpy_array(self):
        with pytest.raises(ValueError, match="ndarray"):
            DEM(
                array=[[1, 2], [3, 4]],
                origin_x=0.0,
                origin_y=100.0,
                cell_size=2.0,
                crs="EPSG:32644",
            )

    def test_rejects_non_positive_cell_size(self):
        arr = np.zeros((5, 5), dtype=np.float32)
        with pytest.raises(ValueError, match="positive"):
            DEM(
                array=arr,
                origin_x=0.0,
                origin_y=100.0,
                cell_size=-1.0,
                crs="EPSG:32644",
            )

    def test_rows_cols_properties(self):
        arr = np.zeros((12, 8), dtype=np.float32)
        dem = DEM(
            array=arr, origin_x=0.0, origin_y=100.0, cell_size=2.0, crs="EPSG:32644"
        )
        assert dem.rows == 12
        assert dem.cols == 8

    def test_default_nodata_is_minus_9999(self):
        arr = np.zeros((5, 5), dtype=np.float32)
        dem = DEM(
            array=arr, origin_x=0.0, origin_y=100.0, cell_size=2.0, crs="EPSG:32644"
        )
        assert dem.nodata == -9999.0


class TestBuildDEM:
    def test_returns_dem_object(self):
        pc = make_toy_pc()
        dem = build_dem(pc, cell_size=10.0)
        assert isinstance(dem, DEM)

    def test_dem_array_is_numpy_float32(self):
        pc = make_toy_pc()
        dem = build_dem(pc, cell_size=10.0)
        assert isinstance(dem.array, np.ndarray)
        assert dem.array.dtype == np.float32

    def test_no_nan_in_output(self):
        pc = make_toy_pc()
        dem = build_dem(pc, cell_size=10.0)
        assert not np.any(np.isnan(dem.array))

    def test_elevation_range_within_source(self):
        pc = make_toy_pc()
        dem = build_dem(pc, cell_size=10.0)
        assert np.nanmin(dem.array) >= 279.0
        assert np.nanmax(dem.array) <= 282.0

    def test_crs_propagated_from_pointcloud(self):
        pc = make_toy_pc()
        dem = build_dem(pc, cell_size=10.0)
        assert dem.crs == pc.crs

    def test_cell_size_stored_correctly(self):
        pc = make_toy_pc()
        dem = build_dem(pc, cell_size=5.0)
        assert dem.cell_size == 5.0

    def test_dem_shape_matches_bounding_box(self):
        pc = make_toy_pc(scale=500_000.0)
        dem = build_dem(pc, cell_size=10.0)
        assert dem.rows >= 10
        assert dem.cols >= 10

    def test_custom_cell_size_overrides_settings(self):
        pc = make_toy_pc()
        dem_coarse = build_dem(pc, cell_size=20.0)
        dem_fine = build_dem(pc, cell_size=5.0)
        assert dem_fine.rows > dem_coarse.rows
        assert dem_fine.cols > dem_coarse.cols

    def test_origin_x_is_near_min_x(self):
        pc = make_toy_pc(scale=500_000.0)
        dem = build_dem(pc, cell_size=10.0)
        assert dem.origin_x <= min(pc.x)

    def test_origin_y_is_near_max_y(self):
        pc = make_toy_pc(scale=500_000.0)
        dem = build_dem(pc, cell_size=10.0)
        assert dem.origin_y >= max(pc.y)


class TestValidateDEM:
    def _make_contours(self, elevs: list[float]) -> list[ContourLine]:
        return [
            ContourLine(elevation=e, points=[(81.286, 21.263), (81.287, 21.264)])
            for e in elevs
        ]

    def test_valid_dem_passes(self):
        arr = np.full((5, 5), 280.0, dtype=np.float32)
        dem = DEM(
            array=arr, origin_x=0.0, origin_y=100.0, cell_size=2.0, crs="EPSG:32644"
        )
        validate_dem(dem, self._make_contours([278.0, 280.0, 282.0]))

    def test_dem_below_source_range_fails(self):
        arr = np.full((5, 5), 260.0, dtype=np.float32)
        dem = DEM(
            array=arr, origin_x=0.0, origin_y=100.0, cell_size=2.0, crs="EPSG:32644"
        )
        with pytest.raises(ValueError, match="below source minimum"):
            validate_dem(dem, self._make_contours([278.0, 280.0, 282.0]))

    def test_dem_above_source_range_fails(self):
        arr = np.full((5, 5), 310.0, dtype=np.float32)
        dem = DEM(
            array=arr, origin_x=0.0, origin_y=100.0, cell_size=2.0, crs="EPSG:32644"
        )
        with pytest.raises(ValueError, match="exceeds source maximum"):
            validate_dem(dem, self._make_contours([278.0, 280.0, 282.0]))

    def test_tolerance_allows_edge_extrapolation(self):
        arr = np.full((5, 5), 282.5, dtype=np.float32)
        dem = DEM(
            array=arr, origin_x=0.0, origin_y=100.0, cell_size=2.0, crs="EPSG:32644"
        )
        validate_dem(dem, self._make_contours([278.0, 280.0, 282.0]))


class TestRealFixture:
    @pytest.fixture(scope="class")
    def real_dem(self):
        path = FIXTURES / "contours_1m.kml"
        if not path.exists():
            pytest.skip("contours_1m.kml not present")
        contours = KMLTerrainSource.from_file(path).extract_contours()
        pc = build_point_cloud(contours)
        return build_dem(pc, cell_size=2.0), contours

    def test_dem_shape_is_reasonable(self, real_dem):
        dem, _ = real_dem
        assert dem.rows > 100
        assert dem.cols > 100

    def test_no_nan_in_real_dem(self, real_dem):
        dem, _ = real_dem
        assert not np.any(np.isnan(dem.array))

    def test_elevation_range_matches_contours(self, real_dem):
        dem, contours = real_dem
        validate_dem(dem, contours)

    def test_crs_is_32644(self, real_dem):
        dem, _ = real_dem
        assert dem.crs == "EPSG:32644"

    def test_cell_size_stored_correctly(self, real_dem):
        dem, _ = real_dem
        assert dem.cell_size == 2.0
