# System Architecture — Village Pond Planning System

## High-Level Design

The system exposes **two analysis entry points** that share a common downstream pipeline:

```
Browser (Leaflet SPA)
       │
       │  POST /analyzeContour  (KML/KMZ upload)
       │  POST /analyzeArea     (lat/lon bbox → SRTM tile download)
       │  GET  /api/imagery     (tile metadata)
       │  GET  /api/village/…   (registry search)
       │  GET  /api/results/…   (saved results)
       ▼
┌─────────────────────────────────────────────────────────┐
│                    FastAPI Layer                          │
│   routes.py · imagery.py · error_handlers.py             │
└─────────┬──────────────────────────┬────────────────────┘
          │ run_in_threadpool         │ run_in_threadpool
          ▼                           ▼
 AnalysisService.run()      AnalysisService.run_from_dem()
 (KML/KMZ path)             (Tile DEM path)
          │                           │
    KMLTerrainSource          DemFromTiles
    IDW interpolation         AWS Terrarium PNG tiles
    → DEM object              → DEM object
          │                           │
          └──────────┬────────────────┘
                     ▼  (shared pipeline from here)
         ┌───────────┴────────────────────────────┐
         ▼               ▼              ▼          ▼
   fill_sinks()    ExclusionMasks   D8 routing  find_candidates()
   slope raster    (OSM Overpass)   flow_dir    depression bowls
                                    flow_accum  ranked CandidatePoint[]
                                         │
                                         ▼
                             RainfallService (fail-open)
                             Open-Meteo ERA5 → NASA POWER
                                         │
                                         ▼
                             RunoffEstimate (SCS-CN)
                                         │
                                         ▼
                             PondDesign (IS 5477)
                                         │
                                         ▼
                             Watershed BFS + Polygonize
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
| DEM builder (KML) | `src/dem/builder.py` | IDW interpolation backed by SciPy KD-Tree |
| DEM builder (tiles) | `src/dem/from_tiles.py` | AWS Terrarium PNG tile download, decode, stitch, reproject |
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
| Orchestrator | `src/api/analysis_service.py` | `run()` for KML path · `run_from_dem()` for tile path |
| Reliability | `src/external/` | Retry (3×), timeout, circuit-open on all external calls |
| Persistence | `src/db/` | SQLModel + PostgreSQL JSONB (fail-open init) |
| Village registry | `src/api/routes.py` + `src/db/models.py` | Search + KML retrieval |
| Imagery endpoint | `src/api/imagery.py` | Tile URL metadata (3 providers) |
| Pour-pt override | `src/api/routes.py` + `src/api/analysis_service.py` | Snap to nearest candidate |
| Frontend | `frontend/index.html` | Leaflet SPA + chart + Draw Area tool + override UI |
| Documentation | `frontend/help.html` | System guide: features, data flow, result definitions |

## Key Design Decisions

### Two Entry Points, One Shared Pipeline
The `/analyzeContour` and `/analyzeArea` endpoints produce identical `AnalysisResult` JSON. The only
difference is **how the DEM is built**. Everything from sink-filling onward is shared code in
`AnalysisService`. This means the frontend results section needed zero changes to support the new
tile-based path.

### Free SRTM via AWS Terrarium Tiles
The Draw Area feature uses AWS's public Terrarium elevation tiles
(`s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png`). These are:
- **100% free**, no API key, no rate limit documented
- SRTM-derived, globally available, ~38 m/pixel at zoom 12
- PNG RGB-encoded: `elevation = (R × 256 + G + B/256) − 32768`

Accuracy limitation (surfaced to users via a warning banner): ~38 m/pixel resolution vs 1–2 m/pixel
from hand-supplied KMZ contour maps. Suitable for regional site selection; KMZ upload is recommended
for final engineering design.

### Fail-Open at Every External Boundary
Every external call (OSM Overpass, Open-Meteo, NASA POWER, PostgreSQL, AWS tile server) is wrapped
in a try/except. On failure, the system returns a degraded-but-valid result with machine-readable
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

## Data Flow — KML/KMZ Upload Path

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
DEM (raw, ~2 m grid)
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

## Data Flow — Draw Area Path (SRTM Tiles)

```
User draws bbox on map (south, west, north, east)
    │ POST /analyzeArea?south=…&west=…&north=…&east=…
    ▼
Validate area ≤ MAX_AREA_SELECTION_SQKM (default 10 sq km)
    │
    ▼
DemFromTiles.build_dem_from_bbox()
    │ compute tile x,y range at zoom 12
    │ download 1–25 Terrarium PNG tiles (AWS, free, no key)
    │ decode RGB → elevation_m
    │ stitch tiles into mosaic
    │ clip to bbox
    │ reproject to local UTM
    ▼
DEM (raw, ~38 m grid)  ← same DEM schema as KML path
    │
    ▼ (shared pipeline from here — identical to KML path above)
fill_sinks → slope → OSM masks → candidates → rainfall → runoff → pond_design
→ watershed BFS → polygon → CatchmentMetrics
    │
    ▼
AnalysisResult JSON (warnings includes "dem_from_tiles_low_resolution")
    │
    ▼
Browser: renders all result cards + keeps bbox boundary as dashed blue overlay
```

## Assignment Requirement Coverage

| Requirement | Implementation |
|---|---|
| 1. Display satellite imagery | `/api/imagery` endpoint · Leaflet basemap switcher (3 providers) |
| 2. Accept terrain/boundary input | KMZ upload + Draw Area on map |
| 3. Identify suitable pond locations | Depression analysis + D8 flow + candidate scoring |
| 4. Exclude water bodies & built-up | OSM Overpass → water mask + land mask (fail-open) |
| 5. Estimate catchment area | BFS watershed delineation → area_ha |
| 6. Rainfall data | Open-Meteo ERA5 (primary) → NASA POWER (fallback) · 10-yr monthly |
| 7. Runoff estimation | SCS-CN method with HSG-based CN + built-up fraction |
| 8. Pond design & visualization | IS 5477 storage · IS 12169 embankment · map + sidebar results |
