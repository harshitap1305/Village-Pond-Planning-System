# Module-Wise Detailed To-Do — Contour-to-Catchment Backend

This expands each of the 15 modules from the implementation plan into concrete, sequential tasks —
what to install, what file to create, what function to write, and how to verify it's actually done
before moving on. Follow it top to bottom; each module assumes the previous ones are committed.

---

## Module 1 — Repo Scaffolding & Project Skeleton

**What to do:**
1. `git init village-pond-catchment`, create a public/private GitHub repo, push empty commit.
2. Create the folder skeleton:
   ```
   mkdir -p src/{terrain,geometry,dem,hydrology,catchment,api,schemas} tests/{unit,integration,fixtures} docs
   ```
3. Set up Python environment: `python -m venv .venv`, activate it.
4. Create `requirements.txt` with initial deps (you'll add more per module):
   ```
   fastapi
   uvicorn[standard]
   pydantic
   pydantic-settings
   numpy
   scipy
   shapely
   pyproj
   rasterio
   richdem
   fastkml
   lxml
   pytest
   pytest-cov
   httpx
   ```
5. `pip install -r requirements.txt`, then `pip freeze > requirements-lock.txt`.
6. Write `src/config.py`:
   - A `Settings(BaseSettings)` class with fields like `cell_size_m: float = 2.0`, `max_upload_mb: int = 20`, `env: str = "dev"`.
   - Load from `.env` (add `.env.example` to repo, real `.env` to `.gitignore`).
7. Write `.gitignore` (venv, `__pycache__`, `.env`, `*.pyc`, `/tmp_outputs`).
8. Write a stub `README.md` with project title, one-line description, "Setup instructions coming soon."
9. Set up pre-commit: `pip install pre-commit`, add `.pre-commit-config.yaml` with `black`, `ruff`.
10. Write `.github/workflows/ci.yml`: on push/PR, install deps, run `ruff check .`, run `pytest` (will pass trivially since no tests yet — that's fine).
11. Verify: `pytest` runs (even with 0 tests), CI badge shows green on GitHub.

**Commit checkpoints:**
- `chore: init repo structure and folders`
- `chore: add config module and env handling`
- `ci: add lint + test GitHub Actions workflow`

---

## Module 2 — Terrain Source Interface & KML/KMZ Ingestion

**What to do:**
1. In `src/schemas/terrain.py`, define:
   ```python
   class ContourLine(BaseModel):
       elevation: float
       points: List[Tuple[float, float]]  # (lon, lat)
   ```
2. In `src/terrain/base.py`, define the abstract interface:
   ```python
   class TerrainSource(ABC):
       @abstractmethod
       def extract_contours(self) -> List[ContourLine]: ...
   ```
   This is the single most important interface in the whole project — every future format (GeoTIFF, SHP) will implement this same method signature.
3. In `src/terrain/kml_source.py`, implement `KMLTerrainSource(TerrainSource)`:
   - Constructor takes raw bytes or a file path.
   - If filename ends `.kmz`, unzip in-memory (`zipfile.ZipFile`) and pull `doc.kml`.
   - Parse with `lxml.etree` (namespace-aware — your sample file uses `xmlns="http://www.opengis.net/kml/2.2"`).
   - For each `<Placemark>`: read elevation from `<name>` (your sample's convention), fall back to reading Z from `<coordinates>` if present (defensive — some KML exporters embed elevation there instead).
   - Parse `<coordinates>` text: split on whitespace, split each pair on comma, cast to floats.
   - Return list of `ContourLine`.
4. Write a quick manual script `scripts/try_kml_parse.py` that loads `tests/fixtures/contours_1m.kml` and prints `len(contours)`, min/max elevation — run it manually to sanity check against the ~2711 lines / 267–~330m range you'd expect from the sample.
5. Copy `contours_1m.kml` into `tests/fixtures/`.

**Commit checkpoints:**
- `feat: define TerrainSource abstract interface`
- `feat: implement KML contour parser`
- `feat: add KMZ zip-extraction support`

---

## Module 3 — Input Validation & File Upload Handling

**What to do:**
1. In `src/terrain/exceptions.py`, define:
   ```python
   class TerrainParseError(Exception): ...
   class InvalidGeometryError(Exception): ...
   class UnsupportedFormatError(Exception): ...
   ```
2. In `KMLTerrainSource`, wrap parsing in try/except; raise `TerrainParseError` with a clear message on malformed XML.
3. Add validation function `validate_contours(contours: List[ContourLine])`:
   - Reject if `len(contours) < 2` — can't interpolate a surface from one line.
   - Reject if any `ContourLine.points` has `< 2` points.
   - Reject if all elevations are identical (flat file, nothing to interpolate).
4. Add file-level checks before parsing even starts (in the future API layer, but write the pure function now so it's testable):
   - Extension must be `.kml` or `.kmz`.
   - Size must be under `settings.max_upload_mb`.
5. Create 2-3 broken fixture files in `tests/fixtures/`: `empty.kml`, `single_line.kml`, `not_xml.kml` (just garbage text).
6. Write `tests/unit/test_kml_validation.py` asserting each broken fixture raises the right exception.

**Commit checkpoints:**
- `feat: add custom exception hierarchy`
- `feat: add contour validation checks`
- `test: add malformed-KML fixtures and validation tests`

---

## Module 4 — Point Cloud Extraction & Coordinate Normalization

**What to do:**
1. In `src/schemas/geometry.py`, define:
   ```python
   class PointCloud(BaseModel):
       x: List[float]   # meters, projected
       y: List[float]
       z: List[float]   # elevation
       crs: str          # e.g. "EPSG:32644"
   ```
2. In `src/geometry/crs_utils.py`, write `detect_utm_epsg(lon: float, lat: float) -> int`:
   - Formula: `zone = int((lon + 180) / 6) + 1`; northern hemisphere if `lat >= 0` → EPSG `326xx`, else `327xx`.
   - For your sample data (lon ≈ 81.28, lat ≈ 21.26 — Chhattisgarh, India), this should resolve to UTM zone 44N, EPSG:32644 — write a unit test asserting exactly that, since it's a known fixed answer for your sample file.
3. In `src/geometry/pointcloud.py`, write `build_point_cloud(contours: List[ContourLine]) -> PointCloud`:
   - Compute centroid of all points, feed into `detect_utm_epsg`.
   - Use `pyproj.Transformer.from_crs("EPSG:4326", target_epsg, always_xy=True)` to reproject every `(lon, lat)` to `(x, y)` meters.
   - Flatten all `(x, y, elevation)` triples across all contour lines into the `PointCloud`.
   - De-duplicate identical `(x, y)` pairs (keep first occurrence) — contour vertices sometimes repeat at line joins.
4. Write `tests/unit/test_pointcloud.py`: build point cloud from the sample fixture, assert `len(x) > 0`, assert projected coordinates are in a sane meter range (not still in the 0–100 degree range — that alone catches a broken reprojection).

**Commit checkpoints:**
- `feat: add UTM zone auto-detection`
- `feat: implement point cloud extraction with reprojection`
- `test: validate CRS detection and point cloud output`

---

## Module 5 — DEM Construction via Interpolation

**What to do:**
1. In `src/schemas/dem.py`, define:
   ```python
   class DEM(BaseModel):
       class Config: arbitrary_types_allowed = True
       array: Any          # numpy 2D array of elevations
       origin_x: float      # meters, top-left corner
       origin_y: float
       cell_size: float     # meters
       crs: str
       nodata: float = -9999.0
   ```
2. In `src/dem/builder.py`, write `build_dem(pc: PointCloud, cell_size: float) -> DEM`:
   - Compute bounding box from `pc.x`/`pc.y`, add small buffer (e.g. 1 cell) so edge points aren't clipped.
   - Build a regular grid of `(xi, yi)` at `cell_size` spacing using `numpy.meshgrid`.
   - Interpolate with `scipy.interpolate.griddata((pc.x, pc.y), pc.z, (xi, yi), method="linear")`.
   - Fill any `NaN` at the edges (outside convex hull of points) with `method="nearest"` as a second pass, so you don't get holes.
   - Wrap the result in a `DEM` object with the correct geotransform.
3. Write a sanity-check function `validate_dem(dem: DEM, contours: List[ContourLine])`:
   - Assert `dem.array` min/max fall within [min elevation - tolerance, max elevation + tolerance] of the input contours — catches interpolation blow-ups.
4. Write `scripts/debug_plot_dem.py`: `matplotlib.pyplot.imshow(dem.array)`, save PNG — run manually to visually eyeball that the interpolated surface looks like sensible terrain (smooth hills, no giant spikes) for the sample file.
5. Write `tests/unit/test_dem_builder.py` using the toy/sample data — assert DEM shape matches expected grid dimensions and elevation range is sane.

**Commit checkpoints:**
- `feat: implement grid interpolation for DEM construction`
- `feat: add DEM validation against source contour range`
- `chore: add debug DEM plotting script`

---

## Module 6 — DEM Conditioning (Sink Filling) & Slope

**What to do:**
1. Install/verify `richdem` works (`pip install richdem` — note: needs a C++ toolchain on some systems; if it fails to build, fall back to a pure-Python sink-fill via `scipy.ndimage` — document whichever you use).
2. In `src/dem/conditioning.py`, write `fill_sinks(dem: DEM) -> DEM`:
   - Convert `dem.array` to `richdem.rdarray(dem.array, no_data=dem.nodata)`.
   - Call `richdem.FillDepressions(rd_array, in_place=False)`.
   - Return a new `DEM` with the filled array (same geotransform).
3. In `src/dem/slope.py`, write `compute_slope(dem: DEM) -> np.ndarray`:
   - Use `np.gradient(dem.array, dem.cell_size)` to get `dz/dx`, `dz/dy`.
   - `slope_rad = np.arctan(np.sqrt(dzdx**2 + dzdy**2))`; convert to degrees if you want human-readable output.
   - This matches your HLD formula exactly — keep the docstring citing it.
4. Optionally write `compute_aspect(dem: DEM) -> np.ndarray` (direction of steepest descent, `np.arctan2(-dzdy, dzdx)`) — not required by the assignment but cheap to add and useful later for suitability scoring.
5. Write `tests/unit/test_conditioning.py`: build a toy 5×5 DEM with one artificial pit in the middle, run `fill_sinks`, assert the pit value is raised to match its lowest neighbor (standard depression-filling check).
6. Write `tests/unit/test_slope.py`: toy DEM with a known constant gradient (e.g. a tilted plane), assert computed slope matches the analytically expected angle.

**Commit checkpoints:**
- `feat: add sink-filling via RichDEM`
- `feat: compute slope raster`
- `test: validate sink-filling and slope against toy DEM`

---

## Module 7 — Flow Direction (D8 Algorithm)

**What to do:**
1. In `src/hydrology/flow_direction.py`, write `compute_flow_direction(dem: DEM) -> np.ndarray`:
   - For each cell, compare elevation to its 8 neighbors.
   - Direction = neighbor with the steepest downward slope: `drop = (z_center - z_neighbor) / distance` (distance is `cell_size` for orthogonal neighbors, `cell_size * sqrt(2)` for diagonals).
   - Encode direction as an integer code (common D8 convention: 1=E, 2=SE, 4=S, 8=SW, 16=W, 32=NW, 64=N, 128=NE) or simply store `(dx, dy)` offset per cell — pick whichever you find easier to reason about, document the choice.
   - Handle edge cells (no valid downhill neighbor within bounds) by marking as a "sink"/outlet.
   - Hand-roll this with numpy (vectorized comparison against all 8 shifted arrays) instead of a per-cell Python loop — much faster and better demonstrates the "scalability" principle.
2. Build a **toy DEM** fixture in `tests/fixtures/toy_dem.py`: a hard-coded 5×5 numpy array shaped like a simple valley (e.g. elevations decreasing toward one corner) where you can compute the correct flow direction by hand.
3. Write `tests/unit/test_flow_direction.py`: run `compute_flow_direction` on the toy DEM, assert every cell's direction matches your hand-computed expected array exactly.

**Commit checkpoints:**
- `feat: implement D8 flow direction (vectorized)`
- `test: add toy DEM fixture with known flow directions`
- `test: validate D8 output against toy DEM`

---

## Module 8 — Flow Accumulation

**What to do:**
1. In `src/hydrology/flow_accumulation.py`, write `compute_flow_accumulation(flow_dir: np.ndarray) -> np.ndarray`:
   - Initialize accumulation array to 1 (each cell contributes itself).
   - Process cells in order of decreasing elevation (topological order — a cell can only receive flow after all its upstream neighbors have been processed), OR use `richdem`'s built-in `FlowAccumulation` function if it's already in your dependency set from Module 6 (recommended — less code, well-tested).
   - Each cell adds its accumulated value to whichever downstream cell its flow direction points to.
2. Write a helper `top_accumulation_cells(accum: np.ndarray, percentile: float = 95) -> np.ndarray` (boolean mask) — useful for the debug visualization and for Module 9's candidate detection.
3. Write `scripts/debug_plot_accumulation.py`: plot `log(accum + 1)` as an image (log scale makes drainage channels visible against low-accumulation background) — run manually on the sample DEM to visually confirm channels look plausible.
4. Write `tests/unit/test_flow_accumulation.py`: run on the same toy DEM from Module 7, assert accumulation values match hand-calculated expected values (e.g. the outlet cell should have accumulation = 25 for a 5×5 grid if all flow converges there).

**Commit checkpoints:**
- `feat: implement flow accumulation`
- `chore: add accumulation debug visualization`
- `test: validate accumulation against toy DEM`

---

## Module 9 — Pond Candidate Location Identification

**What to do:**
1. In `src/config.py`, add tunable settings: `accumulation_percentile_threshold: float = 90.0`, `max_candidate_slope_deg: float = 15.0`.
2. In `src/catchment/candidates.py`, write `find_candidates(dem, flow_accum, slope) -> List[CandidatePoint]`:
   - Mask = `(flow_accum >= percentile(flow_accum, threshold)) & (slope <= max_slope)`.
   - From the masked cells, cluster nearby cells together (e.g. `scipy.ndimage.label`) so you don't return 50 adjacent pixels as 50 separate "candidates" — take the highest-accumulation cell per cluster as its representative point.
   - Convert each representative cell's `(row, col)` back to real-world coordinates: raster→meters (using DEM geotransform)→ reproject back to WGS84 lat/lon using `pyproj` (inverse of Module 4's transformer).
   - Assign a simple `score` (e.g. normalized accumulation value) so candidates can be ranked.
   - Return a sorted list (highest score first), schema:
     ```python
     class CandidatePoint(BaseModel):
         lat: float; lon: float; elevation: float; score: float
     ```
3. **Important:** every threshold here comes from `settings`, not a hard-coded number — this is what the assignment explicitly checks for.
4. Write `tests/unit/test_candidates.py` using the toy DEM: assert the returned candidate coordinates fall inside the expected low-accumulation-sink region you designed the toy DEM around.

**Commit checkpoints:**
- `feat: implement candidate point selection`
- `feat: make thresholds configurable via settings`
- `test: validate candidate detection on toy DEM`

---

## Module 10 — Catchment Delineation (Watershed Extraction)

**What to do:**
1. In `src/hydrology/watershed.py`, write `delineate_catchment(flow_dir: np.ndarray, pour_point_rc: Tuple[int,int]) -> np.ndarray` (returns boolean mask same shape as DEM):
   - Standard approach: reverse the flow-direction graph (for each cell, know which cells point *into* it), then do a BFS/DFS upstream from the pour point, marking every cell that can reach it as `True`.
   - Alternatively use `richdem`'s built-in watershed/basin function if available, and just validate its output — less code to maintain.
2. In `src/catchment/polygonize.py`, write `mask_to_polygon(mask: np.ndarray, dem: DEM) -> shapely.Polygon (or MultiPolygon)`:
   - Use `rasterio.features.shapes(mask.astype('uint8'), transform=dem_transform)` to vectorize the mask into polygon(s).
   - Merge multiple polygon fragments with `shapely.ops.unary_union` if the mask isn't contiguous.
   - Reproject the polygon back to WGS84 (`pyproj.Transformer`) for GeoJSON output.
   - Add `.simplify(tolerance)` to reduce vertex count for frontend map performance (per your own HLD's "map performance with multiple layers" risk).
3. Write `tests/unit/test_watershed.py` on the toy DEM: pick the known outlet cell as pour point, assert the delineated mask equals the *entire* toy grid (since in your toy valley example, all cells should drain to one outlet).

**Commit checkpoints:**
- `feat: implement watershed delineation from pour point`
- `feat: convert catchment mask to GeoJSON polygon`
- `test: validate watershed delineation on toy DEM`

---

## Module 11 — Catchment Metrics Computation

**What to do:**
1. In `src/schemas/catchment.py`, define:
   ```python
   class CatchmentMetrics(BaseModel):
       area_ha: float
       cell_count: int
       elevation_stats: Dict[str, float]  # min, max, mean
       slope_stats: Dict[str, float]
   ```
2. In `src/catchment/metrics.py`, write `compute_metrics(mask: np.ndarray, dem: DEM, slope: np.ndarray) -> CatchmentMetrics`:
   - `cell_count = mask.sum()`
   - `area_ha = cell_count * (dem.cell_size ** 2) / 10_000` — this is exactly the formula from your HLD (`Area (ha) = contributing cells × cell area / 10,000`).
   - `elevation_stats` / `slope_stats`: mask the DEM/slope arrays with `mask`, compute `min/max/mean` via numpy (ignore nodata).
3. Cross-check function `assert_area_consistency(metrics, flow_accum_at_pour_point, cell_size)`: compare `cell_count` against the flow-accumulation value at the pour point — they should match exactly (accumulation *is* upstream cell count by construction), which is a strong internal correctness check worth keeping as an assertion or logged warning, not just a test.
4. Write `tests/unit/test_metrics.py` on the toy DEM: assert area matches hand-calculated value.

**Commit checkpoints:**
- `feat: compute catchment area and terrain statistics`
- `feat: add area-vs-accumulation cross-validation check`
- `test: validate metrics against toy DEM`

---

## Module 12 — API Layer: `POST /analyzeContour`

**What to do:**
1. In `src/api/analysis_service.py`, write the orchestrator class:
   ```python
   class AnalysisService:
       def __init__(self, terrain_source_factory): ...
       def run(self, file_bytes, filename, cell_size=None, pour_point=None) -> AnalysisResult:
           # 1. instantiate KMLTerrainSource(file_bytes)
           # 2. contours = source.extract_contours(); validate_contours(contours)
           # 3. pc = build_point_cloud(contours)
           # 4. dem = build_dem(pc, cell_size); validate_dem(dem, contours)
           # 5. dem = fill_sinks(dem); slope = compute_slope(dem)
           # 6. flow_dir = compute_flow_direction(dem)
           # 7. flow_accum = compute_flow_accumulation(flow_dir)
           # 8. candidates = find_candidates(...)
           # 9. selected = pour_point override or candidates[0]
           # 10. mask = delineate_catchment(flow_dir, selected_rc)
           # 11. polygon = mask_to_polygon(mask, dem)
           # 12. metrics = compute_metrics(mask, dem, slope)
           # 13. return AnalysisResult(candidates, selected, polygon, metrics, metadata)
   ```
   Every step here is a function you already wrote and unit-tested in Modules 2-11 — this module is pure wiring, which is why it should be quick if the earlier modules are solid.
2. In `src/schemas/response.py`, define the final `AnalysisResult` response schema (matches the JSON shape in the plan doc).
3. In `src/api/routes.py`:
   ```python
   @router.post("/analyzeContour", response_model=AnalysisResult)
   async def analyze_contour(file: UploadFile, cell_size: float | None = None):
       contents = await file.read()
       result = await run_in_threadpool(analysis_service.run, contents, file.filename, cell_size)
       return result
   ```
   (`run_in_threadpool` because your pipeline is CPU-bound sync code — don't block the async event loop.)
4. In `src/api/main.py`: create the `FastAPI()` app, include the router, mount CORS middleware if the frontend will call it directly.
5. Run locally: `uvicorn src.api.main:app --reload`, open `http://localhost:8000/docs`, manually upload `contours_1m.kml` through the Swagger UI, confirm you get a real JSON response back with non-empty catchment polygon and plausible area.

**Commit checkpoints:**
- `feat: implement AnalysisService orchestrator`
- `feat: add POST /analyzeContour endpoint`
- `feat: add response schema and threadpool offloading`

---

## Module 13 — Error Handling, Logging & Reliability Hardening

**What to do:**
1. In `src/api/error_handlers.py`, register FastAPI exception handlers:
   - `TerrainParseError` → HTTP 400 with message.
   - `InvalidGeometryError` → HTTP 422.
   - `UnsupportedFormatError` → HTTP 415.
   - Generic `Exception` fallback → HTTP 500, logged with full traceback but a generic message returned to the client (don't leak internals).
2. Set up logging in `src/config.py` or a new `src/logging_setup.py`: configure `logging` (or `structlog`) with a request-ID field, log at INFO for each pipeline stage entry/exit (e.g. "DEM built: 340x210 grid", "Catchment delineated: 12.4 ha") — this doubles as your demo narration material.
3. Add upload guards in the route: reject files over `settings.max_upload_mb` before reading fully into memory (check `Content-Length` header first); reject non-`.kml`/`.kmz` extensions immediately.
4. Add `GET /health` route returning `{"status": "ok"}` — cheap but satisfies "availability" checks and is standard practice for any deployable service.
5. Verify idempotency: run the same file through the endpoint twice, assert identical output (no hidden randomness — if you used any clustering/sorting with ties, make sure it's deterministic, e.g. sort with a stable secondary key).

**Commit checkpoints:**
- `feat: add global exception handlers`
- `feat: add structured logging across pipeline`
- `feat: add /health endpoint and upload size guards`

---

## Module 14 — Testing Suite & CI Integration

**What to do:**
1. Confirm you already have unit tests per module (Modules 2-11) — if any are missing, backfill them now.
2. Write `tests/integration/test_full_pipeline.py`:
   - Load `tests/fixtures/contours_1m.kml` as bytes.
   - Call `AnalysisService.run(...)` directly (no HTTP layer).
   - Assert: `result.catchment.area_ha > 0`, `result.catchment.elevation_stats["min"] >= min(contour elevations) - tol`, `shapely.geometry.shape(result.catchment.polygon_geojson).is_valid`.
3. Write `tests/integration/test_api.py` using FastAPI's `TestClient`:
   - `client.post("/analyzeContour", files={"file": ("contours_1m.kml", open(fixture,"rb"), "application/vnd.google-earth.kml+xml")})`
   - Assert status 200, assert JSON has expected top-level keys.
   - Also test the failure path: post `not_xml.kml`, assert 400.
4. Add `pytest-cov`: run `pytest --cov=src --cov-report=term-missing`, aim for meaningful coverage on the algorithmic modules especially (hydrology, catchment) — 100% isn't the goal, but the core logic should be covered.
5. Update `.github/workflows/ci.yml` to run `pytest --cov` and fail the build on test failure (not just lint).

**Commit checkpoints:**
- `test: add end-to-end pipeline integration test`
- `test: add API-level integration tests via TestClient`
- `ci: wire coverage reporting into CI`

---

## Module 15 — Documentation, Dockerization & Demo Prep

**What to do:**
1. Write `Dockerfile`:
   ```dockerfile
   FROM python:3.11-slim
   RUN apt-get update && apt-get install -y build-essential libgdal-dev
   WORKDIR /app
   COPY requirements.txt .
   RUN pip install -r requirements.txt
   COPY src ./src
   CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
   ```
2. Write `docker-compose.yml` exposing port 8000, mounting `.env`.
3. Build and run: `docker compose up --build`, confirm `/docs` and `/analyzeContour` work identically to local `uvicorn` run.
4. Finalize `README.md`:
   - Project description, architecture diagram (reuse the ASCII one from the plan doc or export a proper image).
   - Installation guide (venv path AND Docker path).
   - How to run tests.
   - API usage example (`curl -F "file=@contours_1m.kml" http://localhost:8000/analyzeContour`).
5. Write the submission **report** (separate doc, per the assignment):
   - GitHub repo link.
   - Working API route/URL (localhost or deployed).
   - Catchment estimation approach — condense Modules 5-11 into a readable explanation (contour → DEM interpolation → sink-fill → D8 flow direction → flow accumulation → watershed delineation → area/stats), reusing language from your HLD Section 6.
   - Demo section: screenshot of Swagger UI request/response using `contours_1m.kml`, and ideally a plotted image of the delineated catchment overlaid on the DEM.
   - API documentation: link to `/docs`, or paste the OpenAPI schema summary.
   - LLM usage citation paragraph, per the course's academic integrity policy.
6. Do a full dry run of your demo before submission: fresh clone of the repo, follow your own README from scratch, confirm nothing is missing (an env var, a fixture path, a dependency) that only worked because it was already set up on your machine.

**Commit checkpoints:**
- `docs: add README with setup and usage instructions`
- `chore: add Dockerfile and docker-compose`
- `docs: finalize submission report and architecture diagram`

---

## Cross-Module Checklist (verify before final submission)

- [ ] No hard-coded coordinates, elevations, or file-specific constants anywhere in `src/` (grep for `81.28`, `21.26`, `277`, etc. to be sure)
- [ ] `TerrainSource` interface has exactly one method other code depends on — swapping in a fake/mock implementation shouldn't require touching hydrology or catchment code
- [ ] Every geospatial computation happens in a metric CRS, not degrees
- [ ] Toy-DEM unit tests exist for D8, flow accumulation, and area computation, with hand-verifiable expected values
- [ ] `/analyzeContour` returns valid GeoJSON (validate with `shapely.geometry.shape(...).is_valid`) and sane numeric ranges on the sample file
- [ ] CI is green end-to-end (lint + unit + integration)
- [ ] `docker compose up --build` works on a machine that has never had the venv set up
- [ ] README + report are enough for someone else to run and reproduce your demo cold