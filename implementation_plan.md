# Implementation Plan — Contour-to-Catchment Backend API
### AI-based Village Pond Planning System — Phase: `/analyzeContour` (KML/KMZ ingestion)

---

## 0. Guiding Architecture

```
                        ┌────────────────────────┐
                        │   FastAPI Layer         │  (Module 12)
                        │  POST /analyzeContour   │
                        └───────────┬─────────────┘
                                    │  orchestrates
                        ┌───────────▼─────────────┐
                        │  AnalysisService         │  (Module 12)
                        │  (use-case orchestrator) │
                        └───────────┬─────────────┘
           ┌────────────┬──────────┼───────────┬──────────────┐
           ▼            ▼          ▼           ▼              ▼
   TerrainSource   DEMBuilder  FlowEngine  CatchmentDelineator  Ranker
   (interface)      (M4-M5)     (M7-M8)         (M9-M10)       (M9)
       ▲
       │ implements
  KMLTerrainSource (M2-M3)   ← next phase: GeoTIFFTerrainSource, SHPTerrainSource
```

**Key design decisions locked in from Day 1:**
- **Strategy pattern** for `TerrainSource` — decouples format (KML today) from algorithm (DEM/hydrology). Satisfies "no hard-coding, generalizable."
- **Pure functions / stateless services** for all geospatial algorithms — enables unit testing without spinning up the API, and horizontal scaling later (no shared state).
- **Pydantic models** at every boundary (input, DEM, catchment result) — correctness + self-documenting API.
- **Dependency injection** of `TerrainSource` into `AnalysisService` — swap implementations without touching orchestration or API code.

---

## Module Breakdown (15 modules, ~2 days each ≈ 1 month)

Each module below lists: **Goal · Deliverables · Design principle(s) addressed · Suggested commits** (2-3 commits per module keeps history granular and honest).

---

### Module 1 — Repo Scaffolding & Project Skeleton
**Goal:** Set up a clean, extensible project skeleton before writing any logic.
**Deliverables:**
- Folder structure (below), `pyproject.toml`/`requirements.txt`, `.gitignore`, `README.md` stub, `LICENSE`
- `src/terrain/`, `src/hydrology/`, `src/catchment/`, `src/api/`, `src/schemas/`, `tests/`, `docs/`
- Config module (`src/config.py`) using `pydantic-settings` (12-factor style — env-based config)
- Pre-commit hooks: `black`, `ruff`/`flake8`, `mypy` (optional)
- GitHub Actions CI stub (lint + test on push)
**Principles:** Maintainability, Reliability (CI from day 1)
**Commits:** `chore: init repo structure` → `chore: add config + env handling` → `ci: add lint/test workflow`

---

### Module 2 — Terrain Source Interface & KML/KMZ Ingestion
**Goal:** Define the abstraction that makes the system format-agnostic, and build the concrete KML reader.
**Deliverables:**
- Abstract base `TerrainSource` (ABC) with method `extract_contours() -> List[ContourLine]`
- `KMLTerrainSource` implementation using `fastkml` or `lxml` (handles both `.kml` and `.kmz` — unzip KMZ transparently)
- Robust parsing: namespaces, `ExtendedData/SchemaData` elevation extraction (as seen in your sample: elevation is in `<name>`, not Z-coordinate — handle both cases defensively since other tools embed elevation in Z)
- `ContourLine` Pydantic model: `elevation: float`, `points: List[Tuple[lon, lat]]`
**Principles:** Modularity, Reusability (interface first), Correctness (defensive parsing)
**Commits:** `feat: define TerrainSource interface` → `feat: implement KML contour parser` → `feat: add KMZ zip-extraction support`

---

### Module 3 — Input Validation & File Upload Handling
**Goal:** Make ingestion robust against malformed/adversarial input before it reaches the algorithm.
**Deliverables:**
- File type/size validation (extension + MIME sniff, not trust filename)
- Schema validation: reject files with <2 contour lines, non-monotonic/duplicate elevations, degenerate geometries
- Custom exception hierarchy (`TerrainParseError`, `InvalidGeometryError`) mapped to HTTP error codes later
- Unit tests with a deliberately corrupted KML fixture
**Principles:** Reliability, Correctness, Security-mindedness
**Commits:** `feat: add file validation layer` → `test: add malformed-KML fixtures`

---

### Module 4 — Point Cloud Extraction & Coordinate Normalization
**Goal:** Convert contour lines into a clean elevation point cloud ready for interpolation.
**Deliverables:**
- Flatten all `(lon, lat, elevation)` triples from contour vertices
- CRS handling: reproject WGS84 (EPSG:4326) → a local metric CRS (UTM zone auto-detected from centroid) using `pyproj`, since distance/area math needs meters, not degrees
- De-duplication of coincident points
- `PointCloud` schema: `x, y (meters), z (elevation)`
**Principles:** Correctness (CRS mismatch is a classic silent-bug source — you even flagged this in your HLD risk table)
**Commits:** `feat: extract point cloud from contours` → `feat: auto-detect UTM zone + reproject`

---

### Module 5 — DEM Construction via Interpolation
**Goal:** Build a regular-grid raster (DEM) from scattered contour points — the core terrain model everything else depends on.
**Deliverables:**
- Grid rasterization using `scipy.interpolate` (`griddata` with `linear`/`cubic`) or `RichDEM`'s `TIN`→raster path
- Configurable cell size (default ~1–2 m given your 1 m contour interval), bounded by contour extent
- `DEM` model wrapping a numpy array + geotransform (origin, cell size, CRS)
- Sanity checks: interpolated elevation range should roughly match input contour range (catch interpolation blow-ups at edges)
**Principles:** Correctness, Reusability (DEM object is the shared currency for all downstream modules — same object could later come from a GeoTIFF loader)
**Commits:** `feat: implement grid interpolation` → `feat: wrap DEM as typed object with geotransform` → `test: validate DEM against known elevation range`

---

### Module 6 — DEM Conditioning (Sink Filling) & Slope
**Goal:** Clean the DEM so flow-routing doesn't get artificially trapped, per your HLD's hydrological methodology section.
**Deliverables:**
- Sink/pit filling (Wang & Liu or Planchon-Darboux algorithm via `richdem.FillDepressions`)
- Slope raster: `slope = arctan(sqrt((∂z/∂x)² + (∂z/∂y)²))` (matches your HLD formula exactly)
- Aspect raster (useful bonus for suitability scoring later)
- Visual debug output (matplotlib PNG saved to `/tmp` for manual QA — not part of API response)
**Principles:** Correctness, Reliability
**Commits:** `feat: add sink-filling via RichDEM` → `feat: compute slope/aspect rasters` → `chore: add debug raster plotting utility`

---

### Module 7 — Flow Direction (D8 Algorithm)
**Goal:** Assign each cell a downslope flow direction — first hydrological algorithm from your HLD.
**Deliverables:**
- D8 implementation (steepest of 8 neighbors) — use `richdem.FlowProportions`/`pysheds` or hand-rolled numpy for pedagogical transparency (you'll be asked to explain it in demo)
- Unit test on a synthetic 5×5 "toy DEM" with a known correct flow-direction answer (critical for demonstrating correctness independent of your real messy data)
**Principles:** Correctness (deterministic, testable in isolation), Modularity
**Commits:** `feat: implement D8 flow direction` → `test: validate D8 against synthetic DEM`

---

### Module 8 — Flow Accumulation
**Goal:** Compute upstream contributing cells per cell — identifies natural drainage paths.
**Deliverables:**
- Flow accumulation via topological traversal or `pysheds`/`richdem` built-in
- Output as raster; highlight top-percentile "drainage channel" cells for sanity visualization
- Unit test on the same toy DEM (accumulation should match hand-computed values)
**Principles:** Correctness, Scalability (vectorized numpy ops, not per-cell Python loops, so it scales to bigger DEMs later)
**Commits:** `feat: implement flow accumulation` → `test: validate accumulation on toy DEM`

---

### Module 9 — Pond Candidate Location Identification
**Goal:** Programmatically pick a plausible pond point — **no hard-coded coordinates**, as the assignment explicitly warns.
**Deliverables:**
- Candidate selection heuristic: local elevation minima combined with flow-accumulation threshold (cells where accumulation > Nth percentile AND slope below a max threshold)
- Return **ranked list** of candidates (not just one) — supports the `/api/candidates` endpoint from your own HLD
- Config-driven thresholds (not magic numbers) so it generalizes to other contour maps of different scale
**Principles:** Correctness, Reusability (thresholds are parameters, not constants), directly satisfies "do not hard-code" requirement
**Commits:** `feat: implement candidate point selection` → `feat: make thresholds configurable via settings`

---

### Module 10 — Catchment Delineation (Watershed Extraction)
**Goal:** Given a candidate/selected point, extract the full upstream catchment polygon — the assignment's central deliverable.
**Deliverables:**
- Watershed delineation via upstream traversal from the pour point (`richdem.rdarray.flow_watershed` or manual BFS over flow-direction raster)
- Convert boolean catchment mask → polygon(s) using `rasterio.features.shapes` + `shapely`
- Reproject catchment polygon back to WGS84 (for GeoJSON output / map display)
**Principles:** Correctness, Modularity (single-responsibility: this module *only* delineates, doesn't compute area/stats)
**Commits:** `feat: implement watershed delineation from pour point` → `feat: convert catchment mask to GeoJSON polygon`

---

### Module 11 — Catchment Metrics Computation
**Goal:** Turn the raw catchment geometry into the structured numbers the API needs to return.
**Deliverables:**
- Area (m² / hectares) from polygon geometry (metric CRS — reuse Module 4's projection)
- Mean/min/max elevation and slope within the catchment (raster-masked stats)
- Contributing-cell count cross-check against `Area = cells × cell_area` (matches your HLD's exact formula)
- `CatchmentMetrics` Pydantic schema
**Principles:** Correctness, Maintainability (typed output contract)
**Commits:** `feat: compute catchment area and terrain stats` → `test: validate area formula against toy DEM`

---

### Module 12 — API Layer: `POST /analyzeContour`
**Goal:** Wire everything into the actual HTTP endpoint the assignment requires.
**Deliverables:**
- `AnalysisService` orchestrator: `parse → build DEM → condition → flow-route → find candidates → delineate → compute metrics`
- FastAPI route: accepts `UploadFile`, optional query params (`cell_size`, `pour_point lat/lon` override), returns structured JSON
- Response schema:
  ```json
  {
    "candidate_locations": [{"lat":..., "lon":..., "elevation":..., "score":...}],
    "selected_location": {...},
    "catchment": {
      "area_ha": ...,
      "polygon_geojson": {...},
      "elevation_stats": {...},
      "slope_stats": {...}
    },
    "metadata": {"dem_cell_size_m":..., "contour_count":..., "crs_used":...}
  }
  ```
- Async file handling (don't block event loop on large-file parsing — offload to threadpool)
**Principles:** Modularity (thin controller, fat service), Scalability (async I/O), Correctness (typed response)
**Commits:** `feat: implement AnalysisService orchestrator` → `feat: add POST /analyzeContour route` → `feat: add response schema + GeoJSON serialization`

---

### Module 13 — Error Handling, Logging & Reliability Hardening
**Goal:** Make the API production-grade, not just a happy-path demo.
**Deliverables:**
- Global exception handlers mapping internal errors → clean HTTP 4xx/5xx with useful messages
- Structured logging (`structlog`/stdlib `logging` with request IDs) at each pipeline stage
- Timeouts/size limits on uploaded files (prevent DoS via huge KML)
- Health check endpoint `GET /health` (availability requirement)
- Idempotency: re-running same file always yields same result (no hidden random state)
**Principles:** Reliability, Availability, Maintainability
**Commits:** `feat: add global exception handlers` → `feat: add structured logging` → `feat: add /health endpoint + upload limits`

---

### Module 14 — Testing Suite & CI Integration
**Goal:** Prove correctness quantitatively, not just "it ran without crashing."
**Deliverables:**
- Unit tests per module (D8, accumulation, area formula — using synthetic toy DEMs with known answers, from Modules 7/8/11)
- Integration test: full pipeline run on the provided `contours_1m.kml`, asserting sane bounds (area > 0, elevation within contour range, polygon validity via `shapely.is_valid`)
- API test via `TestClient` (FastAPI) hitting `/analyzeContour` with the sample file
- Coverage report wired into CI (Module 1's GitHub Actions)
**Principles:** Correctness, Reliability, Maintainability
**Commits:** `test: add unit tests for hydrology algorithms` → `test: add end-to-end pipeline integration test` → `ci: wire coverage into GitHub Actions`

---

### Module 15 — Documentation, Dockerization & Demo Prep
**Goal:** Package everything for evaluation — API docs, deployment, and the required report.
**Deliverables:**
- `Dockerfile` + `docker-compose.yml` (reproducible run — Availability/Maintainability)
- Auto-generated API docs via FastAPI's OpenAPI/Swagger UI (`/docs`) — satisfies "API documentation" deliverable almost for free
- `README.md`: installation guide, architecture diagram, how to run, how to test
- Final **report**: GitHub repo link, working API URL, catchment-estimation approach write-up (can lift from your HLD's Section 6, refined with implementation notes), demo screenshots/GeoJSON output on the sample KML, LLM-usage citation per the course policy
**Principles:** Maintainability, Availability (containerized), documentation completeness
**Commits:** `docs: add README with setup instructions` → `chore: add Dockerfile + compose` → `docs: finalize report and architecture diagram`

---

## Suggested Repo Structure

```
village-pond-catchment/
├── src/
│   ├── config.py
│   ├── terrain/
│   │   ├── base.py            # TerrainSource ABC
│   │   └── kml_source.py      # Module 2
│   ├── geometry/
│   │   ├── pointcloud.py      # Module 4
│   │   └── crs_utils.py
│   ├── dem/
│   │   ├── builder.py         # Module 5
│   │   └── conditioning.py    # Module 6
│   ├── hydrology/
│   │   ├── flow_direction.py  # Module 7
│   │   ├── flow_accumulation.py # Module 8
│   │   └── watershed.py       # Module 10
│   ├── catchment/
│   │   ├── candidates.py      # Module 9
│   │   └── metrics.py         # Module 11
│   ├── api/
│   │   ├── main.py
│   │   ├── routes.py          # Module 12
│   │   └── error_handlers.py  # Module 13
│   └── schemas/                # Pydantic models throughout
├── tests/
│   ├── fixtures/contours_1m.kml
│   ├── unit/
│   └── integration/
├── docs/
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## Why this satisfies the evaluation criteria

| Criterion | How the plan addresses it |
|---|---|
| Working API endpoint | Modules 3, 12 |
| Extensibility to future phases | `TerrainSource` interface (M2) — GeoTIFF/SHP just implement it |
| Catchment identification/estimation correctness | Toy-DEM unit tests (M7, M8, M11) prove algorithmic correctness independent of messy real data |
| Documentation | Swagger auto-docs + README + report (M15) |
| Reliability/Availability/Scalability (system design rubric) | Async I/O, stateless services, Docker, health checks, structured errors (M13, M15) |