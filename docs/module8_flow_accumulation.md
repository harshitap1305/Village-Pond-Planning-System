# Module 8 — Flow Accumulation

> **Status:** Complete ✅ | **Tests:** 154/154 passing (cumulative) | **Commit range:** `3279e43 → 6ffcf58`

---

## Overview

Module 8 calculates the **Flow Accumulation** grid. By tracing the D8 flow direction network established in Module 7, this algorithm counts exactly how many upstream cells drain into any given cell on the map.

- **Low Accumulation (e.g. 1-10 cells):** Ridges, peaks, and hillslopes where water diverges.
- **High Accumulation (e.g. 100,000+ cells):** Valley bottoms, established streams, and natural sinks where water converges.

This accumulation grid is the direct mathematical proxy for a "stream network" and is the primary indicator used in Module 9 to identify viable candidate locations for excavating a village pond.

---

## Files Created

```
src/
└── hydrology/
    └── flow_accumulation.py     ← [NEW] Accumulation engine + stream filter

scripts/
└── debug_plot_accumulation.py   ← [NEW] Visual validation of stream networks

tests/
└── unit/
    └── test_flow_accumulation.py← [NEW] Unit tests against mathematical anchor
```

---

## 1. The `pysheds` Accumulation Engine

**File:** [`src/hydrology/flow_accumulation.py`](../src/hydrology/flow_accumulation.py)

Instead of hand-rolling a topological graph traversal in Python (which is prohibitively slow for millions of cells), we leverage the C-optimized `grid.accumulation()` function from `pysheds`.

```python
# Create pysheds Grid and Raster mapping
transform = Affine(dem.cell_size, 0.0, dem.origin_x, 0.0, -dem.cell_size, dem.origin_y)
vf = ViewFinder(affine=transform, shape=dem.array.shape, nodata=0, crs=dem.crs)
fd_raster = Raster(flow_dir.astype(np.int32), viewfinder=vf)

grid = Grid()
grid.viewfinder = vf

accum_raster = grid.accumulation(fdir=fd_raster)
```

### The `np.bincount` Monkeypatch
During implementation, we uncovered an obscure `IndexError` bug inside `pysheds` v0.3.x that triggers exclusively on large grids where water flows off the map boundaries.

**The Bug:** `pysheds` routes off-grid boundary cells into a virtual "sink node" at `index = array.size`. When `np.bincount` runs internally, it returns an array sized `array.size + 1`. The library then attempts to use this oversized array as a boolean mask against a standard-sized array, crashing the application.

**The Fix:** We implemented a scoped monkeypatch in `compute_flow_accumulation()` that safely intercepts `np.bincount` and explicitly truncates the virtual sink node before it crashes the masking operation, resolving the issue without altering the underlying math.

---

## 2. Drainage Network Filtering

In addition to the raw accumulation values, we implemented a helper function to isolate major stream channels:

```python
def top_accumulation_cells(accum: np.ndarray, percentile: float = 90.0) -> np.ndarray:
```

This returns a boolean mask of the highest X% of accumulating cells. Identifying these streams mathematically replaces the need for subjective visual tracing of the drainage networks.

---

## 3. Visualization and Debugging

**File:** [`scripts/debug_plot_accumulation.py`](../scripts/debug_plot_accumulation.py)

Because accumulation values grow exponentially as streams merge, plotting the raw accumulation array produces a mostly black image with a few white outlet pixels.

The debug script solves this by mapping the array to a base-10 logarithmic scale (`np.log10(accum + 1)`). Running this on the 1-metre sample contours reveals a beautifully crisp dendritic drainage network perfectly aligning with the valley floors of the input DEM.

---

## 4. Test Coverage

**File:** [`tests/unit/test_flow_accumulation.py`](../tests/unit/test_flow_accumulation.py)

We reused the 5×5 `TOY_DEM` from Module 7 to rigorously test the accumulation logic:
- **Ridge Test:** Asserted that the highest cell (0, 0) receives zero inflow, meaning its accumulation score is precisely `1` (itself).
- **Diagonal Flow Test:** Traced the exact mathematical progression along the valley diagonal to ensure accumulation grows strictly monotonically.
- **Outlet Wrap-around Verification:** Verified that the main outlet collects exactly `16` cells. (It does not collect all 25 because the top row and left column correctly drain off the boundary of the map, simulating a watershed divide).

The test suite now totals **154 passing tests**.

---

## What Comes Next

With the terrain mapped (Modules 1-6), flow direction calculated (Module 7), and the drainage channels quantified (Module 8), we are ready for **Module 9: Pond Candidate Location Identification**.

Module 9 will cross-reference the `top_accumulation_cells` (to guarantee water supply) against the `slope` array (to avoid extremely steep terrain), automatically clustering the results into real-world geographic coordinates for the best possible pond locations.
