from unittest.mock import MagicMock, patch

from src.catchment.rainfall_service import _rainfall_cache, build_rainfall_stats
from src.external.rainfall.nasa_power_client import NasaPowerUnavailableError
from src.external.rainfall.open_meteo_client import OpenMeteoUnavailableError
from src.hydrology.rainfall_stats import RainfallStats


def test_cache_hit_skips_http():
    # Clear cache before test
    _rainfall_cache.clear()

    # Mock settings
    settings = MagicMock()
    settings.rainfall_history_years = 1
    settings.rainfall_cache_ttl_s = 86400

    stats = RainfallStats(
        annual_avg_mm=100.0,
        monthly_avg_mm=[0.0] * 12,
        wet_season_avg_mm=100.0,
        dry_season_avg_mm=0.0,
        wettest_month=7,
        driest_month=1,
        years_of_data=1,
        source="cache",
        data_start_year=2023,
        data_end_year=2023,
    )

    # Inject into cache
    import time
    from datetime import date

    end_year = date.today().year - 1
    start_year = end_year
    key = (23.0, 80.0, start_year, end_year)
    _rainfall_cache[key] = (stats, time.monotonic())

    with patch("src.catchment.rainfall_service.OpenMeteoClient") as mock_open:
        with patch("src.catchment.rainfall_service.NasaPowerClient") as mock_nasa:
            res = build_rainfall_stats(23.0, 80.0, settings)

            assert res is stats
            mock_open.assert_not_called()
            mock_nasa.assert_not_called()


@patch("src.catchment.rainfall_service.aggregate_open_meteo")
@patch("src.catchment.rainfall_service.OpenMeteoClient")
def test_open_meteo_primary_called(mock_client_cls, mock_agg):
    _rainfall_cache.clear()
    settings = MagicMock()
    settings.rainfall_history_years = 1
    settings.rainfall_cache_ttl_s = 86400

    mock_instance = mock_client_cls.return_value
    mock_instance.get_daily_rainfall.return_value = "{}"

    mock_stats = MagicMock()
    mock_agg.return_value = mock_stats

    res = build_rainfall_stats(23.0, 80.0, settings)

    assert res is mock_stats
    mock_instance.get_daily_rainfall.assert_called_once()
    mock_agg.assert_called_once_with("{}")


@patch("src.catchment.rainfall_service.aggregate_nasa_power")
@patch("src.catchment.rainfall_service.NasaPowerClient")
@patch("src.catchment.rainfall_service.OpenMeteoClient")
def test_fallback_to_nasa_power_when_open_meteo_fails(
    mock_open_cls, mock_nasa_cls, mock_nasa_agg
):
    _rainfall_cache.clear()
    settings = MagicMock()
    settings.rainfall_history_years = 1
    settings.rainfall_cache_ttl_s = 86400

    mock_open_inst = mock_open_cls.return_value
    mock_open_inst.get_daily_rainfall.side_effect = OpenMeteoUnavailableError("Timeout")

    mock_nasa_inst = mock_nasa_cls.return_value
    mock_nasa_inst.get_daily_rainfall.return_value = "{nasa_data}"

    mock_stats = MagicMock()
    mock_nasa_agg.return_value = mock_stats

    res = build_rainfall_stats(23.0, 80.0, settings)

    assert res is mock_stats
    mock_nasa_inst.get_daily_rainfall.assert_called_once()
    mock_nasa_agg.assert_called_once_with("{nasa_data}")


@patch("src.catchment.rainfall_service.NasaPowerClient")
@patch("src.catchment.rainfall_service.OpenMeteoClient")
def test_returns_none_when_both_unavailable(mock_open_cls, mock_nasa_cls):
    _rainfall_cache.clear()
    settings = MagicMock()
    settings.rainfall_history_years = 1
    settings.rainfall_cache_ttl_s = 86400

    mock_open_cls.return_value.get_daily_rainfall.side_effect = (
        OpenMeteoUnavailableError()
    )
    mock_nasa_cls.return_value.get_daily_rainfall.side_effect = (
        NasaPowerUnavailableError()
    )

    res = build_rainfall_stats(23.0, 80.0, settings)

    assert res is None
