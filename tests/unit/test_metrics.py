"""
Tests for Module 11 — Catchment Metrics Computation.
"""

import math

import pytest

from src.catchment.metrics import assert_area_consistency, compute_metrics
from src.dem.slope import compute_slope_deg
from src.hydrology.flow_accumulation import compute_flow_accumulation
from src.hydrology.flow_direction import compute_flow_direction
from src.hydrology.watershed import delineate_catchment
from tests.fixtures.toy_dem import TOY_DEM


@pytest.fixture
def metrics_and_accum():
    slope = compute_slope_deg(TOY_DEM)
    fd = compute_flow_direction(TOY_DEM)
    accum = compute_flow_accumulation(fd, TOY_DEM)
    mask = delineate_catchment(fd, seed_cells=[(4, 4)])

    metrics = compute_metrics(mask, TOY_DEM, slope)
    return metrics, int(accum[4, 4])


class TestComputeMetrics:
    def test_cell_count(self, metrics_and_accum):
        metrics, _ = metrics_and_accum
        assert metrics.cell_count == 16

    def test_area_ha_formula(self, metrics_and_accum):
        metrics, _ = metrics_and_accum
        # 16 cells * (2.0m)^2 / 10_000 = 0.0064 ha
        assert abs(metrics.area_ha - 0.0064) < 1e-9

    def test_elevation_stats(self, metrics_and_accum):
        metrics, _ = metrics_and_accum
        assert metrics.elevation_stats["min"] == 12.0
        assert metrics.elevation_stats["max"] == 18.0
        assert abs(metrics.elevation_stats["mean"] - 15.0) < 1e-4

    def test_slope_stats(self, metrics_and_accum):
        metrics, _ = metrics_and_accum
        expected = math.degrees(math.atan(1 / math.sqrt(2)))  # approx 35.2644 degrees
        assert abs(metrics.slope_stats["min"] - expected) < 0.001
        assert abs(metrics.slope_stats["max"] - expected) < 0.001
        assert abs(metrics.slope_stats["mean"] - expected) < 0.001

    def test_area_consistency_passes(self, metrics_and_accum):
        metrics, accum_at_pour = metrics_and_accum
        # For TOY_DEM, accum[4,4]=16 and mask.sum()=16 (pysheds includes self in accum).
        # With the new invariant: cell_count == flow_accum_at_sinks + num_seeds.
        # Here: 16 == 16 + 0 → pass num_seeds=0 since self is already included.
        assert (
            assert_area_consistency(
                metrics, flow_accum_at_sinks=accum_at_pour, num_seeds=0
            )
            is True
        )

    def test_area_consistency_fails_on_mismatch(self, metrics_and_accum):
        metrics, _ = metrics_and_accum
        # Passing wrong accum value should return False without raising
        assert (
            assert_area_consistency(metrics, flow_accum_at_sinks=25, num_seeds=1)
            is False
        )
