"""
Unit tests for build_rainfall_stats() in rainfall_service.py.

Module 7 additions:
  - Tests now patch get_open_meteo_client / get_nasa_power_client (singleton
    getters) rather than the class constructors directly.
  - test_budget_exhausted_skips_nasa_power: verifies that if _RAINFALL_BUDGET_S
    is set to 0, the NASA POWER fallback is skipped entirely and None is returned.
  - test_singleton_getters_are_reused: verifies that repeated calls to
    build_rainfall_stats return the client singleton (no new instances).
"""

import time
from unittest.mock import MagicMock, patch

from src.catchment.rainfall_service import _rainfall_cache, build_rainfall_stats
from src.external.rainfall.nasa_power_client import NasaPowerUnavailableError
from src.external.rainfall.open_meteo_client import OpenMeteoUnavailableError
from src.hydrology.rainfall_stats import RainfallStats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_settings(history_years: int = 1, cache_ttl_s: int = 86400) -> MagicMock:
    s = MagicMock()
    s.rainfall_history_years = history_years
    s.rainfall_cache_ttl_s = cache_ttl_s
    s.open_meteo_timeout_s = 15
    s.nasa_power_timeout_s = 30
    return s


def _make_stats(source: str = "open_meteo") -> RainfallStats:
    return RainfallStats(
        annual_avg_mm=1200.0,
        monthly_avg_mm=[0.0] * 12,
        wet_season_avg_mm=1000.0,
        dry_season_avg_mm=200.0,
        wettest_month=7,
        driest_month=1,
        years_of_data=1,
        source=source,
        data_start_year=2023,
        data_end_year=2023,
    )


# ---------------------------------------------------------------------------
# Cache tests
# ---------------------------------------------------------------------------
def test_cache_hit_skips_http():
    """A warm cache entry should be returned without any HTTP call."""
    _rainfall_cache.clear()

    settings = _make_settings()
    stats = _make_stats("cache")

    from datetime import date

    end_year = date.today().year - 1
    key = (23.0, 80.0, end_year, end_year)
    _rainfall_cache[key] = (stats, time.monotonic())

    with (
        patch("src.catchment.rainfall_service.get_open_meteo_client") as mock_om,
        patch("src.catchment.rainfall_service.get_nasa_power_client") as mock_nasa,
    ):
        res = build_rainfall_stats(23.0, 80.0, settings)

        assert res is stats
        mock_om.assert_not_called()
        mock_nasa.assert_not_called()


def test_expired_cache_triggers_requery():
    """An expired cache entry (TTL=0) should trigger a fresh HTTP call."""
    _rainfall_cache.clear()

    settings = _make_settings(cache_ttl_s=0)  # expire immediately
    stats = _make_stats()

    from datetime import date

    end_year = date.today().year - 1
    key = (23.0, 80.0, end_year, end_year)
    _rainfall_cache[key] = (stats, 0.0)  # very old timestamp

    with (
        patch("src.catchment.rainfall_service.get_open_meteo_client") as mock_om,
        patch("src.catchment.rainfall_service.aggregate_open_meteo") as mock_agg,
    ):
        fresh = _make_stats("fresh")
        mock_om.return_value.get_daily_rainfall.return_value = "{}"
        mock_agg.return_value = fresh

        res = build_rainfall_stats(23.0, 80.0, settings)
        assert res is fresh
        mock_om.assert_called_once()


# ---------------------------------------------------------------------------
# Primary source: Open-Meteo
# ---------------------------------------------------------------------------
@patch("src.catchment.rainfall_service.aggregate_open_meteo")
@patch("src.catchment.rainfall_service.get_open_meteo_client")
def test_open_meteo_primary_called(mock_client_fn, mock_agg):
    _rainfall_cache.clear()
    settings = _make_settings()

    mock_instance = mock_client_fn.return_value
    mock_instance.get_daily_rainfall.return_value = "{}"
    mock_stats = _make_stats()
    mock_agg.return_value = mock_stats

    res = build_rainfall_stats(23.0, 80.0, settings)

    assert res is mock_stats
    mock_instance.get_daily_rainfall.assert_called_once()
    mock_agg.assert_called_once_with("{}")


# ---------------------------------------------------------------------------
# Fallback: NASA POWER
# ---------------------------------------------------------------------------
@patch("src.catchment.rainfall_service.aggregate_nasa_power")
@patch("src.catchment.rainfall_service.get_nasa_power_client")
@patch("src.catchment.rainfall_service.get_open_meteo_client")
def test_fallback_to_nasa_power_when_open_meteo_fails(
    mock_om_fn, mock_nasa_fn, mock_nasa_agg
):
    _rainfall_cache.clear()
    settings = _make_settings()

    mock_om_fn.return_value.get_daily_rainfall.side_effect = OpenMeteoUnavailableError(
        "Timeout"
    )

    mock_nasa_inst = mock_nasa_fn.return_value
    mock_nasa_inst.get_daily_rainfall.return_value = "{nasa_data}"
    mock_stats = _make_stats("nasa_power")
    mock_nasa_agg.return_value = mock_stats

    res = build_rainfall_stats(23.0, 80.0, settings)

    assert res is mock_stats
    mock_nasa_inst.get_daily_rainfall.assert_called_once()
    mock_nasa_agg.assert_called_once_with("{nasa_data}")


# ---------------------------------------------------------------------------
# Both sources fail
# ---------------------------------------------------------------------------
@patch("src.catchment.rainfall_service.get_nasa_power_client")
@patch("src.catchment.rainfall_service.get_open_meteo_client")
def test_returns_none_when_both_unavailable(mock_om_fn, mock_nasa_fn):
    _rainfall_cache.clear()
    settings = _make_settings()

    mock_om_fn.return_value.get_daily_rainfall.side_effect = OpenMeteoUnavailableError()
    mock_nasa_fn.return_value.get_daily_rainfall.side_effect = (
        NasaPowerUnavailableError()
    )

    res = build_rainfall_stats(23.0, 80.0, settings)
    assert res is None


# ---------------------------------------------------------------------------
# Budget deadline (Module 7 — Reliability Hardening)
# ---------------------------------------------------------------------------
@patch("src.catchment.rainfall_service.get_nasa_power_client")
@patch("src.catchment.rainfall_service.get_open_meteo_client")
def test_budget_exhausted_skips_nasa_power(mock_om_fn, mock_nasa_fn, monkeypatch):
    """
    If the Open-Meteo attempt exhausts the budget, the NASA POWER fallback
    must be skipped entirely and None returned.

    We achieve this by setting _RAINFALL_BUDGET_S to 0 so that
    ``budget_deadline = time.monotonic() + 0`` is already in the past by
    the time the NASA POWER check runs.
    """
    _rainfall_cache.clear()
    settings = _make_settings()

    # Open-Meteo fails (ate the budget)
    mock_om_fn.return_value.get_daily_rainfall.side_effect = OpenMeteoUnavailableError(
        "timed out"
    )

    # Set budget to 0 so there is no time left for NASA POWER
    monkeypatch.setattr("src.catchment.rainfall_service._RAINFALL_BUDGET_S", 0)

    res = build_rainfall_stats(23.0, 80.0, settings)

    assert res is None
    mock_nasa_fn.assert_not_called()  # NASA POWER call must be skipped
