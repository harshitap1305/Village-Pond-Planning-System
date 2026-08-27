# Module 5 — DEM Construction via Interpolation

> **Status:** Complete ✅ | **Tests:** 136/136 passing (cumulative) | **Commit range:** `174e2fb → fb2f70a`

---

## Overview

Module 5 is responsible for **rasterization**. It takes the unstructured, scattered metric points from Module 4 (the `PointCloud`) and interpolates them into a regular 2D grid — a **Digital Elevation Model (DEM)**.

Every single hydrological algorithm that follows (slope, flow direction, accumulation, and watershed delineation) fundamentally relies on this regular grid structure.

```
PointCloud (Scattered)                DEM (Regular Grid)
      x, y, z            →         [[281.2, 281.0, 280.9],
                                    [281.4, 281.1, 280.8],
                                    [281.5, 281.2, 280.6]]
                                   + origin_x, origin_y, cell_size
```

---

## Files Created

```
src/
├── schemas/
│   └── dem.py            ← [NEW] DEM Pydantic model + geotransform
└── dem/
    └── builder.py        ← [NEW] build_dem() + validate_dem()

scripts/
└── debug_plot_dem.py     ← [NEW] Manual visual debug script

tests/
└── unit/
    └── test_dem_builder.py← [NEW] 25 tests for DEM construction
```

---

## 1. The `DEM` Schema

**File:** [`src/schemas/dem.py`](../src/schemas/dem.py)

The output of this module is the `DEM` schema, which wraps a `numpy` 2D array and stores the metadata required to map a cell back to real-world coordinates (a "geotransform").

```python
class DEM(BaseModel):
    array: Any              # 2D numpy array of elevations (float32)
    origin_x: float         # Easting of top-left corner
    origin_y: float         # Northing of top-left corner
    cell_size: float        # Cell width/height (metres)
    crs: str                # EPSG string propagated from PointCloud
    nodata: float = -9999.0 # Sentinel value
```

**Key Design Features:**
- **Arbitrary Types Allowed:** Because Pydantic natively struggles with deep inspection of numpy arrays, we set `arbitrary_types_allowed=True` and use a custom `@field_validator` to enforce that the input is precisely a 2D `ndarray`.
- **Top-Left Origin:** `origin_y` refers to the Northernmost bound of the grid. Array rows increase *Southward*. This matches standard GIS conventions (like GDAL/rasterio), guaranteeing painless GeoTIFF exports in later phases.
- **Float32 Precision:** DEM arrays are strictly cast to `float32`. Given typical village catchment sizes, an array can exceed a million cells. `float32` provides millimetre precision for elevations while halving memory consumption compared to `float64`.

---

## 2. Interpolation Strategy (`build_dem`)

**File:** [`src/dem/builder.py`](../src/dem/builder.py)

We use `scipy.interpolate.griddata` to project the scattered data onto our uniform grid. However, we employ a highly deliberate **Two-Pass Interpolation** strategy.

### Pass 1: Linear Interpolation
```python
grid_linear = griddata(points, values, (xi, yi), method="linear")
```
Linear interpolation creates an accurate, smooth surface by building a TIN (Triangulated Irregular Network) between the scattered points. However, it *cannot extrapolate outside the convex hull of the input data*. This leaves a jagged border of `NaN` (Not-a-Number) cells at the rectangular grid edges.

### Pass 2: Nearest-Neighbour Fill
```python
nan_mask = np.isnan(grid_linear)
if nan_mask.any():
    grid_nearest = griddata(points, values, (xi, yi), method="nearest")
    grid_linear[nan_mask] = grid_nearest[nan_mask]
```
A single `NaN` cell in a slope or flow direction array will poison the math and propagate errors throughout the entire catchment basin. We run a second `nearest` interpolation pass strictly applied to the `NaN` mask. This safely plugs the edge gaps, ensuring the downstream numpy matrix operations never encounter invalid numbers.

---

## 3. The Sanity Check (`validate_dem`)

**File:** [`src/dem/builder.py`](../src/dem/builder.py)

Interpolation can occasionally "blow up" if the algorithm encounters weird geometric edge cases. The `validate_dem()` function compares the raw `ContourLine` maximum and minimum elevations against the generated `DEM` array max/min.

If the grid contains elevation spikes outside a strictly calculated safety tolerance (5% of the overall elevation range, or a minimum of 1m), it throws a `ValueError` rather than allowing a corrupted grid to pass into the hydrology engine.

---

## 4. Test Coverage

**File:** [`tests/unit/test_dem_builder.py`](../tests/unit/test_dem_builder.py)

We added **25 tests**, relying heavily on a synthetic "Toy PointCloud".

### Highlights
- **The Toy DEM:** A synthetic flat plane placed at realistic UTM coordinate scales allows us to predictably assert what the grid shape, origin, and values should be.
- **NaN Enforcement:** Tests explicitly assert that after building, `np.isnan(dem.array).any()` is definitively False.
- **Real Fixture Validation:** Using our real `contours_1m.kml`, tests assert that the final generated grid is over 100x100 cells, has no NaNs, and stays firmly within the 267.0–298.0 metre elevation range expected by the source KML.

---

## What Comes Next

We now have a mathematically sound, completely filled, high-precision metric grid of our terrain.

**Module 6** will prepare this DEM for hydrological simulation. Real terrain data contains artificial "sinks" (depressions or pits caused by interpolation artifacts) that would trap virtual water routing. We will implement **Sink Filling** and generate a **Slope Raster** to mathematically define how steep the terrain is at every cell.
