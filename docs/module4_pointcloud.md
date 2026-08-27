# Module 4 — Point Cloud Extraction & Coordinate Normalization

> **Status:** Complete ✅ | **Tests:** 111/111 passing (cumulative) | **Commit range:** `62ec77c → 666fc1f`

---

## Overview

Module 4 converts raw terrain data from geographic coordinates (degrees) into a metric coordinate system (metres). This is a critical prerequisite for all subsequent modules.

If downstream algorithms (DEM builder, slope calculation, area measurement) attempt to calculate distances in degrees, the results will be highly distorted because degrees of longitude physically shrink as you move away from the equator. By converting everything into a **Universal Transverse Mercator (UTM)** projection up front, we ensure all math is done on a flat, uniform metric grid.

```
List[ContourLine]            PointCloud (Metres)
  elevation: float      →      x: List[float]   ← Easting (UTM)
  points: (lon, lat)           y: List[float]   ← Northing (UTM)
       (WGS84)                 z: List[float]   ← Elevation (unchanged)
                               crs: str         ← e.g. "EPSG:32644"
```

---

## Files Created

```
src/
├── schemas/
│   └── geometry.py       ← [NEW] PointCloud Pydantic model
└── geometry/
    ├── crs_utils.py      ← [NEW] detect_utm_epsg()
    └── pointcloud.py     ← [NEW] build_point_cloud()

tests/
└── unit/
    └── test_pointcloud.py← [NEW] 26 tests for CRS and Reprojection
```

---

## 1. The `PointCloud` Schema

**File:** [`src/schemas/geometry.py`](../src/schemas/geometry.py)

The output of this module is the `PointCloud` schema.

```python
class PointCloud(BaseModel):
    x: List[float]
    y: List[float]
    z: List[float]
    crs: str
```

**Key Features:**
- **Flattened Data:** We discard the distinct "lines" that make up the contours and simply dump all coordinate pairs into three parallel `x`, `y`, and `z` lists. The downstream DEM interpolator requires an unstructured cloud of XYZ points, not lines.
- **Strict Length Validation:** An `@model_validator` guarantees that `len(x) == len(y) == len(z)`.
- **String-based CRS:** The `crs` property is stored as a string (`"EPSG:32644"`) rather than a `pyproj.CRS` object to ensure the model remains JSON-serializable.

---

## 2. Automatic CRS Detection

**File:** [`src/geometry/crs_utils.py`](../src/geometry/crs_utils.py)

To satisfy the requirement that the application must **"generalize to other contour maps,"** we cannot hard-code the CRS. We use `detect_utm_epsg(lon, lat)` to automatically determine the correct UTM zone based on the data's geographic centroid.

**Formula Used:**
```python
zone = int((lon + 180) / 6) + 1
```

If the latitude is positive (Northern Hemisphere), the EPSG code is `32600 + zone`.
If the latitude is negative (Southern Hemisphere), the EPSG code is `32700 + zone`.

**Sample Evaluation:**
For the provided sample in Chhattisgarh, India (Lon ≈ 81.28°, Lat ≈ 21.26°), the formula evaluates to **UTM Zone 44N**, mapping to **EPSG:32644**.

---

## 3. The Point Cloud Builder

**File:** [`src/geometry/pointcloud.py`](../src/geometry/pointcloud.py)

The `build_point_cloud()` pipeline performs four operations:

### A. Flattening
Loops through every contour line and every `(lon, lat)` pair, flattening them into massive lists.

### B. Auto-Detection
Averages all longitude and latitude points to find the map's centroid, then passes it to `detect_utm_epsg()` to determine the target metric CRS.

### C. Reprojection with `always_xy=True`
Uses `pyproj.Transformer` to perform the mathematical reprojection from WGS84 to UTM.

> [!CAUTION]
> **The `always_xy=True` flag is critical.** By standard, EPSG:4326 defines its axes as (Latitude, Longitude). Without this flag, `pyproj` will silently flip the coordinates, leading to coordinates that appear valid but map to entirely different places on Earth. `always_xy=True` forces the expected (X, Y) / (Longitude, Latitude) order.

### D. De-duplication
Due to the nature of contour map exports, start and end points of circular contour rings often overlap perfectly. The builder rounds coordinates to 1 millimetre (`round(val, 3)`) and de-duplicates them. Feeding duplicate X/Y points with slightly varying floating-point noise to an interpolator can cause matrix singularities and crash the DEM builder.

---

## 4. Test Coverage

**File:** [`tests/unit/test_pointcloud.py`](../tests/unit/test_pointcloud.py)

We added **26 tests** to ensure total algorithmic safety during reprojection.

### Highlights
- **Regression Anchors:** `test_chhattisgarh_india_is_32644` proves that the UTM detection algorithm mathematically matches the expected zone for the client's specific dataset.
- **Metric Verification:** Tests verify that the reprojected X and Y lists contain values between 100,000 and 1,000,000 (standard UTM metric bounds), and explicitly assert that they are no longer in the -180 to 180 degree range.
- **Fixture Integration:** `TestRealFixture` loads `contours_1m.kml`, runs the full reprojection pipeline, and verifies that over 100,000 points are successfully converted without triggering a single `NaN`.

---

## 5. Design Decisions Log

| Decision | Rationale |
|----------|-----------|
| Reprojection happens immediately after ingestion | It is universally safer to work in metric space. This isolates geographic degrees to the absolute outer edge of the application. |
| `PointCloud` is unstructured (no lines) | Linear interpolation (`scipy.interpolate.griddata`) does not know what a "line" is; it requires an unstructured scatter of points. |
| Automatic UTM detection | Avoids hard-coding the EPSG string for India, ensuring the system can ingest contour maps from anywhere in the world per Phase 1 requirements. |
| 1mm precision for dedup | Resolves floating-point noise from KML exports without collapsing genuinely distinct points that exist just a few centimetres apart. |

---

## What Comes Next

With coordinates safely converted to metres, **Module 5** will feed this massive `PointCloud` into `scipy.interpolate.griddata`. It will generate a grid (e.g., 2m x 2m cells) and assign an interpolated elevation to every single cell, outputting a continuous 2D **Digital Elevation Model (DEM)** raster.
