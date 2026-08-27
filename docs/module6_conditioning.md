# Module 6 — DEM Conditioning & Slope

> **Status:** Complete ✅ | **Tests:** 140/140 passing (cumulative) | **Commit range:** `08d5289 → df37a21`

---

## Overview

Module 6 takes the raw DEM grid from Module 5 and mathematically prepares it for hydrological simulations (sink filling) and suitability analysis (slope).

1. **Sink Filling:** Raw interpolated DEMs contain artificial "pits" or "sinks" — cells entirely surrounded by higher-elevation neighbors. If uncorrected, these pits trap simulated water routing, fracturing the drainage network. Sink filling raises the elevation of these pits to match their lowest boundary, guaranteeing continuous downhill flow to the map edge.
2. **Slope:** Computing the steepness of the terrain in degrees is a fundamental prerequisite for identifying viable pond excavation sites in Module 9.

---

## Files Created

```
src/
└── dem/
    ├── conditioning.py       ← [NEW] fill_sinks() using pysheds
    └── slope.py              ← [NEW] compute_slope_deg() using numpy

scripts/
└── debug_plot_conditioning.py← [NEW] Visual verification of fill depth & slope

tests/
└── unit/
    ├── test_conditioning.py  ← [NEW] Sink-fill unit tests
    └── test_slope.py         ← [NEW] Analytical slope correctness tests
```

---

## 1. Sink Filling (`pysheds`)

**File:** [`src/dem/conditioning.py`](../src/dem/conditioning.py)

We utilize the `pysheds` library for depression filling. However, interfacing raw numpy arrays with `pysheds` requires rigorous spatial alignment.

```python
# 1. Create a ViewFinder mapping array space to geographic space
transform = Affine(dem.cell_size, 0.0, dem.origin_x, 0.0, -dem.cell_size, dem.origin_y)
vf = ViewFinder(affine=transform, shape=dem.array.shape, nodata=dem.nodata, crs=dem.crs)

# 2. Wrap numpy array in a pysheds Raster, initialize Grid
raster = Raster(dem.array, viewfinder=vf)
grid = Grid()
grid.viewfinder = vf

# 3. Fill depressions
filled_raster = grid.fill_depressions(raster)
```

**Key Features:**
- By explicitly constructing a `ViewFinder` and an Affine `transform`, we guarantee that `pysheds` doesn't inadvertently warp or default the coordinate space to WGS84, preserving our metric `EPSG:32644` geometry.

---

## 2. Slope Calculation

**File:** [`src/dem/slope.py`](../src/dem/slope.py)

We hand-rolled the slope calculation using `numpy.gradient` because it is significantly faster than booting up a full spatial library just for a topographic derivative.

```python
# Calculate partial derivatives (m/m)
dy, dx = np.gradient(dem.array, dem.cell_size, dem.cell_size)

# Convert to angle in degrees
slope_deg = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))
```

**Key Features:**
- **2nd-Order Accurate:** `np.gradient` uses second-order accurate central differences in the interior and first-order accurate differences at the boundaries, providing high-quality, smooth slope transitions.
- **Metric Dependency:** This math is only physically correct because Module 4 successfully converted all coordinates to metres. If we were still in degrees, the dx/dy scale would be disastrously skewed.

---

## 3. Test Coverage & Debug Insights

**Files:** [`tests/unit/test_conditioning.py`](../tests/unit/test_conditioning.py), [`tests/unit/test_slope.py`](../tests/unit/test_slope.py)

### Testing Highlights
- **Analytical Plane Test:** The slope algorithm was tested against a mathematically defined 45-degree tilted plane, ensuring the gradient calculation exactly matches standard trigonometry.
- **Artificial Pit Test:** `test_fills_artificial_pit` creates a 5x5 plane at 280m, carves a 275m pit in the center, and asserts that `fill_sinks` lifts it exactly back to 280m while leaving edges untouched.

### Debug Plot Results
Running `scripts/debug_plot_conditioning.py` on the sample map revealed:
- **Max Fill Depth:** 12.00 metres (highlighting the massive importance of this step — a 12m deep interpolation artifact would have completely ruined the catchment simulation).
- **Slope Range:** 0.0 to 68.5 degrees (realistic for hilly/gorge terrain).

---

## What Comes Next

With the terrain safely conditioned and smoothed, **Module 7** will simulate the actual flow of gravity. We will implement the **D8 Flow Direction** algorithm, calculating the steepest downhill path for every single cell.
