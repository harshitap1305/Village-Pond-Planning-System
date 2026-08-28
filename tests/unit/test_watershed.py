"""
Tests for Module 10 — Catchment Delineation (BFS Watershed).
"""

import numpy as np

from src.hydrology.flow_direction import compute_flow_direction
from src.hydrology.watershed import delineate_catchment
from tests.fixtures.toy_dem import TOY_DEM


class TestWatershed:
    def test_pour_point_is_in_mask(self):
        """The pour point itself is always True in the output mask."""
        fd = compute_flow_direction(TOY_DEM)
        mask = delineate_catchment(fd, pour_point_rc=(4, 4))
        assert mask[4, 4] is np.True_

    def test_watershed_cell_count(self):
        """
        BFS from (4,4) on TOY_DEM yields exactly 16 cells.
        Top row and left column drain out of bounds.
        """
        fd = compute_flow_direction(TOY_DEM)
        mask = delineate_catchment(fd, pour_point_rc=(4, 4))
        assert mask.sum() == 16

    def test_watershed_shape(self):
        """Output mask is same shape as input flow_dir."""
        fd = compute_flow_direction(TOY_DEM)
        mask = delineate_catchment(fd, pour_point_rc=(4, 4))
        assert mask.shape == fd.shape

    def test_watershed_excludes_off_boundary_cells(self):
        """Top row [0, :] and left col [:, 0] are all False."""
        fd = compute_flow_direction(TOY_DEM)
        mask = delineate_catchment(fd, pour_point_rc=(4, 4))

        assert not np.any(mask[0, :])
        assert not np.any(mask[:, 0])

    def test_single_cell_pour_point(self):
        """A pour point at a ridge cell with no upstream drainage returns a 1-cell mask."""
        fd = compute_flow_direction(TOY_DEM)
        # (0, 0) is the highest point (ridge) and flows down, nothing flows into it.
        mask = delineate_catchment(fd, pour_point_rc=(0, 0))
        assert mask.sum() == 1
        assert mask[0, 0] is np.True_
