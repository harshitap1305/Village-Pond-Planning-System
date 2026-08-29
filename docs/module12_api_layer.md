# Module 12: API Layer & Pipeline Orchestration

## Overview

Module 12 serves as the grand finale of the core processing logic, wiring together Modules 2-11 into a cohesive pipeline accessible via a `POST /analyzeContour` HTTP endpoint using **FastAPI**.

## Design Decisions

- **Stateless Orchestrator**: `AnalysisService` is a module-level singleton with no internal state, making it thread-safe for concurrent API requests.
- **Threadpool Offloading**: The entire 14-step pipeline is heavily CPU-bound (NumPy operations, BFS traversals). We run it using `starlette.concurrency.run_in_threadpool` to prevent the async event loop from freezing and blocking other incoming requests.
- **Pour Point Back-Projection**: Candidate locations are output in WGS84 coordinates (`lat`/`lon`). The service safely projects these back to the local UTM grid to resolve the exact `(row, col)` indexes needed for the catchment BFS delineation.

## Core Components

### 1. `AnalysisService`
Located in `src/api/analysis_service.py`. This orchestrator receives the raw bytes of a KML/KMZ upload and passes it through the complete pipeline:
1. Validate file size and type.
2. Extract contours via KML parser.
3. Validate spatial geometry.
4. Construct Point Cloud and DEM.
5. Fill sinks and compute slope.
6. Compute flow direction and accumulation.
7. Identify top candidate locations.
8. Select best candidate and project to grid coordinates.
9. Delineate catchment mask via BFS.
10. Vectorize mask to WGS84 GeoJSON polygon.
11. Compute catchment statistics.
12. Assemble `AnalysisResult` response.

### 2. `POST /analyzeContour`
Located in `src/api/routes.py`. The primary API endpoint. Accepts `multipart/form-data` uploads (`UploadFile`) and an optional `cell_size` parameter.

### 3. Response Schemas
Located in `src/schemas/response.py`. Defines `AnalysisResult`, `CatchmentResult`, and `AnalysisMetadata` to structure the API output identically to the project requirements. The `polygon_geojson` field directly embeds standard GeoJSON formatting via `shapely.geometry.mapping`.

## Verification

The pipeline was run end-to-end against the real 1-meter contour data (`contours_1m.kml`).
- **DEM created**: 1318x1626
- **Best Candidate found**: lat=21.259434, lon=81.283238
- **Catchment Area**: 0.8644 hectares
- **Total processing time**: ~60 seconds (due to large unoptimized DEM size).
