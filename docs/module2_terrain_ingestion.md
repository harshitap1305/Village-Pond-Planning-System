# Module 2 — Terrain Source Interface & KML/KMZ Ingestion

> **Status:** Complete ✅ | **Tests:** 35/35 passing | **Commit range:** `a4890af → ccefa5a`

---

## Overview

Module 2 establishes the **data ingestion layer** — the boundary between raw file bytes
and typed Python objects that every downstream module can work with.

It delivers three things:

| Thing | What it is |
|-------|-----------|
| `ContourLine` | The core data model passed between ALL modules |
| `TerrainSource` | An abstract interface making the system format-agnostic |
| `KMLTerrainSource` | Concrete parser for `.kml` / `.kmz` contour files |

No API wiring, no terrain analysis — purely: **bytes in → `List[ContourLine]` out**.

---

## Files Created

```
src/
├── schemas/
│   └── terrain.py          ← ContourLine Pydantic model
└── terrain/
    ├── base.py             ← TerrainSource ABC
    └── kml_source.py       ← KMLTerrainSource implementation

scripts/
└── try_kml_parse.py        ← manual QA script (not part of test suite)

tests/unit/
└── test_kml_source.py      ← 35 unit + integration tests
```

---

## 1. `ContourLine` — The Core Data Model

**File:** [`src/schemas/terrain.py`](../src/schemas/terrain.py)

```python
class ContourLine(BaseModel):
    elevation: float              # metres above sea level
    points: List[Tuple[float, float]]  # [(lon, lat), ...] — WGS84 / EPSG:4326
```

### Design choices

- **WGS84 coordinates only** — reprojection to a metric CRS (UTM) is deliberately
  deferred to Module 4. The parser's job is faithful reading, not transformation.
- **Pydantic validators baked in** — two field-level checks run at construction time:
  - `elevation` must be a finite float (rejects `inf`, `nan`)
  - `points` must contain at least 2 elements (a single point is not a line)
- **Immutable by default** — Pydantic v2 models are frozen-like; downstream code
  should never mutate a `ContourLine` in place.

### What it is NOT responsible for

- Filtering out elevation outliers (e.g. label Placemarks) — that's Module 3
- Reprojecting coordinates — that's Module 4
- Any geospatial computation — that's Modules 5–11

---

## 2. `TerrainSource` — The Abstract Interface

**File:** [`src/terrain/base.py`](../src/terrain/base.py)

```python
class TerrainSource(ABC):
    @abstractmethod
    def extract_contours(self) -> List[ContourLine]: ...
```

### Why this exists (Strategy Pattern)

The system is designed to support multiple input formats without changing any
downstream code. The `TerrainSource` interface is the contract that makes this possible:

```
Today:   KMLTerrainSource      (Module 2)
Future:  GeoTIFFTerrainSource  (load from satellite/DEM GeoTIFF)
         SHPTerrainSource      (Shapefile contour lines)
```

Because every downstream module (`DEMBuilder`, `FlowEngine`, etc.) depends only on
`TerrainSource.extract_contours()`, swapping the input format requires **zero changes**
outside the `src/terrain/` package.

### Single-method interface = trivially mockable

A one-method ABC is easy to fake in tests without needing real files:

```python
class FakeTerrainSource(TerrainSource):
    def extract_contours(self):
        return [ContourLine(elevation=280.0, points=[(81.0, 21.0), (81.1, 21.1)])]
```

This pattern will be used extensively in Modules 5–11 for unit testing the
geospatial algorithms without needing to load a 6.5 MB KML file every time.

---

## 3. `KMLTerrainSource` — The KML/KMZ Parser

**File:** [`src/terrain/kml_source.py`](../src/terrain/kml_source.py)

### Anatomy of the real KML file

Before writing the parser, the fixture was inspected to determine the exact structure:

```xml
<Folder xmlns="http://www.opengis.net/kml/2.2"
        xmlns:gx="http://www.google.com/kml/ext/2.2">
  <name>ContourMapGenerator</name>
  <Folder>
    <name>contours_1.0m</name>
    <Folder>
      <name py:pytype="str">lines</name>   ← lxml objectify namespace quirk
      <Placemark>                           ← one per contour (×1355)
        <name py:pytype="str">277.0</name>  ← ELEVATION IS HERE
        <LineString>
          <coordinates>                     ← 2D: lon,lat lon,lat ...
            81.2863,21.2635 81.2862,21.2634 ...
          </coordinates>
        </LineString>
      </Placemark>
      <Placemark>                           ← point label marker (×1355)
        <name>277</name>                    ← integer, no decimal
        <Point>
          <coordinates>81.2860,21.2634</coordinates>
        </Point>
      </Placemark>
    </Folder>
  </Folder>
</Folder>
```

### Real file statistics (verified by parser)

| Property | Value |
|----------|-------|
| Total `<Placemark>` elements | 2712 |
| `LineString` Placemarks (contour lines) | **1355** — we parse these |
| `Point` Placemarks (label markers) | 1355 — correctly skipped |
| Other Placemarks (folder labels) | 2 — correctly skipped |
| Elevation range | **267.0 – 298.0 m** |
| Unique elevation levels | **32** |
| Coordinate format | **2D only** (`lon,lat` — no Z component) |
| Elevation source | `<name>` tag (e.g. `"277.0"`) |
| Total coordinate points | 159,113 |
| Average points per contour | 117.4 |

> [!IMPORTANT]
> The elevation is in the `<name>` tag, **not** in the coordinate Z value.
> The coordinate string is 2D only (`lon,lat`). Any parser that reads Z from
> coordinates will get `0.0` for every elevation — a silent, hard-to-debug failure.

### Class structure

```
KMLTerrainSource
├── __init__(data: bytes, filename: str)
│     └── _resolve_kml_bytes()      ← transparently handles .kmz vs .kml
│           └── _extract_kml_from_kmz()
│
├── from_file(path) → classmethod   ← convenience for scripts/tests
│
└── extract_contours() → List[ContourLine]
      └── for each <Placemark>:
            └── _parse_placemark()
                  ├── _read_elevation()     ← reads from <name> tag
                  └── _parse_coordinates()  ← parses "lon,lat lon,lat ..."
```

### Namespace handling

The KML namespace (`http://www.opengis.net/kml/2.2`) must be included in every
element lookup. We use **Clark notation** throughout:

```python
KML_NS = "http://www.opengis.net/kml/2.2"
_PLACEMARK   = f"{{{KML_NS}}}Placemark"
_NAME        = f"{{{KML_NS}}}name"
_COORDINATES = f"{{{KML_NS}}}coordinates"

# lxml iter() with Clark notation finds elements at any nesting depth:
for placemark in root.iter(_PLACEMARK):
    ...
```

This is more robust than string `.find("<Placemark>")` which breaks on namespace
prefixes, attribute order, and whitespace variation.

### KMZ support

KMZ files are ZIP archives containing one or more `.kml` files.
The standard convention is that the main document is named `doc.kml`.

```python
with zipfile.ZipFile(BytesIO(data)) as zf:
    kml_names = [n for n in zf.namelist() if n.lower().endswith(".kml")]
    target = "doc.kml" if "doc.kml" in kml_names else kml_names[0]
    return zf.read(target)
```

The unzipping happens **in memory** (using `BytesIO`) — no temporary files on disk,
which matters for the async API layer in Module 12.

### Coordinate parsing

```python
# Input:  "81.2863,21.2635 81.2862,21.2634 81.2862,21.2634"
# Output: [(81.2863, 21.2635), (81.2862, 21.2634), (81.2862, 21.2634)]
```

The parser handles both 2D (`lon,lat`) and 3D (`lon,lat,alt`) formats.
When Z is present it is **silently ignored** — elevation always comes from `<name>`.
Malformed tokens are skipped individually without crashing the whole parse.

---

## 4. Test Coverage

**File:** [`tests/unit/test_kml_source.py`](../tests/unit/test_kml_source.py)

**35 tests across 5 test classes:**

### `TestContourLineSchema` (5 tests)
Tests that the Pydantic validators catch bad inputs at schema level.

| Test | Verifies |
|------|---------|
| `test_valid_contour_line_created` | Happy path — model constructs correctly |
| `test_rejects_single_point` | `points` validator: < 2 points raises |
| `test_rejects_empty_points` | `points` validator: empty list raises |
| `test_rejects_infinite_elevation` | `elevation` validator: `inf` raises |
| `test_rejects_nan_elevation` | `elevation` validator: `nan` raises |

### `TestTerrainSourceInterface` (2 tests)
| Test | Verifies |
|------|---------|
| `test_kml_source_is_terrain_source` | `isinstance(source, TerrainSource)` |
| `test_cannot_instantiate_abstract_base` | `TerrainSource()` raises `TypeError` |

### `TestKMLParsing` (11 tests)
Tests using **inline KML strings** (fast, no file I/O) covering the key parsing paths.

| Test | Verifies |
|------|---------|
| `test_parses_two_contours_from_minimal_kml` | Basic count |
| `test_returns_contour_line_instances` | Return type |
| `test_elevation_values_are_correct` | Elevation reading from `<name>` |
| `test_coordinate_order_is_lon_lat` | Lon/lat order and geographic sanity |
| `test_point_count_is_correct` | Points-per-contour count |
| `test_handles_pytype_namespace_on_name_tag` | lxml objectify namespace |
| `test_non_numeric_name_placemark_skipped` | Label Placemarks filtered |
| `test_3d_coordinates_z_value_ignored` | 3D coords handled gracefully |
| `test_parses_deeply_nested_placemarks` | Deep `Folder > Folder > Placemark` |
| `test_from_file_classmethod` | `from_file(Path)` constructor |
| `test_from_file_accepts_string_path` | `from_file(str)` constructor |

### `TestKMZSupport` (4 tests)
| Test | Verifies |
|------|---------|
| `test_parses_kmz_with_doc_kml` | Standard KMZ extraction |
| `test_parses_kmz_with_non_standard_kml_name` | Fallback to first `.kml` |
| `test_kmz_prefers_doc_kml_over_other_kml` | `doc.kml` priority |
| `test_kmz_elevation_values_preserved` | Values intact after unzip |

### `TestKMLErrors` (5 tests)
| Test | Verifies |
|------|---------|
| `test_raises_on_invalid_xml` | Non-XML bytes → `ValueError` |
| `test_raises_on_truncated_xml` | Truncated XML → `ValueError` |
| `test_raises_on_kmz_with_no_kml` | KMZ without `.kml` → `ValueError` |
| `test_raises_on_bad_zip_as_kmz` | Non-ZIP `.kmz` → `ValueError` |
| `test_empty_kml_returns_empty_list` | Valid XML, no Placemarks → `[]` |

### `TestRealFixture` (8 tests)
Integration tests against the actual `tests/fixtures/contours_1m.kml`.
Skipped automatically if the fixture is absent (so CI is never blocked).

| Test | Verifies |
|------|---------|
| `test_correct_total_count` | 1355 LineString contours |
| `test_elevation_full_range` | min=267.0, max=298.0 |
| `test_all_terrain_elevations_present` | Every integer 267–298 present |
| `test_unique_elevation_count` | Exactly 32 unique levels |
| `test_all_contours_have_minimum_two_points` | No degenerate contours |
| `test_all_coordinates_within_india_bounds` | lon 68–97°, lat 8–37° |
| `test_all_coordinates_are_two_element_tuples` | `(float, float)` pairs |
| `test_no_nan_coordinates` | No `NaN` or `inf` in coordinates |

---

## 5. Manual QA Script

**File:** [`scripts/try_kml_parse.py`](../scripts/try_kml_parse.py)

```bash
# Run from project root with venv activated:
python scripts/try_kml_parse.py
```

Expected output:
```
Parsing tests/fixtures/contours_1m.kml  (6553.2 KB)...
=======================================================
  Total contour lines parsed  : 1355
  Unique elevation levels     : 32
  Full elevation range        : 267.0 -- 298.0 m
  Core terrain range          : 267.0 -- 298.0 m
  Total coordinate points     : 159,113
  Avg points per contour      : 117.4
  ...
=======================================================
All assertions passed
```

---

## 6. Commit History

| Hash | Message |
|------|---------|
| `a4890af` | `feat: define TerrainSource interface and ContourLine schema` |
| `6024078` | `feat: implement KMLTerrainSource parser` |
| `ccefa5a` | `test: add KML parser sanity script and 35-test suite` |

---

## 7. What Comes Next

Module 2 deliberately **defers** these concerns to later modules:

| Concern | Handled in |
|---------|-----------|
| Reject files with < 2 contours | Module 3 — Input Validation |
| Reject the `277` integer Point labels more explicitly | Module 3 |
| File size / MIME type guards | Module 3 |
| Reproject `(lon, lat)` → `(x, y)` in metres | Module 4 |
| Build the elevation grid (DEM) | Module 5 |
| FastAPI file upload endpoint | Module 12 |

---

## 8. Known Quirks & Decisions Log

| Quirk | Decision |
|-------|---------|
| `<name>` tag has `py:pytype="str"` attribute from lxml objectify | lxml `.text` returns the content string regardless — no special handling needed |
| File has 1355 `Point` Placemarks alongside 1355 `LineString` ones | Point Placemarks have no `<LineString>` child → naturally filtered by the `find(f".//{_COORDINATES}")` check |
| Coordinates are 2D (`lon,lat` only) but KML spec allows 3D | Parser always takes `parts[0]` (lon) and `parts[1]` (lat), ignoring `parts[2]` (Z) if present |
| `lxml.etree` used instead of `fastkml` library | More control over namespace handling; easier to reason about in a demo explanation |
| `from_file()` classmethod separate from `__init__` | `__init__` takes `bytes` (for the API layer in Module 12); `from_file()` is a convenience wrapper for tests and scripts |
