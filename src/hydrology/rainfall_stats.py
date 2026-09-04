"""
Rainfall statistics aggregation from raw API responses.

Public interface:
    aggregate_open_meteo(raw_json)  -> RainfallStats
    aggregate_nasa_power(raw_json)  -> RainfallStats

Both functions are pure (no I/O) and operate on raw JSON strings returned
by their respective clients.  They produce the same RainfallStats schema,
so the rest of the pipeline is agnostic to which source was used.

Aggregation method:
  1. Parse daily time-series values, skipping nulls / fill-values.
  2. Group by calendar year and calendar month.
  3. Per-month totals: sum daily values within each (year, month) bucket.
  4. Monthly averages: mean of per-month totals across all years present.
  5. Annual average: mean of per-year totals across all years.
  6. Wet season (Jun-Sep): mean of those 4-month sums per year.
  7. Dry season (Oct-May): mean of remaining 8-month sum per year.

Indian monsoon context: JJAS (June-July-August-September) is the primary
monsoon season for most of India; Oct-Nov is the northeast monsoon season
for south-east India. We use Jun-Sep as the wet season threshold because
it applies universally to village sites across the country.
"""

import json
import logging
from collections import defaultdict

from pydantic import BaseModel

_log = logging.getLogger(__name__)

# ── Season definitions ────────────────────────────────────────────────────────
# Wet season: South-West Monsoon (JJAS) — primary runoff-generating period.
_WET_MONTHS = {6, 7, 8, 9}  # June, July, August, September
# Dry season: everything else (pre-monsoon + retreating monsoon + winter)
_DRY_MONTHS = {1, 2, 3, 4, 5, 10, 11, 12}

# NASA POWER fill value for missing / bad data
_NASA_FILL_VALUE = -999.0


class RainfallStats(BaseModel):
    """
    Aggregated historical rainfall statistics for a point location.

    Attributes:
        annual_avg_mm:      Mean annual precipitation (mm) over queried years.
        monthly_avg_mm:     12-element list (Jan=index 0 … Dec=index 11) of
                            mean monthly precipitation totals (mm).
        wet_season_avg_mm:  Mean June–September total per year (mm).
        dry_season_avg_mm:  Mean October–May total per year (mm).
        wettest_month:      Calendar month (1-12) with highest mean precipitation.
        driest_month:       Calendar month (1-12) with lowest mean precipitation.
        years_of_data:      Number of calendar years included in averages.
        source:             One of ``"open_meteo_era5_land"`` | ``"nasa_power_merra2"``.
        data_start_year:    First calendar year included.
        data_end_year:      Last calendar year included.
    """

    annual_avg_mm: float
    monthly_avg_mm: list[float]  # 12 values, Jan=0 … Dec=11
    wet_season_avg_mm: float
    dry_season_avg_mm: float
    wettest_month: int  # 1–12
    driest_month: int  # 1–12
    years_of_data: int
    source: str
    data_start_year: int
    data_end_year: int


def _aggregate_daily_series(
    dated_values: list[tuple[int, int, float]],  # (year, month, value_mm)
    source: str,
) -> RainfallStats:
    """
    Core aggregation logic, shared by both parsers.

    Args:
        dated_values: List of (year, month, daily_mm) triples.
                      Nulls and fill-values MUST be excluded before calling.
        source:       Source identifier string for the result schema.

    Returns:
        RainfallStats, or raises ValueError if dated_values is empty.
    """
    if not dated_values:
        raise ValueError("No valid rainfall data points to aggregate")

    # Group into (year, month) buckets, summing daily values
    monthly_sums: dict[tuple[int, int], float] = defaultdict(float)
    for year, month, value in dated_values:
        monthly_sums[(year, month)] += value

    years_present = sorted({y for y, _m in monthly_sums})
    num_years = len(years_present)

    # 12-element per-year bucket for wet/dry/annual sums
    annual_totals: dict[int, float] = defaultdict(float)
    wet_season_totals: dict[int, float] = defaultdict(float)
    dry_season_totals: dict[int, float] = defaultdict(float)
    month_across_years: dict[int, list[float]] = defaultdict(list)

    for (year, month), total in monthly_sums.items():
        annual_totals[year] += total
        month_across_years[month].append(total)
        if month in _WET_MONTHS:
            wet_season_totals[year] += total
        else:
            dry_season_totals[year] += total

    annual_avg = sum(annual_totals.values()) / num_years
    wet_avg = sum(wet_season_totals.values()) / num_years
    dry_avg = sum(dry_season_totals.values()) / num_years

    # Monthly averages: 12-element list Jan=0 … Dec=11
    monthly_avg_mm = []
    for m in range(1, 13):
        vals = month_across_years.get(m, [])
        monthly_avg_mm.append(sum(vals) / len(vals) if vals else 0.0)

    wettest = int(monthly_avg_mm.index(max(monthly_avg_mm))) + 1
    driest = int(monthly_avg_mm.index(min(monthly_avg_mm))) + 1

    return RainfallStats(
        annual_avg_mm=round(annual_avg, 1),
        monthly_avg_mm=[round(v, 1) for v in monthly_avg_mm],
        wet_season_avg_mm=round(wet_avg, 1),
        dry_season_avg_mm=round(dry_avg, 1),
        wettest_month=wettest,
        driest_month=driest,
        years_of_data=num_years,
        source=source,
        data_start_year=years_present[0],
        data_end_year=years_present[-1],
    )


def aggregate_open_meteo(raw_json: str) -> RainfallStats:
    """
    Parse Open-Meteo archive response JSON and return RainfallStats.

    Response format::

        {
            "daily": {
                "time": ["2015-01-01", ...],
                "precipitation_sum": [0.0, null, 3.5, ...]
            }
        }

    Null values are skipped (common at the very start of ERA5-Land records).

    Args:
        raw_json: Raw string returned by OpenMeteoClient.get_daily_rainfall().

    Returns:
        RainfallStats with source="open_meteo_era5_land".

    Raises:
        ValueError: If the JSON has no valid daily precipitation values.
        json.JSONDecodeError: If raw_json is not valid JSON.
    """
    data = json.loads(raw_json)
    daily = data.get("daily", {})
    times = daily.get("time", [])
    values = daily.get("precipitation_sum", [])

    dated: list[tuple[int, int, float]] = []
    for date_str, val in zip(times, values):
        if val is None:
            continue
        try:
            year = int(date_str[:4])
            month = int(date_str[5:7])
        except (ValueError, IndexError):
            continue
        dated.append((year, month, float(val)))

    _log.debug("Open-Meteo: %d valid daily values parsed", len(dated))
    return _aggregate_daily_series(dated, source="open_meteo_era5_land")


def aggregate_nasa_power(raw_json: str) -> RainfallStats:
    """
    Parse NASA POWER API response JSON and return RainfallStats.

    Response format::

        {
            "properties": {
                "parameter": {
                    "PRECTOTCORR": {
                        "20230601": 0.0,
                        "20230602": 1.44,
                        ...
                    }
                }
            }
        }

    Fill value is -999.0 (NASA POWER convention for missing data).

    Args:
        raw_json: Raw string returned by NasaPowerClient.get_daily_rainfall().

    Returns:
        RainfallStats with source="nasa_power_merra2".

    Raises:
        ValueError: If the JSON has no valid daily precipitation values.
        json.JSONDecodeError: If raw_json is not valid JSON.
    """
    data = json.loads(raw_json)
    prectot = data.get("properties", {}).get("parameter", {}).get("PRECTOTCORR", {})

    dated: list[tuple[int, int, float]] = []
    for date_key, val in prectot.items():
        if val is None or float(val) <= _NASA_FILL_VALUE:
            continue
        try:
            year = int(date_key[:4])
            month = int(date_key[4:6])
        except (ValueError, IndexError):
            continue
        dated.append((year, month, float(val)))

    _log.debug("NASA POWER: %d valid daily values parsed", len(dated))
    return _aggregate_daily_series(dated, source="nasa_power_merra2")
