import json

import pytest

from src.hydrology.rainfall_stats import (
    aggregate_nasa_power,
    aggregate_open_meteo,
)


def test_aggregate_open_meteo_monsoon_detected():
    raw_json = json.dumps(
        {
            "daily": {
                "time": [
                    "2023-01-01",
                    "2023-06-15",
                    "2023-07-20",
                    "2023-08-10",
                    "2023-11-01",
                ],
                "precipitation_sum": [1.0, 50.0, 100.0, 150.0, 2.0],
            }
        }
    )

    stats = aggregate_open_meteo(raw_json)

    assert stats.annual_avg_mm == 303.0
    assert stats.wet_season_avg_mm == 300.0  # June, July, August
    assert stats.dry_season_avg_mm == 3.0  # Jan, Nov
    assert stats.years_of_data == 1
    assert stats.source == "open_meteo_era5_land"
    assert stats.wettest_month == 8  # August has 150.0


def test_aggregate_open_meteo_null_days_skipped():
    raw_json = json.dumps(
        {
            "daily": {
                "time": ["2023-06-01", "2023-06-02"],
                "precipitation_sum": [10.0, None],
            }
        }
    )
    stats = aggregate_open_meteo(raw_json)
    assert stats.annual_avg_mm == 10.0


def test_aggregate_nasa_power_fill_value_skipped():
    raw_json = json.dumps(
        {
            "properties": {
                "parameter": {"PRECTOTCORR": {"20230601": 20.0, "20230602": -999.0}}
            }
        }
    )
    stats = aggregate_nasa_power(raw_json)
    assert stats.annual_avg_mm == 20.0
    assert stats.source == "nasa_power_merra2"


def test_monthly_avg_has_12_entries():
    raw_json = json.dumps(
        {"daily": {"time": ["2023-06-01"], "precipitation_sum": [10.0]}}
    )
    stats = aggregate_open_meteo(raw_json)
    assert len(stats.monthly_avg_mm) == 12
    assert stats.monthly_avg_mm[5] == 10.0  # index 5 is June
    assert sum(stats.monthly_avg_mm) == 10.0


def test_empty_data_raises_value_error():
    with pytest.raises(ValueError, match="No valid rainfall data"):
        aggregate_open_meteo('{"daily": {"time": [], "precipitation_sum": []}}')

    with pytest.raises(ValueError, match="No valid rainfall data"):
        aggregate_nasa_power('{"properties": {"parameter": {"PRECTOTCORR": {}}}}')
