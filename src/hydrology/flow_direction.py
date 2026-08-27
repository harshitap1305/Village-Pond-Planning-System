"""
D8 flow direction algorithm.

For every cell in a conditioned (sink-free) DEM, computes the steepest
downhill direction among 8 neighbors and encodes it as a power-of-2 code.

Encoding convention (ArcGIS / pysheds compatible):
    32  64  128
    16   ·    1
     8   4    2

Code 0 = sink or flat (no valid downhill path).

Implementation is fully vectorized using numpy.roll — no Python loops.
"""

import math

import numpy as np

from src.schemas.dem import DEM

# (D8 code, row_delta, col_delta)
# Row delta: -1=North, +1=South
# Col delta: -1=West,  +1=East
_D8_DIRECTIONS: list[tuple[int, int, int]] = [
    (64, -1, 0),  # N
    (128, -1, +1),  # NE
    (1, 0, +1),  # E
    (2, +1, +1),  # SE
    (4, +1, 0),  # S
    (8, +1, -1),  # SW
    (16, 0, -1),  # W
    (32, -1, -1),  # NW
]

_D8_CODES = np.array([c for c, _, _ in _D8_DIRECTIONS], dtype=np.int16)


def compute_flow_direction(dem: DEM) -> np.ndarray:
    """
    Compute the D8 flow direction for every cell of a conditioned DEM.

    Args:
        dem: A sink-filled DEM (output of fill_sinks from Module 6).

    Returns:
        2D int16 array (same shape as dem.array) of D8 direction codes.
        Cells with no valid downhill neighbor are coded 0.
    """
    sqrt2 = math.sqrt(2)
    elev = dem.array.astype(np.float64)  # promote for precision in drops
    cs = dem.cell_size

    # Build 8 drop arrays, one per direction
    drop_arrays = []
    for _, dr, dc in _D8_DIRECTIONS:
        neighbor = np.roll(np.roll(elev, -dr, axis=0), -dc, axis=1)
        distance = cs * (sqrt2 if dr != 0 and dc != 0 else 1.0)
        drop = (elev - neighbor) / distance
        drop_arrays.append(drop)

    drops = np.stack(drop_arrays, axis=0)  # (8, rows, cols)

    # Index of the direction with the steepest positive drop
    best_idx = np.argmax(drops, axis=0)  # (rows, cols)
    max_drop = drops[
        best_idx, np.arange(dem.rows)[:, None], np.arange(dem.cols)[None, :]
    ]

    # Assign codes; flat/sink cells -> 0
    flow_dir = np.where(max_drop > 0, _D8_CODES[best_idx], 0).astype(np.int16)

    return flow_dir
