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

Budget deadline (Module 7 — Reliability Hardening):
  The full Open-Meteo → NASA POWER chain is capped at _RAINFALL_BUDGET_S
  seconds of wall-clock time. Without this, a slow Open-Meteo (3 retries ×
  15 s) followed by a slow NASA POWER (3 retries × 30 s) could block the
  thread for ~85 s. With the cap, worst-case is ~45 s.

  The deadline is enforced by trimming each client's timeout_s to the
  remaining budget. If the budget is exhausted before the NASA POWER call,
  that call is skipped entirely and None is returned.
"""

import logging
import time
from datetime import date

from src.external.rainfall.nasa_power_client import (
    NasaPowerUnavailableError,
    get_nasa_power_client,
)
from src.external.rainfall.open_meteo_client import (
    OpenMeteoUnavailableError,
    get_open_meteo_client,
)
from src.hydrology.rainfall_stats import (
    RainfallStats,
    aggregate_nasa_power,
    aggregate_open_meteo,
)

_log = logging.getLogger(__name__)

# In-memory cache: {(lat2dp, lon2dp, start_year, end_year): (RainfallStats, ts)}
_rainfall_cache: dict[tuple, tuple[RainfallStats, float]] = {}

# Total wall-clock budget (seconds) for the combined Open-Meteo + NASA POWER
# chain. Keeps the rainfall step from blocking the thread for ~85 s worst-case.
# With this cap: ≤ 1 Open-Meteo attempt (15 s) + 1 NASA POWER attempt (30 s) = 45 s.
_RAINFALL_BUDGET_S: int = 45


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

    The combined call is bounded by ``_RAINFALL_BUDGET_S`` seconds. If the
    Open-Meteo call exhausts the budget, the NASA POWER fallback is skipped.

    Args:
        lat:      WGS84 latitude of the selected pond candidate.
        lon:      WGS84 longitude of the selected pond candidate.
        settings: The global Settings instance.

    Returns:
        :class:`RainfallStats` or None if both APIs are unavailable or the
        budget is exhausted.
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

    # ── Budget deadline ───────────────────────────────────────────────────────
    # All remaining HTTP work must complete within _RAINFALL_BUDGET_S seconds.
    budget_deadline = time.monotonic() + _RAINFALL_BUDGET_S

    # ── 2. Try Open-Meteo (primary) ───────────────────────────────────────────
    try:
        # Clamp timeout to remaining budget (minimum 2 s to avoid instant failure).
        remaining = max(2.0, budget_deadline - time.monotonic())
        client = get_open_meteo_client(
            endpoint=settings.open_meteo_base_url,
            timeout_s=min(settings.open_meteo_timeout_s, int(remaining)),
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
        _rainfall_cache[key] = (stats, time.monotonic())
        return stats

    except (OpenMeteoUnavailableError, ValueError, Exception) as exc:
        _log.warning(
            "Open-Meteo unavailable or parse failed (%s) — "
            "falling back to NASA POWER MERRA-2.",
            exc,
        )

    # ── 3. Budget check before NASA POWER ────────────────────────────────────
    remaining = budget_deadline - time.monotonic()
    if remaining <= 2.0:
        _log.warning(
            "Rainfall budget exhausted (%.1f s left) — skipping NASA POWER fallback. "
            "Returning None; rainfall field will be null in response.",
            remaining,
        )
        return None

    # ── 4. Fallback: NASA POWER (MERRA-2) ─────────────────────────────────────
    try:
        client_nasa = get_nasa_power_client(
            endpoint=settings.nasa_power_base_url,
            timeout_s=min(settings.nasa_power_timeout_s, int(remaining)),
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
        _rainfall_cache[key] = (stats, time.monotonic())
        return stats

    except (NasaPowerUnavailableError, ValueError, Exception) as exc:
        _log.error(
            "NASA POWER also unavailable (%s). "
            "Returning None — rainfall field will be null in response.",
            exc,
        )
        return None
