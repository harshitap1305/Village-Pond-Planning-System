# Village Pond Planning System

> **AI-based site selection tool** for rural rainwater harvesting — identify the optimal pond location from a KML/KMZ contour map in under 90 seconds.

---

## Live Demo

| URL | Description |
|---|---|
| `POST /analyzeContour` | Upload a KML/KMZ → get candidates + catchment |
| `GET /docs` | Interactive Swagger UI |
| `GET /health` | Health check |
| `GET /api/imagery` | Basemap tile metadata (satellite/street) |
| `GET /api/village/search?q=` | Village registry search |
| `GET /api/results/{id}` | Retrieve a saved analysis (requires DB) |

---

## What it Produces

Upload a KML/KMZ contour file for any village area and receive a structured JSON response containing:

- **Ranked pond candidate locations** — lat/lon, depression depth, estimated storage volume, and a normalized catchment score
- **Catchment watershed polygon** (GeoJSON, WGS84) — ready to render on any mapping library
- **10-year historical rainfall statistics** — mean monthly + annual (Open-Meteo ERA5-Land primary; NASA POWER MERRA-2 fallback)
- **SCS-CN runoff estimate** — annual runoff volume (m³) for the selected catchment
- **IS 5477 pond design** — recommended depth, surface area, embankment volume
- **OSM exclusion metadata** — water bodies and built-up land that were vetoed

---

## Algorithm — How It Works

The pipeline runs in **~90 seconds** (offline except for OSM + rainfall API calls) and implements classical civil engineering hydrology, not a black-box model.

### Step 1 — KML/KMZ Parsing

Parses the XML-based KML format to extract elevation contour `LineString` rings. Each `Placemark` must carry an altitude value (either as a coordinate Z-component or in the `<name>` field). The parser supports both `.kml` (plain XML) and `.kmz` (ZIP-compressed KML) formats.

### Step 2 — UTM Reprojection & Point Cloud

All WGS84 (lat/lon) contour vertices are reprojected into the correct **local UTM zone** (automatically determined from the centroid). The metric CRS is essential for correct distance/area calculations. Contour lines are then **densified** (1-metre vertex spacing) to produce a dense 3D point cloud `(x, y, z)`.

### Step 3 — DEM Interpolation (IDW + KD-Tree)

The point cloud is interpolated onto a 2D regular grid (default 2 m × 2 m resolution) using **Inverse Distance Weighting** backed by a SciPy `KDTree` spatial index. For each empty cell, the algorithm finds the *k*-nearest contour points and assigns an elevation weighted by `1/distance²`. This produces a continuous **Digital Elevation Model (DEM)**.

### Step 4 — Hydrological Conditioning (Priority-Flood)

Raw interpolated DEMs contain artificial "pits" that trap simulated water flow. The **Planchon–Darboux Priority-Flood algorithm** (via `pysheds`) fills all pits by simulating water rising until it spills over the lowest outlet, producing a "filled DEM" where every cell has a continuous downhill path to the map edge. The unfilled raw DEM is retained separately for depression-depth calculations.

### Step 5 — D8 Flow Network + Accumulation

The filled DEM is modelled as a directed graph. The **D8 (Deterministic Eight-Node)** algorithm assigns each cell a flow-direction pointer to its steepest downhill neighbour (8-connectivity). A **topological traversal** accumulates upstream cell counts: high-accumulation cells represent valleys and channel lines.

### Step 6 — OSM Water & Land Exclusion (Fail-Open)

The DEM bounding box is queried against the **Overpass API** for OpenStreetMap water features (rivers, lakes, ponds, canals) and built-up land (buildings, residential/commercial landuse). Features are:
- Converted to Shapely geometries
- Buffered by configurable safety margins (15 m rivers, 5 m lakes)
- Rasterised onto the DEM grid to produce boolean exclusion masks

If the Overpass API is unreachable, both masks default to **all-false (fail-open)** — the analysis continues without exclusions rather than crashing.

### Step 7 — Pond Candidate Selection

Natural pond sites are found by computing the **depression depth** (`filled_dem - raw_dem`). Cells with depth > 0 are contiguous topographic bowls. For each bowl:

- **Volume** = `Σ (depth_cell × cell_area_m²)`
- **Catchment area** = sum of flow-accumulation values at the bowl's sink cells
- **Score** = `catchment_cells / total_DEM_cells` (normalised, size-independent)
- **Hard veto**: any bowl overlapping the OSM water or land exclusion mask is discarded

Candidates are ranked by score (descending). The top candidate is selected for all downstream calculations.

### Step 8 — Rainfall & Runoff (SCS-CN Method, Fail-Open)

After candidate selection, the system fetches **10-year historical monthly rainfall** for the selected site's coordinates:
1. **Primary**: Open-Meteo ERA5-Land reanalysis (~9 km resolution, free, no key required)
2. **Fallback**: NASA POWER MERRA-2 (~50 km resolution, free, no key required)

Runoff is estimated using the **SCS Curve Number (CN) method**:

```
Q = (P - 0.2S)² / (P + 0.8S),   where S = 1000/CN - 10
```

CN is derived from soil hydrological group (configurable, default HSG-B) and built-up fraction (from the OSM land mask). Annual volume = `Q × catchment_area_m²`.

If both rainfall APIs are unavailable, `rainfall`, `runoff`, and `pond_design` are returned as `null` with machine-readable warning codes — the topographic analysis still completes.

### Step 9 — Watershed Delineation (BFS Upstream)

Given the selected pour point, the D8 flow-direction grid is **reversed** and a **Breadth-First Search** walks upstream from the pour point, visiting every cell that drains into it. The resulting boolean raster mask is:
1. **Polygonized** (rasterio/shapely) into a contiguous polygon
2. **Simplified** (Douglas-Peucker) to reduce vertex count
3. **Reprojected** to WGS84 GeoJSON for frontend rendering

### Step 10 — Pond Design (IS 5477)

Reconciles hydrological supply with topographic capacity using **IS 5477 (Indian Standard for tank design)**:

- **Storage required** = `annual_runoff × design_years` (configurable, default 1 year)
- **Pond depth** = constrained between 2–4 m (configurable `min_pond_depth_m` / `max_pond_depth_m`)
- **Surface area** = `storage_volume / depth`, validated against the topographic bowl area
- `constrained_by` field indicates whether design was limited by topography or hydrology

---

## Technology Stack

| Layer | Technology |
|---|---|
| **API** | Python 3.12 · FastAPI · uvicorn · Starlette |
| **Geospatial** | NumPy · SciPy · PyProj · Shapely · pysheds · Rasterio |
| **KML Parsing** | lxml · fastkml |
| **HTTP Clients** | httpx (async) with retry + timeout hardening |
| **Persistence** | SQLModel + PostgreSQL (JSONB) · SQLite (test fallback via `JSONVariant`) |
| **Config** | pydantic-settings (12-factor env-based, `.env` file) |
| **Frontend** | Vanilla HTML/CSS/JS · Leaflet.js · Chart.js |
| **CI** | GitHub Actions · black · ruff · pre-commit |

---

## Quick Start

### Prerequisites

```bash
sudo apt-get install build-essential libgdal-dev
```

### Local Setup

```bash
git clone https://github.com/harshitap1305/Village-Pond-Planning-System.git
cd Village-Pond-Planning-System

python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env — minimum required: nothing (DATABASE_URL is optional)
```

### Run the API

```bash
# Development (auto-reload)
uvicorn src.api.main:app --reload
# → API: http://localhost:8000
# → Swagger docs: http://localhost:8000/docs
# → Frontend: http://localhost:8000/
```

### Run with Docker

```bash
docker compose up --build
# → http://localhost:8000
```

### Run with Persistence (PostgreSQL)

```bash
# In .env or docker-compose.yml:
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/ponddb

# Seed villages (optional):
python scripts/seed_villages.py
```

### Run Tests

```bash
# All tests (336 total, ~90s)
pytest tests/unit/ tests/integration/ -v

# Fast unit tests only (~10s)
pytest tests/unit/ -v

# With coverage
pytest --cov=src --cov-report=term-missing
```

---

## API Reference

### `POST /analyzeContour`

Upload a KML or KMZ contour file. Returns full analysis.

```bash
curl -F "contour_map=@village.kml" http://localhost:8000/analyzeContour

# With manual pour-point override:
curl -F "contour_map=@village.kml" \
  "http://localhost:8000/analyzeContour?pour_lat=19.1234&pour_lon=82.5678"
```

**Query Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `pour_lat` | float (optional) | Manual pour-point latitude — snaps to nearest auto-detected candidate |
| `pour_lon` | float (optional) | Manual pour-point longitude |
| `cell_size` | float (optional) | DEM grid resolution override in metres (default: 2.0) |

**Response** (abbreviated):

```json
{
  "selected_location": { "lat": 19.12, "lon": 82.56, "score": 0.42, "elevation": 321.5, ... },
  "candidate_locations": [ ... ],
  "catchment": { "area_ha": 18.4, "polygon_geojson": { ... }, "elevation_stats": { ... } },
  "rainfall": { "annual_avg_mm": 1180, "monthly_avg_mm": [ ... ] },
  "runoff": { "annual_volume_m3": 84200, "method": "scs_cn", "cn": 72 },
  "pond_design": { "recommended_depth_m": 3.0, "surface_area_ha": 0.93, ... },
  "warnings": [],
  "result_id": "a1b2c3d4-..."
}
```

**Graceful degradation chain:**
If rainfall APIs fail → `rainfall: null`, `runoff: null`, `pond_design: null`.
Warning codes: `rainfall_unavailable` · `runoff_unavailable` · `pond_design_unavailable` · `pour_point_overridden`

### `GET /api/imagery`

Returns tile URL metadata for map basemaps.

```bash
curl "http://localhost:8000/api/imagery?provider=esri_satellite"
```

| Provider | Description |
|---|---|
| `esri_satellite` (default) | Esri World Imagery — best for site review |
| `carto_light` | CartoDB Positron street map |
| `osm_standard` | OpenStreetMap Carto |

### `GET /api/village/search?q=`

Search the village registry by name (requires `DATABASE_URL`).

### `GET /api/village/{id}/kml`

Download the KML for a registered village to trigger analysis.

### `GET /api/results/{id}`

Retrieve a previously saved analysis result by UUID.

---

## Frontend Features

The web UI at `http://localhost:8000/` provides:

- **Upload KML/KMZ** — drag-and-drop or click-to-browse
- **Village search** — type-ahead search across the registered village registry
- **Live map** with Leaflet: catchment polygon, candidate markers, selected site star
- **Basemap switcher** — 🗺 Street / 🛰 Satellite toggle (Module 10)
- **Pour-point override** — click "📍 Override pour point", then click any map location to re-run with a user-chosen site (Module 11)
- **Results sidebar** — site coordinates, catchment stats, monthly rainfall chart, pond design card
- **Warnings banner** — human-readable degradation notices

---

## Project Structure

```
src/
├── api/
│   ├── main.py               # FastAPI app, lifespan, router registration
│   ├── routes.py             # POST /analyzeContour, GET /health, GET /results/{id}
│   ├── imagery.py            # GET /api/imagery (Module 10)
│   ├── analysis_service.py   # Orchestrator — wires 15-step pipeline
│   └── error_handlers.py     # Structured HTTP error responses
├── terrain/                  # KML/KMZ parsing, TerrainSource ABC
├── geometry/                 # Point cloud + UTM reprojection
├── dem/                      # IDW interpolation, sink-filling, slope
├── hydrology/                # D8 flow, accumulation, watershed BFS
│   ├── rainfall_stats.py     # RainfallStats schema
│   └── runoff.py             # SCS-CN runoff estimation
├── catchment/
│   ├── candidates.py         # Depression analysis + candidate ranking
│   ├── water_exclusion.py    # OSM water mask (fail-open)
│   ├── land_exclusion.py     # OSM built-up mask (fail-open)
│   ├── rainfall_service.py   # Open-Meteo → NASA POWER orchestration
│   ├── pond_design.py        # IS 5477 pond dimensioning
│   └── polygonize.py         # Raster mask → GeoJSON polygon
├── external/
│   ├── rainfall/             # Open-Meteo + NASA POWER clients (retry/timeout)
│   └── water/                # Overpass/OSM client (retry/timeout)
├── db/
│   ├── engine.py             # Async SQLAlchemy engine (fail-open init)
│   └── models.py             # AnalysisRun + Village SQLModel tables
├── schemas/
│   ├── response.py           # AnalysisResult top-level schema
│   └── catchment.py          # CandidatePoint schema
└── config.py                 # Central pydantic-settings config (50+ fields)

frontend/
├── index.html                # Single-page app (Leaflet + Chart.js)
└── env.js                    # Runtime config injection (API_BASE_URL, etc.)

tests/
├── fixtures/                 # contours_1m.kml, broken KMLs, toy DEMs
├── unit/                     # 25+ per-module unit test files
└── integration/              # Full pipeline + API-level tests

scripts/
└── seed_villages.py          # Populate village registry from KML files

docs/
└── architecture.md           # System design + data flow diagram
```

---

## Configuration

All settings live in `src/config.py` and are overridable via environment variables or `.env`:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | *(unset)* | PostgreSQL connection string; omit for DB-less mode |
| `MAX_UPLOAD_MB` | `20` | File upload size limit |
| `CELL_SIZE_M` | `2.0` | DEM grid resolution in metres |
| `MIN_CATCHMENT_AREA_HA` | `1.0` | Minimum catchment to report a candidate |
| `MIN_DEPRESSION_AREA_SQM` | `100` | Minimum bowl area to consider |
| `MAX_CANDIDATE_SLOPE_DEG` | `15` | Hard slope veto for candidates |
| `DEFAULT_HSG` | `B` | Soil hydrological group for SCS-CN |
| `MIN_POND_DEPTH_M` | `2.0` | Minimum pond depth (IS 5477) |
| `MAX_POND_DEPTH_M` | `4.0` | Maximum pond depth (IS 5477) |
| `OPEN_METEO_TIMEOUT_S` | `10` | Per-attempt timeout for Open-Meteo |
| `OPEN_METEO_RETRIES` | `3` | Retry attempts before failover to NASA POWER |
| `OSM_BUFFER_RIVER_M` | `15` | Safety buffer around OSM river ways |
| `OSM_BUFFER_LAKE_M` | `5` | Safety buffer around OSM lake areas |

Frontend variables (in `frontend/env.js`):

| Variable | Default | Description |
|---|---|---|
| `API_BASE_URL` | `""` (same origin) | Backend URL for cross-origin deployments |
| `TILE_URL` | CartoDB Light | Fallback tile URL if `/api/imagery` unavailable |
| `MAP_INITIAL_VIEW` | `[22.5, 80.0, 5]` | Map centre and zoom on load |
| `WET_SEASON_MONTHS` | `[5,6,7,8]` | Highlighted months on rainfall chart |
| `MAX_UPLOAD_MB` | `20` | Client-side upload size hint |

---

## Features Built vs. Architecture-Only

| Feature | Status |
|---|---|
| KML/KMZ parsing + DEM | ✅ Fully implemented & tested |
| OSM water/land exclusion | ✅ Fully implemented & tested (fail-open) |
| Rainfall (Open-Meteo + NASA POWER) | ✅ Implemented with retry + failover |
| SCS-CN runoff estimation | ✅ Implemented & tested |
| IS 5477 pond design | ✅ Implemented & tested |
| Pour-point override (Module 11) | ✅ Implemented — snap to nearest candidate |
| Satellite imagery endpoint (Module 10) | ✅ Implemented — 3 tile providers |
| Persistence (PostgreSQL JSONB) | ✅ Implemented — fail-open, result_id in response |
| Village registry + search | ✅ Implemented — `/api/village/search`, `/api/village/{id}/kml` |
| Docker deployment | ✅ `docker compose up --build` |
| CI (GitHub Actions) | ✅ black + ruff + pytest on every push |

---

## LLM Usage

This project used LLM assistance (Google Gemini / Claude) throughout development. The usage was transparent and verification-first:

- **Architecture review**: LLMs were used to review HLD documents and flag inconsistencies (e.g., scoring formula mismatch, area-consistency thresholds).
- **Code generation**: Boilerplate for new modules (rainfall clients, pond design, DB models) was AI-generated then manually verified against reference standards (SCS-CN tables, IS 5477, OSM tagging conventions).
- **Test generation**: Unit test skeletons were AI-generated; all test values were hand-computed or cross-referenced against published formula results.
- **Bug finding**: LLM review caught a real bug (flow-routing inconsistency between candidacy and watershed delineation) that was subsequently fixed and verified with a regression test.

In all cases, every generated code block was read, understood, and validated before being committed. No AI output was accepted without independent verification.

---

## License

MIT — see [LICENSE](LICENSE)
