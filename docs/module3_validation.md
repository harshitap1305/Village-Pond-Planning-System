# Module 3 — Input Validation & File Upload Handling

> **Status:** Complete ✅ | **Tests:** 85/85 passing (cumulative) | **Commit range:** `6ad7d40 → 3e5cd9c`

---

## Overview

Module 3 wraps the ingestion pipeline in a **two-layer validation shield** so that
bad input produces clean, typed errors rather than cryptic stack traces.

```
Raw bytes
    │
    ▼  validate_file(filename, size_bytes)      ← Layer 1 — BEFORE parsing
    │  Wrong extension  →  UnsupportedFormatError  (HTTP 415)
    │  Too large        →  FileTooLargeError        (HTTP 413)
    │
    ▼  KMLTerrainSource.extract_contours()      ← Module 2 — parsing
    │  Bad XML / zip   →  TerrainParseError        (HTTP 400)
    │
    ▼  validate_contours(contours)              ← Layer 2 — AFTER parsing
    │  < 2 lines        →  InvalidGeometryError    (HTTP 422)
    │  All same elev    →  InvalidGeometryError    (HTTP 422)
    │  Zero-size bbox   →  InvalidGeometryError    (HTTP 422)
    │
    ▼  List[ContourLine]  ✓
```

**What this module does NOT do** (deferred on purpose):

| Concern | Handled in |
|---------|-----------|
| Registering FastAPI error handlers | Module 13 |
| Filtering elevation outliers | Module 4+ |
| Geographic bounds checking | Not required |
| MIME-type sniffing (magic bytes) | Future enhancement |

---

## Files Created / Modified

```
src/terrain/
├── exceptions.py    ← [NEW] custom exception hierarchy
├── validators.py    ← [NEW] validate_file() + validate_contours()
└── kml_source.py   ← [MODIFIED] 3 ValueError → TerrainParseError

tests/
├── fixtures/
│   ├── empty.kml         ← [NEW] broken fixture: 0 Placemarks
│   ├── single_contour.kml← [NEW] broken fixture: only 1 contour
│   ├── flat_terrain.kml  ← [NEW] broken fixture: all same elevation
│   └── not_xml.kml       ← [NEW] broken fixture: garbage bytes
└── unit/
    └── test_validation.py← [NEW] 50 tests for Module 3
```

---

## 1. Exception Hierarchy

**File:** [`src/terrain/exceptions.py`](../src/terrain/exceptions.py)

### Class tree

```
Exception
└── TerrainError                   ← catch-all for all ingestion errors
    ├── UnsupportedFormatError     ← wrong file extension
    ├── FileTooLargeError          ← file exceeds size limit
    ├── TerrainParseError          ← file unreadable (bad XML / bad ZIP)
    └── InvalidGeometryError       ← parsed but geometrically unusable
```

### HTTP status code mapping

These mappings are recorded in the module docstring and will be wired to
FastAPI exception handlers in Module 13. They are NOT implemented here.

| Exception | HTTP code | Semantics |
|-----------|-----------|-----------|
| `UnsupportedFormatError` | **415** Unsupported Media Type | Extension not `.kml`/`.kmz` |
| `FileTooLargeError` | **413** Request Entity Too Large | Exceeds `max_upload_mb` |
| `TerrainParseError` | **400** Bad Request | Corrupt XML or invalid ZIP |
| `InvalidGeometryError` | **422** Unprocessable Entity | Parsed but DEM-unusable |

### Design decisions

**Single inheritance root (`TerrainError`):**
The API layer can catch the entire family with one `except TerrainError` when it only
needs to return a generic 4xx, or discriminate between subtypes for precise status codes:

```python
try:
    validate_file(filename, size)
    contours = KMLTerrainSource(data).extract_contours()
    validate_contours(contours)
except UnsupportedFormatError:
    raise HTTPException(415, ...)
except FileTooLargeError:
    raise HTTPException(413, ...)
except TerrainParseError:
    raise HTTPException(400, ...)
except InvalidGeometryError:
    raise HTTPException(422, ...)
```

**`TerrainParseError` is NOT a subclass of `ValueError`:**
This is intentional. A bare `ValueError` would be caught by all Python code that
does `except ValueError` — way too broad. A typed exception forces explicit handling.
The test suite verifies this explicitly:
```python
assert not issubclass(TerrainParseError, ValueError)  # test passes ✓
```

---

## 2. `validate_file()` — File-Level Guard

**File:** [`src/terrain/validators.py`](../src/terrain/validators.py)

```python
def validate_file(filename: str, size_bytes: int) -> None
```

### What it checks

| Check | Failure condition | Exception raised |
|-------|-------------------|-----------------|
| Extension | `suffix not in settings.allowed_extensions` | `UnsupportedFormatError` |
| Size | `size_bytes > settings.max_upload_mb * 1024 * 1024` | `FileTooLargeError` |

### Key design points

- **Run this BEFORE parsing** — fail fast, don't read 200 MB of garbage into memory
  just to discover it's a `.csv`
- **Extension check is case-insensitive** — `.KML`, `.Kml`, `.kml` all accepted
- **Exact limit boundary is inclusive** — a file of exactly 20 MB is accepted;
  20 MB + 1 byte is rejected. This is intentional (≤ not <)
- **All thresholds from `settings`** — `settings.max_upload_mb` and
  `settings.allowed_extensions` — zero hard-coded magic numbers

### Error message quality

Both exceptions include human-readable detail in their message strings:

```python
# UnsupportedFormatError
"Unsupported file type '.csv'. Accepted formats: .kml, .kmz"

# FileTooLargeError
"File is 25.0 MB, which exceeds the 20 MB upload limit."
```

---

## 3. `validate_contours()` — Semantic Validation

**File:** [`src/terrain/validators.py`](../src/terrain/validators.py)

```python
def validate_contours(contours: List[ContourLine]) -> None
```

### Three checks in order

#### Check 1 — Minimum contour count

```python
if len(contours) < 2:
    raise InvalidGeometryError("At least 2 contour lines required ...")
```

**Why:** A DEM interpolator needs elevation at multiple levels to build a surface.
A single contour defines only one elevation — that's a cliff edge, not a terrain.

#### Check 2 — Elevation variety

```python
unique_elevations = {c.elevation for c in contours}
if len(unique_elevations) < 2:
    raise InvalidGeometryError("... cannot compute slope from a flat surface.")
```

**Why:** If all contours share the same elevation, the terrain is a flat plane.
Flow direction is undefined on a flat plane — the hydrological analysis produces
no meaningful output. Note: *two contours at the same elevation are fine as long
as a third differs* (i.e. the check is on unique elevation count, not contour count).

#### Check 3 — Non-zero spatial extent

```python
lon_range = max(all_lons) - min(all_lons)
lat_range = max(all_lats) - min(all_lats)
if lon_range < 0.0001 or lat_range < 0.0001:
    raise InvalidGeometryError("Near-zero spatial extent ...")
```

**Why:** `0.0001°` ≈ 11 metres at the equator. Anything smaller means all contours
are clustered at essentially one point — either a single-point marker file or a
data export error. A terrain model of 11×11 m can't meaningfully locate a pond site.

### What `validate_contours()` does NOT check

- Whether elevations are monotonically ordered (not required by the interpolator)
- Whether elevation values are in a "reasonable" range for India (not the validator's job)
- Whether contours are geographically inside India (too brittle, not specified)
- Individual point validity (that's `ContourLine`'s Pydantic validator in Module 2)

---

## 4. Changes to `KMLTerrainSource`

**File:** [`src/terrain/kml_source.py`](../src/terrain/kml_source.py)

Three `ValueError` raises replaced with `TerrainParseError`:

| Location | Old | New |
|----------|-----|-----|
| `extract_contours()` — bad XML | `raise ValueError("Invalid XML...")` | `raise TerrainParseError("KML file could not be parsed as XML...")` |
| `_extract_kml_from_kmz()` — bad ZIP | `raise ValueError("not a valid ZIP...")` | `raise TerrainParseError("KMZ file is not a valid ZIP archive...")` |
| `_extract_kml_from_kmz()` — no KML in ZIP | `raise ValueError("no .kml files")` | `raise TerrainParseError("KMZ archive contains no .kml files")` |

The import was also added:
```python
from src.terrain.exceptions import TerrainParseError
```

**Why only these three lines?** The parser's other `None` returns (skipping bad
Placemarks, skipping non-numeric names) are not errors — they are expected parser
behaviour. Only truly unrecoverable situations (`XMLSyntaxError`, `BadZipFile`) warrant
an exception.

---

## 5. Broken Fixture Files

Four fixture files in `tests/fixtures/` that serve as regression anchors.
Each tests a specific failure mode:

| File | Size | What goes wrong |
|------|------|----------------|
| `empty.kml` | 62 B | Valid XML, zero `<Placemark>` → parser returns `[]` → count check fails |
| `single_contour.kml` | 218 B | 1 `LineString` → count check: "got 1" |
| `flat_terrain.kml` | 533 B | 3 contours all at `280.0 m` → elevation variety check fails |
| `not_xml.kml` | 83 B | Garbage bytes with `.kml` extension → `TerrainParseError` at parse time |

These files intentionally do NOT test the file-level guard (`validate_file`) —
they all have valid extensions and are small enough to pass. They are designed to
test what happens after the file passes the file guard but fails either at parse
time or at semantic validation time.

---

## 6. Test Coverage

**File:** [`tests/unit/test_validation.py`](../tests/unit/test_validation.py)

**50 tests across 5 classes** (combined with Module 2: 85 total passing):

### `TestExceptionHierarchy` (6 tests)

| Test | Verifies |
|------|---------|
| `test_terrain_error_is_exception` | `issubclass(TerrainError, Exception)` |
| `test_all_subclasses_inherit_from_terrain_error` | All 4 subtypes inherit root |
| `test_catch_all_with_terrain_error` | `except TerrainError` catches any subtype |
| `test_subclasses_are_also_exceptions` | Each is directly raiseable |
| `test_exception_message_preserved` | `.args[0]` contains the message string |
| `test_subclasses_are_distinct` | Types are not the same object |

### `TestValidateFile` (21 tests)

Tests cover: lowercase/uppercase/mixed-case extensions, dotted filenames, zero-byte
files, five rejected extensions (.txt, .csv, .tif, .shp, no extension), exact
boundary condition (20 MB accepted, 20 MB + 1 byte rejected), large file rejection,
error message quality (size and limit mentioned), and catch-all behaviour.

### `TestValidateContours` (13 tests)

Tests cover: minimal valid pair, many contours, non-integer elevations, the
"duplicate elevation OK if third differs" edge case, empty list, single contour,
all-same elevation (two contours, ten contours), elevation value in error message,
single-point contours (zero bbox), tiny bbox (0.00001° spread).

### `TestKMLSourceExceptions` (6 tests)

| Test | Key assertion |
|------|--------------|
| `test_invalid_xml_raises_terrain_parse_error` | Type is `TerrainParseError` |
| `test_parse_error_catchable_as_terrain_error` | Caught by `except TerrainError` |
| `test_bad_zip_kmz_raises_terrain_parse_error` | `.kmz` bad zip → typed error |
| `test_empty_kmz_raises_terrain_parse_error` | ZIP with no .kml → typed error |
| `test_parse_error_is_not_value_error` | `not issubclass(TerrainParseError, ValueError)` |
| `test_truncated_xml_raises_terrain_parse_error` | Partial XML → typed error |

### `TestFixtureFiles` (4 tests)

End-to-end integration tests — file bytes → `validate_file()` → parse → `validate_contours()`:

| Test | Flow | Exception expected |
|------|------|--------------------|
| `test_empty_kml_passes_file_check_but_fails_semantic` | File guard ✓ → parse ✓ → `[]` → validate ✗ | `InvalidGeometryError("At least 2")` |
| `test_single_contour_fails_semantic_validation` | Parse → 1 contour → validate ✗ | `InvalidGeometryError("got 1")` |
| `test_flat_terrain_fails_elevation_variety_check` | Parse → 3 contours same elev → validate ✗ | `InvalidGeometryError("flat surface")` |
| `test_not_xml_raises_terrain_parse_error` | File guard ✓ → parse ✗ | `TerrainParseError` |

---

## 7. Cumulative Test Count

| Module | Tests added | Running total |
|--------|-------------|---------------|
| Module 2 | 35 | 35 |
| Module 3 | 50 | **85** |

---

## 8. Commit History

| Hash | Message |
|------|---------|
| `6ad7d40` | `feat: add custom exception hierarchy for terrain errors` |
| `77b6669` | `refactor: raise TerrainParseError instead of ValueError in KMLTerrainSource` |
| `ff06363` | `feat: add validate_file and validate_contours functions` |
| `747b7da` | `test: add broken KML fixture files for validation testing` |
| `3e5cd9c` | `test: add Module 3 validation test suite (85 total tests)` |

---

## 9. What Comes Next

Module 4 will consume the clean `List[ContourLine]` output that Module 3 has
validated and transform the coordinates:

| Concern | Module |
|---------|--------|
| Reproject `(lon, lat)` WGS84 → `(x, y)` UTM using `pyproj` | **Module 4** |
| Build a raster elevation grid (DEM) from reprojected contours | Module 5 |
| Fill sinks and compute D8 flow direction | Module 6 |
| Flow accumulation and drainage network | Module 7 |

---

## 10. Design Decisions Log

| Decision | Rationale |
|----------|-----------|
| `TerrainParseError` is NOT a `ValueError` subclass | Prevents accidental catch by generic `except ValueError` in third-party code |
| `validate_file()` is a free function, not a method | Pure function → testable without instantiating `KMLTerrainSource` |
| `validate_contours()` is a free function, not a method | Same reason; also decoupled from which `TerrainSource` produced the contours |
| All thresholds read from `settings` | 12-factor config principle; no magic numbers; easy to override in tests via env vars |
| `0.0001°` as the spatial-extent threshold | ≈ 11 m at the equator; anything smaller is almost certainly a data error |
| No MIME-type sniffing (magic bytes check) | Extension check is sufficient for this project phase; can be added later |
| Fixture files kept in `tests/fixtures/` | Co-located with the test suite; skipped gracefully if missing on CI |
