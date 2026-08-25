# System Architecture — Village Pond Planning System

## High-Level Design

```
Frontend (Map UI)
       │
       │  HTTP POST /analyzeContour  (KML/KMZ file upload)
       ▼
┌──────────────────────────────────────────────────┐
│              FastAPI Layer  (Module 12)           │
│           POST /analyzeContour                    │
└───────────────────────┬──────────────────────────┘
                        │ orchestrates
                        ▼
             AnalysisService (orchestrator)
                        │
       ┌────────────────┼────────────────────────┐
       ▼                ▼              ▼          ▼
 TerrainSource      DEMBuilder    FlowEngine   Catchment
 (KML parser)       (M5–M6)      (M7–M8)      (M9–M11)
 (M2–M3)
       │
  implements
       │
 KMLTerrainSource ── future: GeoTIFFTerrainSource, SHPTerrainSource
```

## Module Map

| Module | Component | Responsibility |
|--------|-----------|----------------|
| 1 | Scaffold | Repo structure, config, CI |
| 2 | `terrain/` | `TerrainSource` ABC + KML/KMZ parser |
| 3 | `terrain/` | Input validation, custom exceptions |
| 4 | `geometry/` | Point cloud extraction + UTM reprojection |
| 5 | `dem/` | Grid interpolation → DEM object |
| 6 | `dem/` | Sink-filling (Planchon-Darboux) + slope raster |
| 7 | `hydrology/` | D8 flow direction (vectorised numpy) |
| 8 | `hydrology/` | Flow accumulation (topological traversal) |
| 9 | `catchment/` | Pond candidate ranking (configurable thresholds) |
| 10 | `hydrology/` | Watershed delineation (BFS upstream) |
| 11 | `catchment/` | Area, elevation stats, metrics schema |
| 12 | `api/` | FastAPI `POST /analyzeContour` + orchestrator |
| 13 | `api/` | Error handlers, structured logging, `/health` |
| 14 | `tests/` | Unit + integration tests, CI coverage |
| 15 | Docs | Dockerfile, README, final report |

## Key Design Decisions

### Strategy Pattern for `TerrainSource`
The `TerrainSource` abstract base class decouples input format from the analysis pipeline.
`KMLTerrainSource` implements it today; future formats (GeoTIFF, Shapefile) will add new
implementations without touching any hydrology or API code.

### Stateless Services
Every geospatial function is a pure function — no class state, no shared mutable data.
This makes unit testing trivial (pass in data, assert output) and enables horizontal scaling.

### Pydantic at Every Boundary
`ContourLine → PointCloud → DEM → CandidatePoint → CatchmentMetrics → AnalysisResult`
Each transformation is type-checked. Silent data corruption is caught at the boundary, not
silently propagated downstream.

### Config-Driven Thresholds
All hydrological thresholds (`accumulation_percentile_threshold`, `max_candidate_slope_deg`)
live in `src/config.py` and are settable via environment variables.
No magic numbers anywhere in `src/hydrology/` or `src/catchment/`.

## Data Flow

```
KML file bytes
    │
    ▼ Module 2–3
ContourLine[]  (elevation + point geometry)
    │
    ▼ Module 4
PointCloud     (x,y,z in metres, UTM CRS)
    │
    ▼ Module 5
DEM            (numpy 2D array + geotransform)
    │
    ▼ Module 6
DEM (filled)   + slope raster
    │
    ▼ Module 7
flow_direction raster
    │
    ▼ Module 8
flow_accumulation raster
    │
    ├── ▼ Module 9
    │   CandidatePoint[]   (ranked by score)
    │
    └── ▼ Module 10
        catchment mask (boolean raster)
            │
            ▼ Module 11
        CatchmentMetrics (area_ha, elevation_stats, polygon GeoJSON)
            │
            ▼ Module 12
        AnalysisResult JSON  ──► Frontend
```
