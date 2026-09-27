# System Architecture — Village Pond Planning System

## High-Level Design

```
Browser (Leaflet SPA)
       │
       │  HTTP POST /analyzeContour  (KML/KMZ upload)
       │  HTTP GET  /api/imagery     (tile metadata)
       │  HTTP GET  /api/village/…   (registry search)
       │  HTTP GET  /api/results/…   (saved results)
       ▼
┌─────────────────────────────────────────────────────┐
│                  FastAPI Layer                       │
│  routes.py · imagery.py · error_handlers.py         │
└───────────────────────┬─────────────────────────────┘
                        │  run_in_threadpool
                        ▼
            AnalysisService.run()
            (15-step orchestrator)
                        │
      ┌─────────────────┼──────────────────────────────┐
      ▼                 ▼                ▼              ▼
TerrainSource       DEMBuilder      ExclusionMasks  HydroEngine
(KML parser)        (IDW + KD-Tree) (OSM Overpass)  (D8 + BFS)
      │                 │                │              │
      ▼                 ▼                ▼              ▼
ContourLine[]        DEM object      water_mask[]   candidates[]
                                    land_mask[]     catchment GeoJSON
                                          │
                                          ▼
                              RainfallService
                              Open-Meteo → NASA POWER
                                          │
                                          ▼
                              RunoffEstimate (SCS-CN)
                                          │
                                          ▼
                              PondDesign (IS 5477)
                                          │
                                          ▼
                              AnalysisResult JSON
                                          │
                               ┌──────────┴──────────┐
                               ▼                     ▼
                         DB (async,              HTTP Response
                         fail-open)              to Browser
```

## Module Map (as shipped)

| Module | Source path | Responsibility |
|--------|------------|----------------|
| Scaffold & CI | `.github/`, `pyproject.toml`, `Dockerfile` | Repo structure, pre-commit, GitHub Actions |
| Terrain parsing | `src/terrain/` | `TerrainSource` ABC · `KMLTerrainSource` · KMZ support |
| Input validation | `src/terrain/validators.py` | File-size, extension, semantic contour checks |
| Point cloud | `src/geometry/pointcloud.py` | Densification + UTM reprojection |
| DEM builder | `src/dem/builder.py` | IDW interpolation backed by SciPy KD-Tree |
| Conditioning | `src/dem/conditioning.py` | Planchon–Darboux Priority-Flood (via pysheds) |
| D8 flow | `src/hydrology/` (pysheds) | Flow direction + accumulation |
| OSM water | `src/catchment/water_exclusion.py` | Overpass query → boolean mask (fail-open) |
| OSM land | `src/catchment/land_exclusion.py` | Built-up exclusion mask (reuses cached XML) |
| Candidates | `src/catchment/candidates.py` | Depression analysis, scoring, water/land veto |
| Watershed | `src/hydrology/watershed.py` | BFS upstream delineation |
| Polygonize | `src/catchment/polygonize.py` | Raster → GeoJSON polygon (Douglas-Peucker) |
| Metrics | `src/catchment/metrics.py` | Area, elevation/slope stats, consistency check |
| Rainfall | `src/catchment/rainfall_service.py` + `src/external/rainfall/` | Open-Meteo ERA5 → NASA POWER fallback |
| Runoff | `src/hydrology/runoff.py` | SCS-CN method; rational-method fallback |
| Pond design | `src/catchment/pond_design.py` | IS 5477 storage reconciliation |
| Unified response | `src/api/analysis_service.py` | Orchestrator wiring all steps |
| Reliability | `src/external/` | Retry (3×), timeout, circuit-open on all external calls |
| Persistence | `src/db/` | SQLModel + PostgreSQL JSONB (fail-open init) |
| Village registry | `src/api/routes.py` + `src/db/models.py` | Search + KML retrieval |
| Imagery endpoint | `src/api/imagery.py` | Tile URL metadata (3 providers) |
| Pour-pt override | `src/api/routes.py` + `src/api/analysis_service.py` | Snap to nearest candidate |
| Frontend | `frontend/index.html` | Leaflet SPA + chart + override UI |

## Key Design Decisions

### Fail-Open at Every External Boundary
Every external call (OSM Overpass, Open-Meteo, NASA POWER, PostgreSQL) is wrapped in a
try/except. On failure, the system returns a degraded-but-valid result with machine-readable
`warnings[]` codes. The topographic analysis never crashes due to an API outage.

### Single Routing Pass
Flow direction and accumulation are computed once inside `find_candidates()`.
The same grids are reused for watershed delineation — eliminating the rounding errors
that arose from a separate fill-and-route pass in earlier drafts.

### Strategy Pattern for `TerrainSource`
The `TerrainSource` ABC decouples input format from the analysis pipeline.
`KMLTerrainSource` is the only implementation today; adding GeoTIFF or Shapefile support
requires a new class without touching any hydrology or API code.

### Snap-to-Candidate for Pour-Point Override
Rather than accepting an arbitrary map click as a pour point (which might not be a depression),
the manual override snaps to the nearest auto-detected candidate bowl. This keeps all downstream
watershed and pond-design calculations valid and is disclosed in `warnings[]`.

### Persistence Decoupled from Analysis
The DB write (`INSERT INTO analysis_runs`) happens in the async route context, after
`run_in_threadpool` returns. This means a DB outage never affects response time or correctness.
`result_id` is `null` in the response if the write fails.

### JSONVariant for Cross-DB Compatibility
`AnalysisRun.result_json` uses a custom `JSONVariant` type decorator that maps to `JSONB`
on PostgreSQL and `TEXT` (JSON-serialised) on SQLite. This lets the full test suite run
locally without requiring PostgreSQL while still using native JSONB in production.

## Data Flow

```
KML/KMZ bytes
    │ parse + reproject
    ▼
ContourLine[]
    │ densify 1-m spacing
    ▼
PointCloud (x, y, z UTM)
    │ IDW + KD-Tree
    ▼
DEM (raw, 2 m grid)
    │ Priority-Flood
    ▼
DEM (filled)  ──► slope_deg raster
    │
    │ Overpass API (fail-open) ──► water_mask, land_mask
    │
    ▼ D8 via pysheds
flow_direction, flow_accumulation
    │
    ▼ depression analysis + scoring + veto
CandidatePoint[] (ranked, best first)
    │
    │ Open-Meteo / NASA POWER (fail-open)
    ▼
RainfallStats (10-yr monthly)
    │ SCS-CN
    ▼
RunoffEstimate (annual_volume_m³)
    │ IS 5477
    ▼
PondDesign (depth, area, storage)
    │
    │ BFS upstream on flow_direction
    ▼
catchment mask (bool raster)
    │ polygonize + Douglas-Peucker
    ▼
CatchmentMetrics (area_ha, polygon GeoJSON, elevation/slope stats)
    │
    ▼
AnalysisResult JSON  ──►  DB (fail-open)  ──►  HTTP response
```
