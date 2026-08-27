"""
Tests for DEM sink filling.
"""

import numpy as np

from src.dem.conditioning import fill_sinks
from src.schemas.dem import DEM


class TestConditioning:
    def test_fills_artificial_pit(self):
        # Create a 5x5 flat DEM at 280m
        arr = np.full((5, 5), 280.0, dtype=np.float32)
        # Put a pit in the middle at 275m
        arr[2, 2] = 275.0

        dem = DEM(
            array=arr,
            origin_x=0.0,
            origin_y=100.0,
            cell_size=2.0,
            crs="EPSG:32644",
        )

        filled_dem = fill_sinks(dem)

        # The pit should be raised to 280m to match its lowest neighbor
        assert filled_dem.array[2, 2] == 280.0

        # The edges should remain unchanged
        assert filled_dem.array[0, 0] == 280.0
        assert filled_dem.array[4, 4] == 280.0

    def test_leaves_flat_dem_unchanged(self):
        arr = np.full((5, 5), 280.0, dtype=np.float32)
        dem = DEM(
            array=arr,
            origin_x=0.0,
            origin_y=100.0,
            cell_size=2.0,
            crs="EPSG:32644",
        )

        filled_dem = fill_sinks(dem)

        np.testing.assert_array_equal(dem.array, filled_dem.array)
