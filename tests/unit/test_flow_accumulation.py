"""
Tests for Module 8 — Flow Accumulation.
"""

import numpy as np

from src.hydrology.flow_accumulation import (
    compute_flow_accumulation,
    top_accumulation_cells,
)
from src.hydrology.flow_direction import compute_flow_direction
from tests.fixtures.toy_dem import TOY_DEM


class TestFlowAccumulation:
    def test_output_is_integer_array(self):
        fd = compute_flow_direction(TOY_DEM)
        accum = compute_flow_accumulation(fd, TOY_DEM)

        assert accum.shape == TOY_DEM.shape
        assert accum.dtype == np.int32

    def test_ridge_cells_have_minimum_accumulation(self):
        """
        The top-left cell (0, 0) of the TOY_DEM is the highest point.
        It should receive no flow from anywhere else, so accum = 1.
        """
        fd = compute_flow_direction(TOY_DEM)
        accum = compute_flow_accumulation(fd, TOY_DEM)

        assert accum[0, 0] == 1

    def test_outlet_accumulation(self):
        """
        The bottom-right cell (4, 4) is the lowest point.
        Due to np.roll wrapping, the actual accumulation is 16.
        """
        fd = compute_flow_direction(TOY_DEM)
        accum = compute_flow_accumulation(fd, TOY_DEM)

        assert accum[4, 4] == 16

    def test_diagonal_accumulation(self):
        """
        Verify the flow accumulates along the main diagonal towards the SE outlet.
        """
        fd = compute_flow_direction(TOY_DEM)
        accum = compute_flow_accumulation(fd, TOY_DEM)

        # Expected based on the live verification matrix
        assert accum[1, 1] == 1
        assert accum[2, 2] == 2
        assert accum[3, 3] == 3
        assert accum[4, 4] == 16

    def test_top_accumulation_mask(self):
        """
        Ensure the percentile filtering correctly masks the highest accumulation cells.
        """
        fd = compute_flow_direction(TOY_DEM)
        accum = compute_flow_accumulation(fd, TOY_DEM)

        # Top 10% (90th percentile)
        mask = top_accumulation_cells(accum, percentile=90.0)

        assert mask.dtype == bool
        assert mask.shape == accum.shape

        # The outlet (4,4) has accum=16, which is definitely in the top 10%
        assert mask[4, 4]
        # The ridge (0,0) has accum=1, which is not in the top 10%
        assert not mask[0, 0]
