# Submission Report — AI-based Village Pond Planning System

**Course:** CSD
**Submission Phase:** Phase 3
**GitHub:** https://github.com/harshitap1305/Village-Pond-Planning-System

---

## 1. System Overview

This system automates the civil-engineering task of identifying optimal rainwater harvesting pond sites in rural villages. Given a KML/KMZ contour map of any village, the system:

1. Builds a Digital Elevation Model (DEM) from contour lines
2. Runs hydrological routing to identify natural depressions
3. Cross-references OpenStreetMap to exclude existing water bodies and built-up land
4. Fetches 10-year historical rainfall and computes SCS-CN runoff
5. Recommends pond dimensions per IS 5477
6. Returns everything as structured JSON with a GeoJSON catchment polygon, rendered on an interactive Leaflet map

**Typical pipeline latency:** 60–90 seconds (dominated by OSM + rainfall API round-trips)

---

## 2. API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/analyzeContour` | Upload KML/KMZ → full analysis result |
| `GET`  | `/health` | Service liveness check |
| `GET`  | `/docs`   | Interactive Swagger UI |
| `GET`  | `/api/imagery` | Basemap tile metadata (satellite/street) |
| `GET`  | `/api/village/search?q=` | Village registry search |
| `GET`  | `/api/village/{id}/kml` | Download KML for a registered village |
| `GET`  | `/api/results/{id}` | Retrieve saved analysis by UUID |

### Key API Features
- **`pour_lat` / `pour_lon` query params** on `/analyzeContour`: manual pour-point override — the system snaps to the nearest auto-detected candidate bowl and re-runs the full downstream analysis
- **Graceful degradation**: if any external API (OSM, Open-Meteo, NASA POWER, DB) fails, the system returns a valid partial result with `warnings[]` codes rather than an HTTP 500

---

## 3. Methodology

### 3.1 DEM Construction
Contour elevation rings from KML are reprojected to the local UTM zone (auto-detected from centroid), densified at 1-metre vertex spacing, then interpolated into a 2-metre raster grid using **Inverse Distance Weighting** with a SciPy KD-Tree index.

### 3.2 Hydrological Conditioning
The **Planchon–Darboux Priority-Flood algorithm** (via `pysheds`) fills artificial DEM pits. The filled DEM drives D8 flow routing; the raw DEM is retained for depression-depth computation.

### 3.3 Candidate Selection & Scoring
Natural depressions are identified as cells where `filled_dem - raw_dem > 0`. Contiguous depression groups are scored:

```
Score = catchment_cells / total_DEM_cells
```

where `catchment_cells` = sum of flow-accumulation values at the bowl's sink cells. This is a size-independent metric that ranks by drainage efficiency. Candidates whose bowl footprint overlaps OSM water or built-up land are discarded.

### 3.4 Rainfall & Runoff (SCS-CN)
- **Primary source:** Open-Meteo ERA5-Land reanalysis (10-year monthly mean, ~9 km)
- **Fallback:** NASA POWER MERRA-2 (10-year monthly mean, ~50 km)
- **Method:** SCS Curve Number using HSG-B soil (configurable) and built-up fraction from the OSM land mask

```
S = 1000/CN - 10
Q = (P - 0.2S)² / (P + 0.8S)
Annual_volume = Q × catchment_area_m²
```

### 3.5 Pond Design (IS 5477)
Storage required = annual runoff × design life (1 year default). Pond depth is constrained to [2 m, 4 m] (IS 5477 guidance). Surface area = storage / depth, validated against the topographic bowl area.

### 3.6 Watershed Delineation
BFS upstream on the reversed D8 flow-direction grid from the selected pour point. The resulting boolean raster is polygonised and Douglas-Peucker simplified to a GeoJSON polygon.

---

## 4. Architecture Summary

**Key design principles:**
- **Fail-open**: every external call (OSM, rainfall APIs, DB) degrades gracefully — analysis never crashes on API outage
- **Single routing pass**: flow direction/accumulation computed once, reused for all candidates and watershed delineation
- **Stateless services**: all geospatial functions are pure functions — no shared mutable state, safe for concurrent requests
- **Pydantic at every boundary**: each pipeline transformation is type-checked; data errors are caught at the boundary

See [docs/architecture.md](docs/architecture.md) for the full data-flow diagram and module map.

---

## 5. What Was Built

All items below are implemented, tested, and committed:

| Module | Description | Test coverage |
|--------|-------------|---------------|
| KML/KMZ parsing | Terrain extraction, UTM reprojection | Unit tests |
| DEM interpolation | IDW + KD-Tree | Unit tests |
| Hydrological conditioning | Priority-Flood | Unit tests |
| D8 flow routing | Via pysheds | Unit + integration |
| OSM water exclusion | Overpass API, fail-open | Unit + integration |
| OSM land exclusion | Reuses cached XML | Unit + integration |
| Candidate selection | Depression analysis, veto, scoring | Unit tests |
| Rainfall (Open-Meteo) | 10-year ERA5, retry, failover | Unit tests (mocked) |
| Rainfall (NASA POWER) | Fallback, retry, timeout | Unit tests (mocked) |
| SCS-CN runoff | With built-up fraction from OSM | Unit tests |
| IS 5477 pond design | Topography-constrained | Unit tests |
| Watershed delineation | BFS upstream | Unit tests |
| Polygonization | Raster → GeoJSON | Unit + integration |
| Unified response assembly | Graceful degradation chain | Integration tests |
| Reliability hardening | 3× retry + timeout on all external calls | Unit tests |
| Persistence (PostgreSQL JSONB) | SQLModel, fail-open, result_id | Unit + integration |
| Village registry | Search + KML download | Integration tests |
| Imagery endpoint | 3 tile providers, no API key | Unit tests |
| Pour-point override UI | Snap to nearest candidate | Unit + integration |
| Frontend | Leaflet SPA, Chart.js, layer switcher | — |
| Docker deployment | `docker compose up --build` | — |
| CI (GitHub Actions) | black + ruff + pytest on every push | — |

**Total test count: 349 (336 from Modules 1–9 + 13 new from Modules 10–11), all passing.**

---

## 6. Known Limitations & Future Work

- **No real-time satellite imagery**: the imagery endpoint serves free tile providers; high-resolution Planet/Sentinel imagery would require a paid API key
- **Soil type is fixed per deployment**: HSG is set globally in config, not derived per-cell from a soil database
- **No user accounts**: analysis results are identified by UUID but not associated with users
- **Village registry is seeded manually**: `scripts/seed_villages.py` must be run after adding KML files; a bulk-import API endpoint would improve operator UX
- **IDW resolution vs. accuracy**: 2 m DEM cells work well for contour spacing ≥ 5 m; very dense contour maps may benefit from a larger cell size

---

## 7. LLM Usage Statement

LLM tools (Google Gemini, Claude Sonnet) were used throughout this project in the following ways:

**Architecture review (Phase 2→3 transition):** The LLM reviewed the Phase 2 HLD document and flagged inconsistencies between the scoring formula in the README and the implementation (storage volume was being blended into the score against spec). This bug was verified against the actual code, confirmed as real, and fixed with a regression test.

**Code generation:** New module boilerplate (rainfall HTTP clients, SCS-CN runoff, SQLModel persistence, pond design, imagery endpoint, pour-point override) was AI-generated. All generated code was manually reviewed against:
- SCS-CN curve number tables (USDA TR-55)
- IS 5477 Part 1 pond design guidance
- OSM tagging conventions (wiki.openstreetmap.org)
- Open-Meteo and NASA POWER API documentation

**Test generation:** Unit test skeletons were AI-generated; all expected values (e.g., CN lookups, annual volume formulas) were hand-computed and cross-checked before acceptance.

**Debugging:** LLM helped diagnose a flow-routing consistency bug (two separate `pysheds` routing passes produced inconsistent catchment areas at candidacy vs. watershed delineation). The fix was to compute routing once and reuse it — this was verified with the existing integration tests and a new `test_idempotency` test.

In every case, AI output was read, understood, and independently verified before being committed. No AI output was accepted on trust alone.
