"""
Tests for Module 7 — D8 Flow Direction.
"""

import numpy as np

from src.hydrology.flow_direction import compute_flow_direction
from src.schemas.dem import DEM
from tests.fixtures.toy_dem import CELL_SIZE, EXPECTED_INTERIOR_CODE, TOY_DEM

VALID_D8_CODES = {0, 1, 2, 4, 8, 16, 32, 64, 128}


class TestD8OutputShape:
    def test_output_shape_matches_dem(self):
        fd = compute_flow_direction(TOY_DEM)
        assert fd.shape == TOY_DEM.shape

    def test_output_dtype_is_int16(self):
        fd = compute_flow_direction(TOY_DEM)
        assert fd.dtype == np.int16

    def test_all_codes_are_valid_d8_values(self):
        fd = compute_flow_direction(TOY_DEM)
        unique_codes = set(np.unique(fd).tolist())
        assert unique_codes.issubset(VALID_D8_CODES)


class TestD8Correctness:
    def test_interior_cells_drain_southeast(self):
        """All interior cells of the SE-tilted toy DEM must have code 2 (SE)."""
        fd = compute_flow_direction(TOY_DEM)
        interior = fd[1:4, 1:4]
        assert np.all(interior == EXPECTED_INTERIOR_CODE), (
            f"Expected all interior cells = {EXPECTED_INTERIOR_CODE}, "
            f"got:\n{interior}"
        )

    def test_flat_dem_produces_all_zeros(self):
        """A perfectly flat DEM has no downhill neighbor anywhere."""
        arr = np.full((5, 5), 280.0, dtype=np.float32)
        dem = DEM(
            array=arr,
            origin_x=0.0,
            origin_y=10.0,
            cell_size=CELL_SIZE,
            crs="EPSG:32644",
        )
        fd = compute_flow_direction(dem)
        assert np.all(fd == 0)

    def test_north_slope_drains_north(self):
        """A DEM that drops uniformly northward should produce code 64 (N)."""
        # North = row index decreasing. So row 0 must be lowest, row 4 highest.
        rows = np.tile(np.arange(1, 6), (5, 1)).T.astype(np.float32)
        dem = DEM(
            array=rows,
            origin_x=0.0,
            origin_y=10.0,
            cell_size=CELL_SIZE,
            crs="EPSG:32644",
        )
        fd = compute_flow_direction(dem)
        # Interior cells [1:4, 1:4] should all drain North (code 64)
        assert np.all(fd[1:4, 1:4] == 64)

    def test_east_slope_drains_east(self):
        """A DEM that drops uniformly eastward should produce code 1 (E)."""
        cols = np.tile(np.arange(5, 0, -1), (5, 1)).astype(np.float32)
        dem = DEM(
            array=cols,
            origin_x=0.0,
            origin_y=10.0,
            cell_size=CELL_SIZE,
            crs="EPSG:32644",
        )
        fd = compute_flow_direction(dem)
        # Interior cells [1:4, 1:4] should all drain East (code 1)
        assert np.all(fd[1:4, 1:4] == 1)

    def test_south_slope_drains_south(self):
        """A DEM that drops uniformly southward should produce code 4 (S)."""
        # South = row index increasing. So row 0 must be highest, row 4 lowest.
        rows = np.tile(np.arange(5, 0, -1), (5, 1)).T.astype(np.float32)
        dem = DEM(
            array=rows,
            origin_x=0.0,
            origin_y=10.0,
            cell_size=CELL_SIZE,
            crs="EPSG:32644",
        )
        fd = compute_flow_direction(dem)
        assert np.all(fd[1:4, 1:4] == 4)


class TestD8DiagonalDistance:
    def test_steep_diagonal_beats_shallow_orthogonal(self):
        """
        When a diagonal drop is much steeper than an orthogonal one,
        the diagonal direction wins, correctly accounting for sqrt(2) distance.

        DEM layout (3x3):
            10   5   0
            10  10  10
            10  10  10
        Center cell (row=1, col=1) = 10.
        East neighbor (row=1, col=2) = 10  -> orthogonal drop = 0 (flat)
        NE neighbor  (row=0, col=2) = 0   -> diagonal drop = (10-0)/(sqrt(2)*cs) > 0
        Expected direction: NE (code 128).
        """
        arr = np.array(
            [
                [10.0, 5.0, 0.0],
                [10.0, 10.0, 10.0],
                [10.0, 10.0, 10.0],
            ],
            dtype=np.float32,
        )
        dem = DEM(
            array=arr,
            origin_x=0.0,
            origin_y=6.0,
            cell_size=2.0,
            crs="EPSG:32644",
        )
        fd = compute_flow_direction(dem)
        # Center cell should drain NE (code 128)
        assert fd[1, 1] == 128
