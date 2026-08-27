"""
Tests for slope calculation.
"""

import numpy as np

from src.dem.slope import compute_slope_deg
from src.schemas.dem import DEM


class TestSlope:
    def test_flat_plane_is_zero_slope(self):
        arr = np.full((5, 5), 280.0, dtype=np.float32)
        dem = DEM(
            array=arr,
            origin_x=0.0,
            origin_y=100.0,
            cell_size=2.0,
            crs="EPSG:32644",
        )
        slope = compute_slope_deg(dem)
        np.testing.assert_array_equal(slope, np.zeros((5, 5), dtype=np.float32))

    def test_45_degree_plane(self):
        # A plane dropping 2m (cell_size) every 2m in X direction -> 45 degrees
        # [284, 282, 280]
        # [284, 282, 280]
        # [284, 282, 280]
        arr = np.array(
            [
                [284.0, 282.0, 280.0],
                [284.0, 282.0, 280.0],
                [284.0, 282.0, 280.0],
            ],
            dtype=np.float32,
        )

        dem = DEM(
            array=arr,
            origin_x=0.0,
            origin_y=100.0,
            cell_size=2.0,
            crs="EPSG:32644",
        )

        slope = compute_slope_deg(dem)

        # Edges might be slightly different depending on how gradient handles boundaries (1st order diff)
        # But the middle cell should be exactly 45 degrees
        assert np.isclose(slope[1, 1], 45.0)

        # Actually, np.gradient calculates 2nd order accurate central differences in the interior
        # and 1st order accurate differences at the boundaries. For a perfect linear plane,
        # it should be 45.0 everywhere.
        assert np.allclose(slope, 45.0)
