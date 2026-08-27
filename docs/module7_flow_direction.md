# Module 7 — Flow Direction (D8 Algorithm)

> **Status:** Complete ✅ | **Tests:** 149/149 passing (cumulative) | **Commit range:** `df37a21 → 880fdd9`

---

## Overview

Module 7 calculates the **D8 Flow Direction**. For every single cell in our conditioned DEM, this algorithm evaluates all 8 neighboring cells, finds the steepest downhill slope, and encodes that direction as an integer.

This raster matrix of directions acts as the "gravitational map" for all subsequent hydrology modules, directing simulated rainfall downhill to form streams and catchments.

```
Elevation (DEM)                Flow Direction (D8 Code)
 [[10,  9,  8],                  [[2, 2, 2],
  [11, 10,  7],        →          [1, 2, 2],
  [12, 11,  6]]                   [1, 1, 2]]
```

---

## Files Created

```
src/
└── hydrology/
    ├── __init__.py           ← [NEW] Package init
    └── flow_direction.py     ← [NEW] D8 numpy implementation

tests/
├── fixtures/
│   └── toy_dem.py            ← [NEW] 5x5 tilted valley DEM
└── unit/
    └── test_flow_direction.py← [NEW] Directionality and diagonal math tests
```

---

## 1. D8 Direction Encoding Convention

We strictly follow the **ArcGIS / pysheds Power-of-2 encoding scheme**:

| Code | Direction |
|------|-----------|
| 1    | East (→) |
| 2    | South-East (↘) |
| 4    | South (↓) |
| 8    | South-West (↙) |
| 16   | West (←) |
| 32   | North-West (↖) |
| 64   | North (↑) |
| 128  | North-East (↗) |

**Code `0`** is reserved for flat cells or sinks (where no neighboring cell is lower than the center).

*Design Choice:* By adhering to this exact power-of-2 convention, we ensure our output raster can be passed seamlessly into standard off-the-shelf routing algorithms (like `pysheds.accumulation`) in Module 8 without costly translation layers.

---

## 2. Vectorized Implementation (`compute_flow_direction`)

**File:** [`src/hydrology/flow_direction.py`](../src/hydrology/flow_direction.py)

Calculating drops cell-by-cell in Python using nested `for` loops is unacceptably slow (taking up to 30 seconds for a 2.1 million cell grid). We implemented a **fully vectorized approach** using `numpy.roll` that executes in fractions of a second.

**The Math:**
1. We shift the entire elevation array in all 8 directions.
2. We calculate the slope drop: `(elev - neighbor) / distance`.
   - *Crucially, orthogonal distance is `cell_size`, but diagonal distance is `cell_size * sqrt(2)`.*
3. We stack the 8 results and use `np.argmax(drops, axis=0)` to find the index of the steepest drop simultaneously across the entire map.

---

## 3. The `TOY_DEM` Fixture

**File:** [`tests/fixtures/toy_dem.py`](../tests/fixtures/toy_dem.py)

To ensure mathematical perfection moving forward, we created a static, hard-coded 5×5 DEM fixture.
It acts as a perfectly tilted plane dropping South and East:

```
20  19  18  17  16
19  18  17  16  15
18  17  16  15  14
17  16  15  14  13
16  15  14  13  12  ← Lowest cell (outlet)
```

Because of its uniform geometry, we mathematically know that **every interior cell must flow exactly South-East (Code `2`)**. This serves as the ground-truth anchor for our tests.

---

## 4. Test Coverage

**File:** [`tests/unit/test_flow_direction.py`](../tests/unit/test_flow_direction.py)

We added **9 new tests**, bringing the suite up to 149 passing tests.

### Highlights
- **Directional Gradients:** We generate entirely separate test DEMs sloping uniformly North, South, and East, explicitly asserting that the output D8 codes are `64`, `4`, and `1` respectively.
- **The Diagonal Sqrt(2) Test:** `test_steep_diagonal_beats_shallow_orthogonal` specifically targets the `distance` divisor logic. It creates a terrain where dropping diagonally covers more elevation, but is further away. It asserts that the algorithm correctly scales the physical diagonal distance by `math.sqrt(2)` before declaring a "winner".

---

## What Comes Next

With every cell pointing to its steepest downhill neighbor, **Module 8** will implement **Flow Accumulation**. It will trace these flow paths from the ridges down to the valleys, counting how many upstream cells drain into each target cell, thereby outlining the actual streams and drainage networks of the terrain.
