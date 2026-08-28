"""
Computes area and terrain statistics for delineated catchments.
"""

import logging

import numpy as np

from src.schemas.catchment import CatchmentMetrics
from src.schemas.dem import DEM

_log = logging.getLogger(__name__)


def compute_metrics(mask: np.ndarray, dem: DEM, slope: np.ndarray) -> CatchmentMetrics:
    """Compute area and terrain statistics for a catchment mask."""

    # 1. Cell count (True values in the mask)
    cell_count = int(mask.sum())

    # 2. Area using the exact HLD formula
    area_ha = cell_count * (dem.cell_size**2) / 10_000

    # 3. Elevation stats — only at masked cells
    masked_elevs = dem.array[mask]
    elevation_stats = {
        "min": float(masked_elevs.min()),
        "max": float(masked_elevs.max()),
        "mean": float(masked_elevs.mean()),
    }

    # 4. Slope stats — only at masked cells
    masked_slopes = slope[mask]
    slope_stats = {
        "min": float(masked_slopes.min()),
        "max": float(masked_slopes.max()),
        "mean": float(masked_slopes.mean()),
    }

    return CatchmentMetrics(
        area_ha=area_ha,
        cell_count=cell_count,
        elevation_stats=elevation_stats,
        slope_stats=slope_stats,
    )


def assert_area_consistency(
    metrics: CatchmentMetrics,
    flow_accum_at_pour_point: int,
) -> bool:
    """
    Cross-checks cell_count against flow accumulation at the pour point.

    By construction, these should be equal: accumulation IS the upstream cell count.
    A mismatch indicates a bug in the flow-direction or watershed algorithm.

    Returns True if consistent, logs a warning and returns False if not.
    """
    if metrics.cell_count != flow_accum_at_pour_point:
        _log.warning(
            "Area consistency check FAILED: cell_count=%d, flow_accum=%d. "
            "This may indicate a flow-direction or BFS bug.",
            metrics.cell_count,
            flow_accum_at_pour_point,
        )
        return False
    return True
