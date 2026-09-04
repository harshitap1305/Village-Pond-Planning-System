# Module 2 — Rainfall Data Integration

## Overview
Module 2 is responsible for retrieving historical daily rainfall statistics for the selected village pond site. It uses a **dual-source, fail-open architecture**:
1. **Primary**: Open-Meteo ERA5-Land (ECMWF reanalysis, ~9 km resolution). Free, no API key, fast (~9 ms response time).
2. **Fallback**: NASA POWER MERRA-2 (~50 km resolution). Used automatically if Open-Meteo is unavailable.
3. **Fail-Open**: If both sources fail, the pipeline proceeds normally with a `null` rainfall object.

## Design Decisions
- **10-Year Baseline**: The pipeline aggregates data over the past 10 calendar years, which is the standard hydrological baseline for low-dam capacity fixing in India (IS 5477 Part 1).
- **Wet vs Dry Season**: We classify June–September (JJAS) as the "wet season" (South-West Monsoon) and October–May as the "dry season". This is crucial for evaluating runoff potential, as Indian village ponds fill almost entirely during the monsoon.
- **In-Memory Caching**: A module-level TTL cache (`rainfall_cache_ttl_s = 86400` seconds) ensures that nearby queries (rounded to 2 decimal places, ~1.1 km) share the same HTTP response, minimizing API strain.

## Schema Additions

### `RainfallStats`
Appended to the final API response (`AnalysisResult`):
```json
{
  "rainfall": {
    "annual_avg_mm": 1100.5,
    "monthly_avg_mm": [10.1, 15.2, 20.3, ...],
    "wet_season_avg_mm": 950.0,
    "dry_season_avg_mm": 150.5,
    "wettest_month": 7,
    "driest_month": 1,
    "years_of_data": 10,
    "source": "open_meteo_era5_land",
    "data_start_year": 2014,
    "data_end_year": 2023
  }
}
```

## Internal Architecture
- `src/config.py`: Timeout parameters, base URLs, and cache TTL values.
- `src/external/rainfall/open_meteo_client.py`: HTTP client using `httpx` with `tenacity` exponential backoff.
- `src/external/rainfall/nasa_power_client.py`: HTTP client using `httpx` with `tenacity` exponential backoff.
- `src/hydrology/rainfall_stats.py`: Pure-function data parsers (`aggregate_open_meteo`, `aggregate_nasa_power`) that group daily data points into (year, month) buckets.
- `src/catchment/rainfall_service.py`: Orchestrator containing the cache logic and try/except fallback block.

## Integration
Called at Step 7b of the main `analysis_service.py` pipeline, immediately after the best candidate depression is selected, so it queries the exact lat/lon of the chosen site.
