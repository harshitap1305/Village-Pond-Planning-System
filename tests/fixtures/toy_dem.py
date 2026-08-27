"""
Toy DEM and expected flow direction fixture for Module 7 and Module 8 tests.

The DEM is a 5x5 tilted plane that drops 1m every step going South and East.
Origin is top-left (North-West). Elevation at (row, col) = 20 - row - col.

   20  19  18  17  16
   19  18  17  16  15
   18  17  16  15  14
   17  16  15  14  13
   16  15  14  13  12
                    ^
                    lowest cell (outlet at bottom-right)

All interior cells have their steepest drop toward South-East (code 2).
"""

import numpy as np

from src.schemas.dem import DEM

CELL_SIZE = 2.0  # metres

# Elevation surface: 5x5, drops going SE
_rows, _cols = np.mgrid[0:5, 0:5]
TOY_ARRAY = (20.0 - _rows - _cols).astype(np.float32)

TOY_DEM = DEM(
    array=TOY_ARRAY,
    origin_x=0.0,
    origin_y=10.0,
    cell_size=CELL_SIZE,
    crs="EPSG:32644",
)

# Hand-computed expected D8 codes for every cell.
# Interior cells: steepest drop is SE -> code 2.
# Edge and corner cells will have wrapping artifacts from np.roll, so we
# only assert on interior cells [1:4, 1:4] in the tests.
EXPECTED_INTERIOR_CODE = 2  # SE
