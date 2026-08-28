"""
A 7x7 bowl-shaped DEM fixture designed specifically for candidate point testing.

Features a gentle center basin that passes the default 15-degree slope filter,
unlike the 5x5 TOY_DEM which is steep everywhere.
"""

import numpy as np

from src.schemas.dem import DEM

# 7x7 grid: outer ring at 30, inner ring at 10, center 1x1 flat at 5
_valley_array = np.array(
    [
        [30, 30, 30, 30, 30, 30, 30],
        [30, 10, 10, 10, 10, 10, 30],
        [30, 10, 5, 3, 5, 10, 30],
        [30, 10, 3, 1, 3, 10, 30],  # row 3: center (3,3) is the valley floor (elev 1)
        [30, 10, 5, 3, 5, 10, 30],
        [30, 10, 10, 10, 10, 10, 30],
        [30, 30, 30, 30, 30, 30, 30],
    ],
    dtype=np.float32,
)

VALLEY_DEM = DEM(
    array=_valley_array,
    origin_x=0.0,
    origin_y=14.0,  # y decreases by 2 each row (14, 12, 10, 8, 6, 4, 2)
    cell_size=2.0,
    crs="EPSG:32644",
)
