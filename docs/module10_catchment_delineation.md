# Module 10 — Catchment Delineation (Watershed Extraction)

> **Status:** Complete ✅ | **Tests:** 169/169 passing (cumulative) | **Commit range:** `5400318 → aabc995`

---

## Overview

Module 10 connects the mathematical dots between a specific terrain point and the land area that drains into it. Given the coordinates of a "pour point" (e.g., the pond candidate location identified in Module 9), this module runs a **Breadth-First Search (BFS)** directly up the flow-direction graph to trace every square meter of contributing watershed.

It then translates that boolean array mask into a clean, simplified Shapely `Polygon` (or `MultiPolygon`) with valid WGS84 GPS coordinates for frontend mapping.

---

## Files Created

```
src/
└── hydrology/
    └── watershed.py          ← [NEW] BFS delineation algorithm
└── catchment/
    └── polygonize.py         ← [NEW] Mask vectorization & CRS reprojection

tests/
└── unit/
    ├── test_watershed.py     ← [NEW] BFS boundary validation
    └── test_polygonize.py    ← [NEW] Vectorization & GIS coordinate verification
```

---

## 1. Watershed Delineation (The BFS)

**File:** [`src/hydrology/watershed.py`](../src/hydrology/watershed.py)

Because `richdem` isn't installed in the final environment, we opted for the pure, deterministic approach: a manual BFS graph traversal.

The D8 encoding from Module 7 (`1`, `2`, `4`, `8`, etc.) maps where a cell flows *downhill*. To find a watershed, we must trace *uphill*. We do this by mapping the graph in reverse:
```python
# Forward delta map mapping D8 codes to (row_delta, col_delta)
forward_delta = {code: (dr, dc) for code, dr, dc in _D8_DIRECTIONS}

# Identify all upstream cells flowing into (r, c)
incoming = [[[] for _ in range(cols)] for _ in range(rows)]
for r in range(rows):
    for c in range(cols):
        code = flow_dir[r, c]
        if code in forward_delta:
            dr, dc = forward_delta[code]
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols:
                incoming[nr][nc].append((r, c))
```

We then run a standard BFS (`collections.deque`) starting from the `pour_point_rc`, queuing up incoming neighbors until we hit the ridge lines where no more cells flow in. This completes in `O(N)` time and outputs a boolean mask of the catchment.

---

## 2. Catchment Polygonization

**File:** [`src/catchment/polygonize.py`](../src/catchment/polygonize.py)

The frontend requires GIS vectors (GeoJSON), not binary numpy arrays. We bridge this gap using a 5-step pipeline:

1. **Raster to Vector (`rasterio.features.shapes`)**: Extracts raw polygonal boundaries from the `1` values in the mask using the DEM's original UTM geotransform.
2. **Merging (`shapely.ops.unary_union`)**: Handles cases where the watershed mask is technically non-contiguous (e.g. flat areas with identical elevations) by fusing fragments together.
3. **Simplification (`shapely.Polygon.simplify`)**: Reduces the vertex count. This honors the HLD risk-mitigation strategy regarding frontend map performance when rendering massive catchment polygons.
4. **Reprojection (`pyproj.Transformer`)**: Transforms the local metric UTM coordinates back to global WGS84 (`EPSG:4326`) longitude/latitude.
5. **Output**: Returns a standard `shapely.geometry.BaseGeometry` ready to be serialized to GeoJSON by the API layer.

---

## 3. Test Coverage

We built two dedicated test files against the `TOY_DEM` to ensure absolute correctness.

**Watershed Delineation Tests**
- Confirmed that a pour point at `(4, 4)` (the absolute lowest point in the toy DEM) correctly traces back and captures exactly **16 cells**.
- The top row and left column correctly evaluate to `False` (excluded) because they drain off the edge of the array due to `np.roll` wrap-around boundary conditions in Module 7.
- Proved that placing a pour point at the highest ridge `(0, 0)` correctly returns a 1-cell watershed.

**Polygonization Tests**
- Verified the resulting Shapely polygon is topologically valid.
- Assured the polygon area is mathematically sound. (16 cells × 2m × 2m = 64 m²).
- Confirmed all bounding box coordinates fall strictly within WGS84 bounds (`-90 ≤ lat ≤ 90` and `-180 ≤ lon ≤ 180`).

---

## What Comes Next

We have the geographic shape of the watershed. **Module 11: Catchment Metrics Computation** will now overlay this shape onto the original terrain to calculate the exact metric area in hectares and extract statistical summaries for slope and elevation across the catchment.
