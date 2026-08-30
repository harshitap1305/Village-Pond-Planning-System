"""
Deterministic 4-bowl DEM fixture for Module 9 unit testing.

Grid: 80×80 cells at 10m cell_size = 800m × 800m map.
CRS: EPSG:32644 (UTM zone 44N), origin at (400000, 2200000).

Key thresholds at 10m cell_size:
  min_depression_area_sqm = 500m²  → ≥ 5 cells footprint
  min_catchment_area_ha   = 0.5ha  → ≥ 50 cells catchment

Fixtures:
  Bowl A (rows 40-49, cols 5-14): single minimum → had_flat_bottom=False
    Feeder (rows 5-39, cols 5-14): 250-cell uphill slope feeding into Bowl A.

  Bowl D (rows 40-49, cols 60-69): 2-cell flat bottom → had_flat_bottom=True
    Feeder (rows 5-39, cols 60-69): 250-cell uphill slope feeding into Bowl D.

  Bowl B (rows 5-6, cols 35-36): 4 cells = 400m² → filtered by area.
  Bowl C (rows 0-3, cols 0-4): edge-touching → discarded.
  Background: 50m everywhere else.

The bowls are designed so:
  - The rim (outermost bowl row/col) is at 48m < background (50m) so the
    boundary_ring correctly identifies the saddle.
  - The feeder grades from 60m → 49m, all above the rim (48m), so water
    from the feeder flows OVER the rim into the bowl.
  - Interior has a strict gradient (each ring is 2m lower) with no flat zones.
  - Single cell at minimum for A (38m), two adjacent at minimum for D.
"""

import numpy as np

from src.schemas.dem import DEM

ROWS, COLS = 80, 80
ORIGIN_X = 400_000.0
ORIGIN_Y = 2_200_000.0
CELL_SIZE = 10.0

# Uniform background
_arr = np.full((ROWS, COLS), 50.0, dtype=np.float32)

# ── Feeder A: rows 5-39, cols 5-14. Grades 60m at row 5 → 49m at row 39. ─────
for r in range(5, 40):
    e = 60.0 - (r - 5) * (11.0 / 34.0)  # 60 at r=5, ~49 at r=39
    _arr[r, 5:15] = float(e)

# ── Bowl A: rows 40-49, cols 5-14. Concentric elevation. ─────────────────────
# Each ring is 2m lower. Ring from outside in:
# row 40 / row 49 / col 5 / col 14: rim at 48m (these are the boundary cells)
# row 41 / row 48 / col 6 / col 13: 46m
# row 42 / row 47 / col 7 / col 12: 44m
# row 43 / row 46 / col 8 / col 11: 42m
# row 44 / row 45 / col 9 / col 10: center zone
# The very center: only (44, 9) at 38m; all others at 40m.
_bowl_a_matrix = np.array(
    [
        # cols: 5    6    7    8    9   10   11   12   13   14
        [48, 48, 48, 48, 48, 48, 48, 48, 48, 48],  # row 40
        [48, 46, 46, 46, 46, 46, 46, 46, 46, 48],  # row 41
        [48, 46, 44, 44, 44, 44, 44, 44, 46, 48],  # row 42
        [48, 46, 44, 42, 42, 42, 42, 44, 46, 48],  # row 43
        [48, 46, 44, 42, 38, 40, 42, 44, 46, 48],  # row 44 — single min at (44,9)
        [48, 46, 44, 42, 40, 40, 42, 44, 46, 48],  # row 45
        [48, 46, 44, 42, 42, 42, 42, 44, 46, 48],  # row 46
        [48, 46, 44, 44, 44, 44, 44, 44, 46, 48],  # row 47
        [48, 46, 46, 46, 46, 46, 46, 46, 46, 48],  # row 48
        [48, 48, 48, 48, 48, 48, 48, 48, 48, 48],  # row 49
    ],
    dtype=np.float32,
)
_arr[40:50, 5:15] = _bowl_a_matrix

# ── Feeder D: rows 5-39, cols 60-69. Same slope as Feeder A. ─────────────────
for r in range(5, 40):
    e = 60.0 - (r - 5) * (11.0 / 34.0)
    _arr[r, 60:70] = float(e)

# ── Bowl D: rows 40-49, cols 60-69. Two cells at minimum. ────────────────────
_bowl_d_matrix = np.array(
    [
        # cols: 60   61   62   63   64   65   66   67   68   69
        [48, 48, 48, 48, 48, 48, 48, 48, 48, 48],  # row 40
        [48, 46, 46, 46, 46, 46, 46, 46, 46, 48],  # row 41
        [48, 46, 44, 44, 44, 44, 44, 44, 46, 48],  # row 42
        [48, 46, 44, 42, 42, 42, 42, 44, 46, 48],  # row 43
        [
            48,
            46,
            44,
            42,
            38,
            38,
            42,
            44,
            46,
            48,
        ],  # row 44 — FLAT BOTTOM at (44,64) and (44,65)
        [48, 46, 44, 42, 40, 40, 42, 44, 46, 48],  # row 45
        [48, 46, 44, 42, 42, 42, 42, 44, 46, 48],  # row 46
        [48, 46, 44, 44, 44, 44, 44, 44, 46, 48],  # row 47
        [48, 46, 46, 46, 46, 46, 46, 46, 46, 48],  # row 48
        [48, 48, 48, 48, 48, 48, 48, 48, 48, 48],  # row 49
    ],
    dtype=np.float32,
)
_arr[40:50, 60:70] = _bowl_d_matrix

# ── Bowl B: rows 5-6, cols 35-36 (4 cells = 400m²) ──────────────────────────
_arr[5, 35] = 49.5
_arr[5, 36] = 49.5
_arr[6, 35] = 49.0
_arr[6, 36] = 49.0

# ── Bowl C: rows 0-3, cols 0-4 (edge-touching) ───────────────────────────────
for r in range(0, 4):
    for c in range(0, 5):
        _arr[r, c] = 48.0 - r

DEPRESSION_DEM = DEM(
    array=_arr,
    origin_x=ORIGIN_X,
    origin_y=ORIGIN_Y,
    cell_size=CELL_SIZE,
    crs="EPSG:32644",
)

# Spatial reference points for test assertions
BOWL_A_ROW_RANGE = (40, 49)
BOWL_A_COL_RANGE = (5, 14)
BOWL_A_MIN_RC = (44, 9)

BOWL_D_ROW_RANGE = (40, 49)
BOWL_D_COL_RANGE = (60, 69)
BOWL_D_FLAT_RCS = [(44, 64), (44, 65)]

BOWL_B_COL_RANGE = (35, 36)
BOWL_B_ROW_RANGE = (5, 6)
BOWL_C_ROW_RANGE = (0, 3)
BOWL_C_COL_RANGE = (0, 4)
