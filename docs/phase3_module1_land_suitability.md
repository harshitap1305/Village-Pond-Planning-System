# Phase 3 Module 1: Land Suitability Hardening

## Overview
This module enhances the pond candidate selection process by excluding locations that are structurally or legally incompatible with pond excavation, specifically built-up land and excessively steep terrain at the dam wall site.

The module implements three key constraints based on engineering principles (such as IS 12169) and practical requirements:
1. **Bowl Footprint Built-up Veto:** Hard veto if the proposed pond footprint (depression area) overlaps with mapped buildings or certain land-uses (residential, commercial, industrial, construction, cemetery).
2. **Upstream Catchment Preservation:** Built-up land located upstream from the pond in the catchment area is explicitly allowed (and even favorable due to increased runoff). The land mask is purposely NOT applied to the upstream catchment.
3. **Rim Slope Constraint:** The dam wall (boundary ring of the depression) must not be impractically steep. If the maximum slope around the boundary exceeds a safe limit for earthen embankments (default 20°), the candidate is rejected. The interior of the bowl can have any slope.

## Architecture & Data Flow

### 1. Configuration & Schemas
- `src/config.py`: Introduces `max_dam_site_slope_deg` (20.0°), `builtup_buffer_margin_m` (10.0m), and `land_cache_ttl_s`.
- `src/schemas/water.py` & `src/schemas/response.py`: Define `LandMaskResult` and `LandExclusionMetadata` to report exclusion metrics back to the user.

### 2. OSM Built-up Land Parsing
- `src/external/water/water_source.py`: Extended with `build_builtup_geometries()`.
- Reuses the *exact same OSM XML blob* downloaded by the water exclusion module. No new network requests are made.
- Identifies `building=*` (excluding negations like `no` and `false`) and specific `landuse=*` polygon tags.

### 3. Land Exclusion Orchestrator
- `src/catchment/land_exclusion.py`: Orchestrates the parsing, reprojection to metric CRS, buffering, and rasterization of built-up polygons onto the DEM grid, producing a boolean mask.
- Fails open (returns an all-False mask) if OSM parsing or rasterization fails.

### 4. Candidate Filtering
- `src/catchment/candidates.py`: `find_candidates()` is updated to accept `land_mask` and `slope_deg` arrays.
- Implements the critical spatial logic during Step C (filtering): checks for mask overlap *only* against `bowl_mask`, and calculates maximum slope *only* on the boundary ring (`binary_dilation(bowl_mask) & ~bowl_mask`).

### 5. API Layer
- `src/api/analysis_service.py`: Wires up `build_land_exclusion_mask()` using the cached OSM XML.
- Passes the mask and slope arrays to `find_candidates`.
- Populates the final response with `LandExclusionMetadata`.

## Testing
- Unit tests in `tests/unit/test_land_exclusion.py` cover OSM XML parsing, built-up rasterization, and thoroughly prove the spatial distinction of the vetoes (e.g., steep interior is allowed, steep rim is vetoed; built-up catchment is allowed, built-up bowl is vetoed).
- Integration tests in `tests/integration/test_full_pipeline.py` ensure the full pipeline correctly surfaces land exclusion metadata.
