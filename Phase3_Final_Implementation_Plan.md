# Phase 3 (Final) Implementation Plan
### AI-based Village Pond Planning System

## TIER 1

### Module 1 — Land Suitability Hardening
**Goal:** Requirement #3 currently only excludes existing water. Close the gap: exclude built-up
land, and stop recommending dam sites on impractically steep ground.

**What to do:**
1. Extend `src/external/water/water_source.py`'s OSM parsing (or add a sibling function) to also
   pull `building=*` and `landuse=residential` ways from the same OSM XML response you're already
   fetching in `water_exclusion.py` — **no new external call needed**, you already have the raw XML
   for the bbox, just parse more tag types out of it.
2. Generalize `build_water_exclusion_mask` into `build_land_exclusion_mask` (or keep water masking
   separate and add a second `built_up_mask` — either is fine, pick one and be consistent) that
   returns a combined exclusion boolean grid: `water_mask | built_up_mask`.
3. In `candidates.py`'s Step C filtering loop, add: reject a bowl if the **rim/dam-site cells**
   (not just the bowl interior) have slope above `settings.max_dam_site_slope_deg` — a new config
   value, e.g. `20.0`. This is a real engineering constraint (you can't practically build an
   earthen dam wall on very steep ground) and directly satisfies "suitable for excavation," not
   just "hydrologically plausible."
4. Add `land_exclusion_source: str` to the response metadata (mirrors your existing
   `water_exclusion.source` pattern) so it's clear in the API contract which exclusions were
   applied.

**Why this order:** everything downstream (rainfall, runoff, pond design) is computed *for* a
selected candidate — you want the candidate selection itself to be correct before you build more
on top of a location that might get relocated by a suitability fix.

---

### Module 2 — Rainfall Data Integration

**Goal:** Requirement #5 — query historical rainfall for the selected location.

**What to do:**
1. Create `src/external/rainfall/open_meteo_client.py`, structured **identically** to
   `osm_client.py` — synchronous `httpx.Client`, same `tenacity` retry decorator, same
   `XUnavailableError` exception pattern:
   ```python
   class OpenMeteoUnavailableError(Exception): ...

   class OpenMeteoClient:
       def __init__(self, endpoint: str, timeout_s: int): ...
       @retry(stop=stop_after_attempt(3), wait=wait_exponential(...), ...)
       def _fetch(self, url: str) -> str: ...
       def get_daily_rainfall(self, lat, lon, start_date, end_date) -> dict:
           # https://archive-api.open-meteo.com/v1/archive
           # ?latitude=..&longitude=..&start_date=..&end_date=..&daily=precipitation_sum
   ```
   No API key required for Open-Meteo's historical archive endpoint.
2. Create `src/hydrology/rainfall_stats.py`: `aggregate_rainfall(daily_json) -> RainfallStats`
   — monthly totals, annual average across the queried years (5-10 years is plenty for a
   village-scale estimate), wet/dry season split.
3. Cache exactly like `water_exclusion.py` does — same in-memory `{bbox_key: (response, ts)}`
   pattern, same TTL config approach (`rainfall_cache_ttl_s`). Copy the pattern deliberately; two
   near-identical caching implementations is fine and keeps the codebase easy to explain in
   the demo, which matters more here than DRY-ing it into an abstraction under time pressure.
4. Add `RainfallStats` to `src/schemas/response.py`, wire into `AnalysisResult`.
5. Call it from `analysis_service.py` right after `selected = candidates[0]` — you need the
   selected point's lat/lon before you can query rainfall for it.

**Config additions** (`src/config.py`, same style as existing):
```python
open_meteo_base_url: str = "https://archive-api.open-meteo.com/v1/archive"
open_meteo_timeout_s: int = 15
rainfall_history_years: int = 10
rainfall_cache_ttl_s: int = 86400
```

---

### Module 3 — Runoff Estimation

**Goal:** Requirement #6 — combine catchment area (already computed) with rainfall (Module 2)
into a runoff volume.

**What to do:**
1. `src/hydrology/runoff.py`:
   ```python
   def estimate_runoff(catchment_area_ha: float, rainfall_stats: RainfallStats,
                        runoff_coefficient: float) -> RunoffEstimate:
       area_m2 = catchment_area_ha * 10_000
       annual_m3 = (rainfall_stats.annual_avg_mm / 1000) * area_m2 * runoff_coefficient
       ...
   ```
   This is the rational method — exactly the formula from your own HLD Section 6.3.
2. `src/hydrology/runoff_coefficients.py`: a small lookup table. Simplest defensible version
   given time constraints: fixed default `C = 0.4` (typical for mixed rural terrain), with an
   optional override if Module 1's land classification tells you the catchment is mostly
   built-up (`C ≈ 0.6-0.7`) vs vegetated (`C ≈ 0.2-0.3`). Don't over-engineer this under time
   pressure — a documented, defensible default beats a fragile multi-class model you can't fully
   explain in the demo.
3. Unit test with a hand-computed example — this is pure arithmetic and should take five minutes
   to get right and prove correct.

---

### Module 4 — Pond Dimensioning & Storage Capacity (and fix the README/code mismatch)

**Goal:** Requirement #7. Also: resolve the scoring-formula inconsistency flagged above.

**What to do:**
1. **Decide and fix the scoring mismatch first** — pick one:
   - (a) Update the README to match the code (`score = catchment_cells / total_cells`), and add
     one sentence explaining that storage volume is reported separately, not blended into ranking.
   - (b) Actually implement the weighted formula the README describes, if you have time to
     re-verify it doesn't break anything from the multi-round candidate-selection correctness work.
   - **Given time pressure, (a) is the safer choice** — it's a documentation fix, not a logic
     change, and you already know the current scoring logic is correct because you tested it
     extensively.
2. `src/catchment/pond_design.py`:
   ```python
   def recommend_pond_design(runoff_estimate, topographic_storage_m3: float,
                              catchment_area_ha: float) -> PondDesign:
       target_storage_m3 = min(
           runoff_estimate.annual_m3 * settings.target_capture_fraction,
           topographic_storage_m3,  # can't store more than the bowl physically holds
       )
       depth_m = clamp(some_default_or_derived_depth, settings.min_depth_m, settings.max_depth_m)
       # back-solve footprint from target_storage_m3 / depth_m, assuming simple rectangular
       # or trapezoidal cross-section
       ...
   ```
   The `min()` against your **already-computed** `estimated_storage_m3` (topographic fill volume,
   which you built in Phase 2) is the key move — it means Module 4 isn't starting from scratch,
   it's reconciling a number you already have with a new hydrological supply number, which is
   both correct engineering practice and less new code to write and test under deadline pressure.
3. Config: `target_capture_fraction: float = 0.4`, `min_pond_depth_m: float = 1.0`,
   `max_pond_depth_m: float = 4.0`.
4. Add `PondDesign` to the response schema.

---

### Module 5 — Unified Response Assembly

**Goal:** Requirement #8 — wire Modules 1-4 into the existing `analysis_service.run()` so
`POST /analyzeContour` returns everything in one call.

**What to do:**
1. Extend `AnalysisResult` (in `src/schemas/response.py`) with `rainfall: RainfallStats`,
   `runoff: RunoffEstimate`, `pond_design: PondDesign`.
2. In `analysis_service.py`, after `selected = candidates[0]` and before the watershed
   delineation loop, insert: query rainfall → estimate runoff → recommend pond design. This is
   pure sequential composition, same style as everything already in that file — no architecture
   change, just three more steps in the existing pipeline.
3. Update `tests/integration/test_full_pipeline.py` and `test_api.py` to assert the new fields
   are present and non-null on a real run against `contours_1m.kml`.

**This module is what makes the assignment's requirement #8 ("overlay all results") literally
true** — one API call, one response, everything the frontend needs to render.

---

## TIER 2 — Needed for a complete, credible submission

### Module 6 — Frontend (map + upload + results overlay)

**Goal:** You need *a* frontend — the assignment requires one, and it's graded (5 marks
frontend/visualization, but also affects "system functionality" credibility in the demo). Given
time constraints, build the smallest thing that's real, not a polished product.

**What to do:**
1. Single-page app — plain HTML/JS + Leaflet is faster to get working than a full React build
   pipeline under time pressure, and Leaflet is exactly what your own HLD specified. Don't reach
   for a bigger stack than you need right now.
2. One file, `frontend/index.html`:
   - A file upload input for `.kml`/`.kmz`.
   - A Leaflet map with an OSM tile layer as the base (this alone satisfies requirement #1's
     spirit — "display imagery for the area" — even without a dedicated satellite tile
     integration; say so plainly in your report rather than overclaiming a separate imagery
     pipeline you didn't build).
   - On upload: `POST` the file to `/analyzeContour`, show a loading spinner, then render:
     - The catchment polygon (`GeoJSON` layer from the response).
     - Markers for each candidate location, top one highlighted.
     - A results panel: catchment area, rainfall stats, runoff volume, recommended pond
       dimensions — all pulled directly from the one JSON response Module 5 assembled.
3. **CORS**: add `CORSMiddleware` to `src/api/main.py` (currently absent — check and add if
   missing) so the frontend can call the API from a different origin/port during dev.
4. Serve the frontend as static files from FastAPI itself (`StaticFiles` mount) — avoids needing
   a separate frontend server/deployment under time pressure. One process, one Docker container,
   simplest possible demo setup.

---

### Module 7 — Reliability Hardening for the New External Calls

**Goal:** You now have two live external dependencies (OSM, Open-Meteo) instead of one. Make sure
one being slow/down doesn't take down the whole `/analyzeContour` call.

**What to do:**
1. Both `OsmApiClient` and the new `OpenMeteoClient` already retry via `tenacity` — confirm both
   have a sane max total wait (they do, per the existing pattern: `wait_exponential(min=2, max=10)`
   × 3 attempts ≈ 20s worst case each).
2. In `analysis_service.py`, wrap the rainfall call in the same try/except-and-degrade pattern
   `water_exclusion.py` already uses for OSM: on `OpenMeteoUnavailableError`, don't crash the
   whole analysis — return `rainfall: None` / a `rainfall_data_available: false` flag, and let
   runoff/pond-design degrade gracefully (e.g. runoff becomes `None` too, or falls back to a
   documented regional-average rainfall constant as a last resort).
3. This is genuinely quick to add **because you're copying a pattern you already built and
   trust**, not inventing new reliability logic under deadline pressure.

---

### Module 8 — Persistence

**Goal:** `/api/results/{id}` and a village registry, matching your HLD's PostgreSQL/PostGIS choice.


**If you do have time:**
1. `docker-compose.yml`: add a `postgres` service (you don't have one yet — currently just the
   API container).
2. `src/db/models.py` — SQLModel is faster to stand up than SQLAlchemy + separate Pydantic
   schemas under time pressure, since it's both in one: `AnalysisRun(id, request_filename,
   result_json, created_at)`. Don't build a full relational schema (separate rainfall/runoff/pond
   tables) right now — one table with the full `AnalysisResult` stored as JSONB is a legitimate,
   fast, defensible choice for a v1, and PostgreSQL's JSONB is a real, citable design decision,
   not a hack.
3. `GET /api/results/{id}` — fetch and return the stored JSON.
4. Save the result at the end of `analysis_service.run()`, return the new `id` in the response.

---

## TIER 3 — Document as architecture, build only if genuinely ahead of schedule

### Module 9 — Village Registry & Search

`GET /api/village/search?q=`, `GET /api/village/{id}` — CRUD over a small seeded `Village` table
(name, boundary/centroid). Only worth building if Module 8 (persistence) is already done and you
have spare time. Otherwise: the current "upload a KML directly" flow already satisfies the
assignment's core ask; village-by-name search is a UX nicety, not a functional requirement gap.

### Module 10 — Dedicated Satellite Imagery Metadata Endpoint

A `GET /api/imagery?bbox=` returning a tile URL template (Esri World Imagery or similar) instead
of relying on the OSM base layer in Module 6. Only worth doing if you want imagery visually
distinct from the OSM-derived water/exclusion layers already on the map — genuinely optional,
the base-map layer in Module 6 already satisfies the letter of requirement #1.

### Module 11 — Manual Pour-Point Override UI

Let the user click the map to override the auto-selected candidate, surfacing your existing
`on_or_near_mapped_water` field as a warning. Nice interaction, not required for the core
functional requirements.

---

## Final Assembly (do this regardless of which tiers you reached)

### Module 12 — Documentation & Report

**What to do, in priority order if time is short:**
1. Update the README's algorithm section to match whatever you actually shipped (this is
   mandatory, not optional — an inconsistent README is worse than a short one, since you'll be
   asked to explain your algorithm live).
2. Write the submission report: GitHub link, working API URL, methodology (you can lift heavily
   from your own README's existing algorithm walkthrough, which is already detailed and accurate
   for Phase 2 — extend it with Modules 1-5's rainfall/runoff/pond-design explanation).
3. **State plainly which Tier 2/3 items you built vs. documented-as-future-work.** Given the
   course's explicit instruction that you must be able to explain everything submitted, an
   honest "we architected persistence but didn't have time to wire it in; here's the schema we'd
   use" is a strictly better answer under questioning than an overreaching claim.
4. LLM usage citation, per course policy — you have an unusually detailed, real record of this
   from the correctness-review conversation; a brief honest summary of that process (multiple
   rounds of AI-assisted review catching real bugs, each verified against actual code before
   accepting) is genuinely good material for this section, not something to downplay.
5. Demo screenshots: upload flow, map with catchment + candidates, results panel.

---
