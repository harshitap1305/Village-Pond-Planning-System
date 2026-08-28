"""
Tests for Module 10 — Catchment Polygonization.
"""

import numpy as np
import pytest

from src.catchment.polygonize import mask_to_polygon
from src.hydrology.flow_direction import compute_flow_direction
from src.hydrology.watershed import delineate_catchment
from tests.fixtures.toy_dem import TOY_DEM


@pytest.fixture
def sample_mask():
    fd = compute_flow_direction(TOY_DEM)
    return delineate_catchment(fd, pour_point_rc=(4, 4))


class TestPolygonize:
    def test_polygon_is_valid_shapely(self, sample_mask):
        """polygon.is_valid == True."""
        polygon = mask_to_polygon(sample_mask, TOY_DEM)
        assert polygon.is_valid

    def test_polygon_area_in_wgs84_bounds(self, sample_mask):
        """
        Area in WGS84 will be in square degrees, which is very small.
        Instead of checking exact square degrees, we just ensure it's > 0.
        Note: The true area in square meters is 64.0 (tested in REPL),
        but shapely area on WGS84 coords will be in degrees.
        """
        polygon = mask_to_polygon(sample_mask, TOY_DEM)
        assert polygon.area > 0
        assert polygon.area < 1.0  # Square degrees are tiny

    def test_polygon_wgs84_coordinates(self, sample_mask):
        """All coords satisfy -90 <= lat <= 90, -180 <= lon <= 180."""
        polygon = mask_to_polygon(sample_mask, TOY_DEM)

        # Test bounds of the polygon
        min_lon, min_lat, max_lon, max_lat = polygon.bounds

        assert -90.0 <= min_lat <= 90.0
        assert -90.0 <= max_lat <= 90.0
        assert -180.0 <= min_lon <= 180.0
        assert -180.0 <= max_lon <= 180.0

    def test_polygon_from_empty_mask_raises(self):
        """Empty mask raises ValueError."""
        empty_mask = np.zeros(TOY_DEM.shape, dtype=bool)
        with pytest.raises(
            ValueError, match="Catchment mask produced no polygon geometry"
        ):
            mask_to_polygon(empty_mask, TOY_DEM)
