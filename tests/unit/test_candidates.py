"""
Tests for Module 9 — Pond Candidate Location Identification.
"""

from src.catchment.candidates import find_candidates
from src.config import settings
from src.dem.slope import compute_slope_deg
from src.hydrology.flow_accumulation import compute_flow_accumulation
from src.hydrology.flow_direction import compute_flow_direction
from tests.fixtures.valley_dem import VALLEY_DEM


class TestFindCandidates:
    def test_returns_candidate_list(self):
        """
        Uses VALLEY_DEM — at least 1 candidate should emerge.
        """
        slope = compute_slope_deg(VALLEY_DEM)
        fd = compute_flow_direction(VALLEY_DEM)
        accum = compute_flow_accumulation(fd, VALLEY_DEM)

        candidates = find_candidates(VALLEY_DEM, accum, slope)

        assert len(candidates) >= 1
        assert isinstance(candidates, list)

    def test_candidate_score_is_between_0_and_1(self):
        """
        Ensures score is properly normalized.
        """
        slope = compute_slope_deg(VALLEY_DEM)
        fd = compute_flow_direction(VALLEY_DEM)
        accum = compute_flow_accumulation(fd, VALLEY_DEM)

        candidates = find_candidates(VALLEY_DEM, accum, slope)

        for c in candidates:
            assert 0.0 <= c.score <= 1.0

    def test_best_candidate_is_valley_floor(self):
        """
        The highest-scoring candidate should have elevation=1m (the bowl center).
        """
        slope = compute_slope_deg(VALLEY_DEM)
        fd = compute_flow_direction(VALLEY_DEM)
        accum = compute_flow_accumulation(fd, VALLEY_DEM)

        candidates = find_candidates(VALLEY_DEM, accum, slope)

        # Center pixel (row 3, col 3) is elevation 1.0
        assert candidates[0].elevation == 1.0
        assert candidates[0].score == 1.0  # It's the global max accumulation

    def test_candidates_sorted_descending_by_score(self):
        """
        If multiple candidates exist, scores must be non-increasing.
        """
        slope = compute_slope_deg(VALLEY_DEM)
        fd = compute_flow_direction(VALLEY_DEM)
        accum = compute_flow_accumulation(fd, VALLEY_DEM)

        candidates = find_candidates(VALLEY_DEM, accum, slope)

        for i in range(len(candidates) - 1):
            assert candidates[i].score >= candidates[i + 1].score

    def test_wgs84_sanity_check(self):
        """
        lat must be in [-90, 90], lon in [-180, 180].
        """
        slope = compute_slope_deg(VALLEY_DEM)
        fd = compute_flow_direction(VALLEY_DEM)
        accum = compute_flow_accumulation(fd, VALLEY_DEM)

        candidates = find_candidates(VALLEY_DEM, accum, slope)

        for c in candidates:
            assert -90.0 <= c.lat <= 90.0
            assert -180.0 <= c.lon <= 180.0

    def test_flat_dem_returns_empty(self):
        """
        If slope > max everywhere (or we adjust settings to fail), no candidates emerge.
        """
        slope = compute_slope_deg(VALLEY_DEM)
        fd = compute_flow_direction(VALLEY_DEM)
        accum = compute_flow_accumulation(fd, VALLEY_DEM)

        # Override max slope to -1.0 so nothing passes (valleydem min slope is 0.0)
        original_max_slope = settings.max_candidate_slope_deg
        settings.max_candidate_slope_deg = -1.0

        try:
            candidates = find_candidates(VALLEY_DEM, accum, slope)
            assert len(candidates) == 0
        finally:
            settings.max_candidate_slope_deg = original_max_slope
