"""
Tests for Module 9 — Depression-Based Pond Candidate Location Identification.

All tests use deterministic fixtures — no KML parsing, no network calls.
"""

import numpy as np
import pytest

from src.catchment.candidates import find_candidates
from src.config import settings
from src.dem.conditioning import fill_sinks
from src.schemas.dem import DEM
from tests.fixtures.depression_dem import (
    BOWL_A_MIN_RC,
    BOWL_B_COL_RANGE,
    BOWL_B_ROW_RANGE,
    BOWL_C_COL_RANGE,
    BOWL_C_ROW_RANGE,
    BOWL_D_FLAT_RCS,
    DEPRESSION_DEM,
)
from tests.fixtures.valley_dem import VALLEY_DEM


@pytest.fixture(scope="module")
def depression_result():
    """Run find_candidates on DEPRESSION_DEM once for the whole module."""
    filled = fill_sinks(DEPRESSION_DEM)
    return find_candidates(DEPRESSION_DEM, filled)


@pytest.fixture(scope="module")
def depression_candidates(depression_result):
    return depression_result[0]


class TestDepressionMethod:
    """Core correctness of the depression-based identification."""

    def test_finds_two_candidates(self, depression_candidates):
        """Bowl A and Bowl D must both be found."""
        assert (
            len(depression_candidates) >= 2
        ), f"Expected >= 2 candidates (Bowl A + Bowl D), got {len(depression_candidates)}"

    def test_bowl_a_single_sink(self, depression_candidates):
        """Bowl A has a single minimum → exactly 1 sink cell, had_flat_bottom=False."""
        # The bowl_sink_rcs contains the interior sink(s).
        # Bowl A's single minimum is at BOWL_A_MIN_RC = (44, 9).
        bowl_a_cands = [
            c for c in depression_candidates if BOWL_A_MIN_RC in c.bowl_sink_rcs
        ]
        assert len(bowl_a_cands) >= 1, (
            f"No candidate with sink at BOWL_A_MIN_RC={BOWL_A_MIN_RC}. "
            f"Sinks found: {[c.bowl_sink_rcs for c in depression_candidates]}"
        )
        assert all(
            not c.had_flat_bottom for c in bowl_a_cands
        ), "Bowl A has a single minimum but had_flat_bottom=True."
        assert all(
            len(c.bowl_sink_rcs) == 1 for c in bowl_a_cands
        ), f"Bowl A should have 1 sink, got: {[c.bowl_sink_rcs for c in bowl_a_cands]}"

    def test_bowl_d_flat_bottom(self, depression_candidates):
        """Bowl D has a 2-cell flat bottom → 2 sinks, had_flat_bottom=True."""
        # Both BOWL_D_FLAT_RCS should be in the candidate's bowl_sink_rcs.
        bowl_d_cands = [
            c
            for c in depression_candidates
            if all(rc in c.bowl_sink_rcs for rc in BOWL_D_FLAT_RCS)
        ]
        assert len(bowl_d_cands) >= 1, (
            f"No candidate with sinks {BOWL_D_FLAT_RCS}. "
            f"All sinks: {[c.bowl_sink_rcs for c in depression_candidates]}"
        )
        assert all(
            c.had_flat_bottom for c in bowl_d_cands
        ), "Bowl D has a 2-cell flat bottom but had_flat_bottom=False."

    def test_bowl_b_filtered_by_min_area(self, depression_candidates):
        """Bowl B is only 4 cells (400m²) — must be filtered by min_depression_area_sqm."""
        # Bowl B sink should be in BOWL_B rows/cols range. No candidate's sink_rcs
        # should fall in that range.
        for c in depression_candidates:
            for rc in c.bowl_sink_rcs:
                in_b = (
                    BOWL_B_ROW_RANGE[0] <= rc[0] <= BOWL_B_ROW_RANGE[1]
                    and BOWL_B_COL_RANGE[0] <= rc[1] <= BOWL_B_COL_RANGE[1]
                )
                assert (
                    not in_b
                ), f"Bowl B sink at {rc} should be area-filtered but was returned."

    def test_bowl_c_edge_excluded(self, depression_candidates):
        """Bowl C is edge-touching — must be discarded."""
        for c in depression_candidates:
            for rc in c.bowl_sink_rcs:
                in_c = (
                    BOWL_C_ROW_RANGE[0] <= rc[0] <= BOWL_C_ROW_RANGE[1]
                    and BOWL_C_COL_RANGE[0] <= rc[1] <= BOWL_C_COL_RANGE[1]
                )
                assert (
                    not in_c
                ), f"Bowl C sink at {rc} is edge-touching but was returned."

    def test_score_range(self, depression_candidates):
        """All scores must be in [0.0, 1.0]."""
        for c in depression_candidates:
            assert 0.0 <= c.score <= 1.0, f"Score {c.score} out of [0,1]"

    def test_score_denominator_is_cell_count(self, depression_result):
        """Score = catchment_cells / total_DEM_cells.
        Verify: score * total_cells ≈ sum(flow_accum_cond at sink cells).
        """
        candidates, _cond_dem, _flow_dir_cond, flow_accum_cond = depression_result
        total_cells = DEPRESSION_DEM.array.size
        for c in candidates:
            implied_catchment = c.score * total_cells
            accum_at_sinks = sum(flow_accum_cond[rc] for rc in c.bowl_sink_rcs)
            assert abs(implied_catchment - accum_at_sinks) < 1.0, (
                f"score * total_cells ({implied_catchment:.1f}) != "
                f"flow_accum_cond at sinks ({accum_at_sinks})"
            )

    def test_sorted_descending(self, depression_candidates):
        """Scores must be non-increasing."""
        for i in range(len(depression_candidates) - 1):
            assert depression_candidates[i].score >= depression_candidates[i + 1].score

    def test_wgs84_range(self, depression_candidates):
        """lat ∈ [-90,90], lon ∈ [-180,180]."""
        for c in depression_candidates:
            assert -90.0 <= c.lat <= 90.0
            assert -180.0 <= c.lon <= 180.0

    def test_storage_volume_positive(self, depression_candidates):
        """estimated_storage_m3 must be > 0 for every candidate."""
        for c in depression_candidates:
            assert c.estimated_storage_m3 > 0.0

    def test_depression_area_positive(self, depression_candidates):
        """depression_area_ha must be > 0 for every candidate."""
        for c in depression_candidates:
            assert c.depression_area_ha > 0.0

    def test_depression_depth_positive(self, depression_candidates):
        """depression_depth_m must be > 0 for every candidate."""
        for c in depression_candidates:
            assert c.depression_depth_m > 0.0


class TestEdgeCases:
    def test_flat_dem_returns_empty(self):
        """A perfectly flat DEM has no depressions — must return empty list."""
        flat = DEM(
            array=np.full((10, 10), 5.0, dtype=np.float32),
            origin_x=0.0,
            origin_y=100.0,
            cell_size=10.0,
            crs="EPSG:32644",
        )
        filled = fill_sinks(flat)
        candidates, *_ = find_candidates(flat, filled)
        assert candidates == []

    def test_returns_4tuple(self, depression_result):
        """find_candidates must return a 4-tuple."""
        assert len(depression_result) == 4

    def test_conditioned_dem_shape(self, depression_result):
        """Conditioned DEM must have same shape as input."""
        _, cond_dem, flow_dir, flow_accum = depression_result
        assert cond_dem.array.shape == DEPRESSION_DEM.array.shape
        assert flow_dir.shape == DEPRESSION_DEM.array.shape
        assert flow_accum.shape == DEPRESSION_DEM.array.shape

    def test_bowl_sink_rcs_is_populated(self, depression_candidates):
        """Every candidate must have at least one bowl_sink_rc."""
        for c in depression_candidates:
            assert len(c.bowl_sink_rcs) >= 1


class TestAdjacentStreamPourPoint:
    """Verifies pour point detection uses min elevation, not max flow_accum."""

    def test_pour_point_elevation_is_rim_not_interior(self, depression_result):
        """
        Pour point elevation must be at the rim level (48m), not at the bowl
        interior minimum (38m). The saddle is always the lowest point on the
        boundary ring, which is the rim.
        """
        candidates, *_ = depression_result
        assert len(candidates) >= 1
        for c in candidates:
            # Bowl rim is at 48m. Interior is at 38–46m. Pour point must be ≥ 48m
            # (at the rim or in the feeder above the rim).
            assert c.elevation >= 48.0, (
                f"Pour point elevation {c.elevation}m is inside the bowl interior "
                "(< rim level 48m). Saddle detection is wrong."
            )


class TestValleyRegression:
    """Regression: VALLEY_DEM (closed bowl) must return >= 1 candidate.

    VALLEY_DEM is a 7×7 bowl at 2m cell_size (tiny). We temporarily drop
    thresholds to test the detection logic, not threshold calibration.
    """

    def test_valley_dem_returns_candidate(self):
        original_ha = settings.min_catchment_area_ha
        original_sqm = settings.min_depression_area_sqm
        settings.min_catchment_area_ha = 0.0
        settings.min_depression_area_sqm = 0.0
        try:
            filled = fill_sinks(VALLEY_DEM)
            candidates, *_ = find_candidates(VALLEY_DEM, filled)
            assert len(candidates) >= 1, "VALLEY_DEM returned no candidates"
        finally:
            settings.min_catchment_area_ha = original_ha
            settings.min_depression_area_sqm = original_sqm
