"""
Orchestrates historical rainfall data retrieval for a selected pond location.

Public interface: :func:`build_rainfall_stats`.

Call chain:
  1. Check in-memory cache keyed by (round(lat,2), round(lon,2), start_year, end_year).
  2. Try Open-Meteo ERA5-Land archive (primary, ~9 km, no API key).
  3. On OpenMeteoUnavailableError → try NASA POWER MERRA-2 (fallback, ~50 km).
  4. On both failures → return None (fail-open; pipeline continues without rainfall).
  5. Parse raw JSON → RainfallStats via rainfall_stats aggregators.
  6. Cache for rainfall_cache_ttl_s seconds.

Cache key uses 2 decimal places (~1.1 km rounding), so nearby analysis runs
within the same grid cell share the same cached result — acceptable given
the resolution of both reanalysis products (9–50 km).

This module is called AFTER the candidate is selected so we have the
exact lat/lon of the winning pond site.
"""

import logging
import time
from datetime import date

from src.external.rainfall.nasa_power_client import (
    NasaPowerClient,
    NasaPowerUnavailableError,
)
from src.external.rainfall.open_meteo_client import (
    OpenMeteoClient,
    OpenMeteoUnavailableError,
)
from src.hydrology.rainfall_stats import (
    RainfallStats,
    aggregate_nasa_power,
    aggregate_open_meteo,
)

_log = logging.getLogger(__name__)

# In-memory cache: {(lat2dp, lon2dp, start_year, end_year): (RainfallStats, ts)}
_rainfall_cache: dict[tuple, tuple[RainfallStats, float]] = {}


def _cache_key(lat: float, lon: float, start_year: int, end_year: int) -> tuple:
    """Round to 2 dp (~1.1 km) so nearby calls share the same entry."""
    return (round(lat, 2), round(lon, 2), start_year, end_year)


def build_rainfall_stats(
    lat: float,
    lon: float,
    settings,
) -> RainfallStats | None:
    """
    Retrieve and aggregate historical rainfall stats for the selected pond site.

    Uses Open-Meteo ERA5-Land as primary source; automatically falls back to
    NASA POWER MERRA-2 if Open-Meteo is unavailable. Returns None if both
    sources fail — the pipeline continues without a crash (fail-open).

    Args:
        lat:      WGS84 latitude of the selected pond candidate.
        lon:      WGS84 longitude of the selected pond candidate.
        settings: The global Settings instance.

    Returns:
        :class:`RainfallStats` or None if both APIs are unavailable.
    """
    this_year = date.today().year
    end_year = this_year - 1  # last complete calendar year
    start_year = end_year - settings.rainfall_history_years + 1
    start_date = f"{start_year}-01-01"
    end_date = f"{end_year}-12-31"

    key = _cache_key(lat, lon, start_year, end_year)
    now = time.monotonic()

    # ── 1. Cache lookup ───────────────────────────────────────────────────────
    cached = _rainfall_cache.get(key)
    if cached is not None:
        stats, ts = cached
        if now - ts < settings.rainfall_cache_ttl_s:
            _log.info(
                "Rainfall cache hit for (%.2f, %.2f) %d-%d",
                lat,
                lon,
                start_year,
                end_year,
            )
            return stats
        _log.info("Rainfall cache expired for (%.2f, %.2f) — re-querying", lat, lon)

    # ── 2. Try Open-Meteo (primary) ───────────────────────────────────────────
    try:
        client = OpenMeteoClient(
            endpoint=settings.open_meteo_base_url,
            timeout_s=settings.open_meteo_timeout_s,
        )
        _log.info(
            "Querying Open-Meteo ERA5-Land for (%.4f, %.4f) %s → %s",
            lat,
            lon,
            start_date,
            end_date,
        )
        raw_json = client.get_daily_rainfall(lat, lon, start_date, end_date)
        stats = aggregate_open_meteo(raw_json)
        _log.info(
            "Rainfall (Open-Meteo ERA5-Land): annual_avg=%.1f mm, "
            "wet_season=%.1f mm, years=%d",
            stats.annual_avg_mm,
            stats.wet_season_avg_mm,
            stats.years_of_data,
        )
        _rainfall_cache[key] = (stats, now)
        return stats

    except (OpenMeteoUnavailableError, ValueError, Exception) as exc:
        _log.warning(
            "Open-Meteo unavailable or parse failed (%s) — "
            "falling back to NASA POWER MERRA-2.",
            exc,
        )

    # ── 3. Fallback: NASA POWER (MERRA-2) ─────────────────────────────────────
    try:
        client_nasa = NasaPowerClient(
            endpoint=settings.nasa_power_base_url,
            timeout_s=settings.nasa_power_timeout_s,
        )
        _log.info(
            "Querying NASA POWER MERRA-2 for (%.4f, %.4f) %s → %s",
            lat,
            lon,
            start_date,
            end_date,
        )
        raw_json = client_nasa.get_daily_rainfall(lat, lon, start_date, end_date)
        stats = aggregate_nasa_power(raw_json)
        _log.info(
            "Rainfall (NASA POWER MERRA-2): annual_avg=%.1f mm, "
            "wet_season=%.1f mm, years=%d",
            stats.annual_avg_mm,
            stats.wet_season_avg_mm,
            stats.years_of_data,
        )
        _rainfall_cache[key] = (stats, now)
        return stats

    except (NasaPowerUnavailableError, ValueError, Exception) as exc:
        _log.error(
            "NASA POWER also unavailable (%s). "
            "Returning None — rainfall field will be null in response.",
            exc,
        )
        return None
