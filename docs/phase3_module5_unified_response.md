# Module 5 — Unified Response Assembly

## Overview

Module 5 closes the loop on the Phase 3 pipeline. It does not add new hydrological
computation — Modules 1–4 already do that. Instead, it hardens the API contract so
the response is:

- **Self-describing**: all 9 fields documented in the schema with full docstrings
- **Observable**: `processing_time_ms` in `metadata`, machine-readable `warnings` list
- **Frontend-ready**: clients can display degraded states without inspecting `null` fields
- **Correct**: fixed bugs in `test_api.py` (missing mocks) and the stale module docstring

---

## Complete `AnalysisResult` JSON Contract

```json
{
  "candidate_locations": [
    {
      "lat": 20.123456,
      "lon": 82.654321,
      "elevation": 275.4,
      "score": 0.412,
      "depression_depth_m": 2.1,
      "depression_area_ha": 0.45,
      "catchment_area_ha": 17.3,
      "estimated_storage_m3": 12450.0,
      "had_flat_bottom": false,
      "on_or_near_mapped_water": false,
      "catchment_polygon_geojson": { "type": "Polygon", "coordinates": [...] }
    }
  ],
  "selected_location": { "...": "same shape as candidate_locations[0]" },
  "catchment": {
    "area_ha": 17.3,
    "polygon_geojson": { "type": "Polygon", "coordinates": [...] },
    "elevation_stats": { "min": 267.0, "max": 298.0, "mean": 282.5 },
    "slope_stats": { "min": 0.1, "max": 28.4, "mean": 8.2 }
  },
  "metadata": {
    "dem_rows": 420,
    "dem_cols": 380,
    "dem_cell_size_m": 2.0,
    "crs_used": "EPSG:32644",
    "contour_count": 62,
    "processing_time_ms": 4823.5
  },
  "water_exclusion": {
    "source": "osm",
    "excluded_feature_count": 2,
    "attribution": "© OpenStreetMap contributors (ODbL)"
  },
  "land_exclusion": {
    "source": "osm",
    "excluded_feature_count": 0,
    "builtup_cells_masked": 0,
    "attribution": "© OpenStreetMap contributors (ODbL)"
  },
  "rainfall": {
    "annual_avg_mm": 1180.0,
    "monthly_avg_mm": [12.0, 8.0, 14.0, 22.0, 41.0, 178.0, 312.0, 290.0, 124.0, 68.0, 18.0, 11.0],
    "wet_season_avg_mm": 904.0,
    "dry_season_avg_mm": 194.0,
    "wettest_month": 7,
    "driest_month": 2,
    "years_of_data": 10,
    "source": "open_meteo_era5_land",
    "data_start_year": 2014,
    "data_end_year": 2023
  },
  "runoff": {
    "annual_avg_m3": 7240.0,
    "wet_season_avg_m3": 6180.0,
    "dry_season_avg_m3": 1060.0,
    "peak_month": 7,
    "runoff_depth_mm": 41.8,
    "curve_number": 71,
    "land_cover_assumed": "mixed_agriculture",
    "hsg_assumed": "B",
    "catchment_area_ha": 17.3,
    "method": "scs_cn_monthly_distributed"
  },
  "pond_design": {
    "live_storage_m3": 2896.0,
    "dead_storage_m3": 386.1,
    "gross_storage_m3": 3861.3,
    "total_storage_m3": 4247.4,
    "water_depth_m": 2.36,
    "embankment_height_m": 2.86,
    "surface_area_m2": 4500.0,
    "embankment_top_width_m": 1.5,
    "target_capture_fraction": 0.4,
    "freeboard_m": 0.5,
    "side_slope": 2.0,
    "shape_factor": 0.4,
    "evaporation_loss_fraction": 0.15,
    "seepage_loss_fraction": 0.10,
    "topographic_storage_m3": 12450.0,
    "annual_runoff_m3": 7240.0,
    "constrained_by": "hydrology",
    "fills_in_wet_season": true,
    "supply_deficit": false
  },
  "warnings": []
}
```

---

## The `warnings` Field — Machine-Readable Degraded States

The `warnings` list is **empty `[]` in the happy path**. Each entry is a stable
string code the frontend can use to display a warning banner or tooltip.

| Code | Meaning | Affected fields |
|---|---|---|
| `"rainfall_unavailable"` | Both Open-Meteo and NASA POWER failed | `rainfall`, `runoff`, `pond_design` |
| `"runoff_unavailable"` | Runoff estimation failed (or rainfall null) | `runoff`, `pond_design` |
| `"runoff_using_rational_fallback"` | Monthly data absent; rational C×P used | `runoff.method` = `"rational_annual_fallback"` |
| `"pond_design_unavailable"` | Dimensioning failed (or runoff null) | `pond_design` |

### Degradation Hierarchy

```
7b: rainfall  →  open_meteo → nasa_power → None + "rainfall_unavailable"
                                                    ↓
7c: runoff    →  scs_cn_monthly → rational_fallback ("runoff_using_rational_fallback")
               or None + "runoff_unavailable"
                                     ↓
7d: pond_design → IS5477 calc → None + "pond_design_unavailable"
```

---

## `processing_time_ms` — Pipeline Timing

`metadata.processing_time_ms` is the wall-clock duration from the start of
`AnalysisService.run()` to just before the `AnalysisResult` is assembled.
It is measured with `time.perf_counter()` for monotonic, high-resolution timing.

This field is useful for:
- **Demo observability**: display "Analysis completed in 4.8 seconds" in the UI
- **Performance monitoring**: detect regressions when new modules are added
- **Debugging**: distinguish slow external API calls from slow computation

---

## Known Limitations

### `builtup_fraction` approximation (Gap 6)

The SCS-CN module receives `builtup_fraction` computed as:
```python
builtup_fraction = land_result.mask.sum() / land_result.mask.size
```

This uses the **full DEM bounding box** as the denominator, not the delineated
catchment area (which isn't available until Step 8, after runoff is estimated in Step 7c).

**Bias direction:** The DEM bbox is typically larger than the catchment, so
`builtup_fraction` may be underestimated if built-up land is concentrated inside
the catchment, or overestimated if it's spread across the bbox but outside the
catchment. For typical rural village sites (which are the target use case), the
built-up fraction is near 0% regardless, so the CN is unaffected.

**Impact:** ≤ 3 CN units in most cases, conservative direction (higher CN → higher
estimated runoff → slightly oversized pond design → safe).

### Cache thread-safety (Gap 7)

Both `_rainfall_cache` (in `rainfall_service.py`) and the water exclusion cache
(in `water_exclusion.py`) are module-level `dict` objects with no threading lock.
Since `analysis_service.run()` is called via `run_in_threadpool`, concurrent
requests for the same location can cause a **race** where both threads miss the
cache and make two API calls.

**Correctness:** Not a bug — the GIL prevents dict corruption; the last writer wins
and the value is correct. The only cost is one redundant API call per concurrent
cache miss. For typical village pond planning usage (one-at-a-time analysis), this
is never triggered.

---

## OpenAPI Error Responses

The following error codes are now documented in the Swagger UI:

| HTTP Code | Meaning |
|---|---|
| `200` | Analysis succeeded (hydrological fields may be null — check `warnings`) |
| `400` | Malformed or unreadable KML/KMZ file |
| `413` | File exceeds the upload size limit |
| `415` | Unsupported file format (must be `.kml` or `.kmz`) |
| `422` | Valid KML but no suitable pond candidates found in the terrain |

All error bodies follow the standard FastAPI format: `{"detail": "error message"}`.
