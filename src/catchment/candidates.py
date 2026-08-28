"""
Pond Candidate Location Identification.

Finds suitable sites for a village pond by intersecting flow accumulation
(water supply) and slope (topographic suitability).
"""

from typing import List

import numpy as np
from pyproj import Transformer
from scipy import ndimage

from src.config import settings
from src.schemas.catchment import CandidatePoint
from src.schemas.dem import DEM


def find_candidates(
    dem: DEM, flow_accum: np.ndarray, slope: np.ndarray
) -> List[CandidatePoint]:
    """
    Identifies pond candidate locations by intersecting water supply
    (flow_accum) and topographic suitability (slope) constraints.

    Args:
        dem: The DEM over which the candidates are calculated.
        flow_accum: A 2D array of flow accumulation values.
        slope: A 2D array of slope values in degrees.

    Returns:
        A list of CandidatePoint objects, sorted descending by score, truncated
        to settings.max_candidates.
    """
    # 1. Dynamic threshold from config (never hard-coded)
    accum_cutoff = np.percentile(flow_accum, settings.accumulation_percentile_threshold)

    # 2. Boolean intersection mask
    mask = (flow_accum >= accum_cutoff) & (slope <= settings.max_candidate_slope_deg)

    # 3. Label contiguous clusters (8-connectivity)
    structure = np.ones((3, 3), dtype=int)
    labeled_array, num_features = ndimage.label(mask, structure=structure)

    if num_features == 0:
        return []

    # 4. Prepare transformer: UTM -> WGS84
    # Note: pyproj direction is 'EPSG:4326' -> 'EPSG:X'. We invert it by swapping args.
    transformer = Transformer.from_crs(dem.crs, "EPSG:4326", always_xy=True)

    candidates = []
    max_accum_global = float(np.max(flow_accum))

    # 5. Extract representative point per cluster
    for cluster_id in range(1, num_features + 1):
        cluster_mask = labeled_array == cluster_id
        cluster_accum = np.where(cluster_mask, flow_accum, -1)
        max_idx = np.argmax(cluster_accum)
        row, col = np.unravel_index(max_idx, flow_accum.shape)

        # 6. (row, col) -> UTM cell centroid
        x = dem.origin_x + (col * dem.cell_size) + (dem.cell_size / 2.0)
        y = dem.origin_y - (row * dem.cell_size) - (dem.cell_size / 2.0)

        # 7. UTM -> WGS84
        lon, lat = transformer.transform(x, y)

        # 8. Score and append
        score = float(flow_accum[row, col]) / max_accum_global
        candidates.append(
            CandidatePoint(
                lat=lat,
                lon=lon,
                elevation=float(dem.array[row, col]),
                score=score,
            )
        )

    # Sort best-first and truncate to max_candidates
    return sorted(candidates, key=lambda c: c.score, reverse=True)[
        : settings.max_candidates
    ]
