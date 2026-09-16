"""
Unit tests for src/hydrology/runoff.py
"""

import pytest

from src.hydrology.rainfall_stats import RainfallStats
from src.hydrology.runoff import (
    _rational_annual_fallback,
    _scs_cn_event,
    _scs_cn_monthly_distributed,
    _scs_cn_retention,
    estimate_runoff,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_rainfall_stats(
    annual_avg_mm: float = 1100.0,
    monthly_avg_mm: list[float] | None = None,
) -> RainfallStats:
    """Helper to build a minimal RainfallStats for testing."""
    if monthly_avg_mm is None:
        # Realistic central-India monsoon distribution (mm/month)
        monthly_avg_mm = [
            10.0,
            15.0,
            20.0,
            30.0,
            50.0,
            120.0,
            260.0,
            280.0,
            180.0,
            80.0,
            30.0,
            10.0,
        ]
    return RainfallStats(
        annual_avg_mm=annual_avg_mm,
        monthly_avg_mm=monthly_avg_mm,
        wet_season_avg_mm=840.0,
        dry_season_avg_mm=260.0,
        wettest_month=8,
        driest_month=1,
        years_of_data=10,
        source="open_meteo_era5_land",
        data_start_year=2014,
        data_end_year=2023,
    )


# ── _scs_cn_event tests ───────────────────────────────────────────────────────


def test_scs_cn_event_zero_below_threshold():
    """P < Ia → Q = 0 (threshold effect)."""
    # CN=71 → S=103.8, Ia=20.8 mm
    s_mm, ia_mm = _scs_cn_retention(71)
    assert ia_mm == pytest.approx(20.76, rel=1e-2)
    # 10 mm drizzle → no runoff
    q = _scs_cn_event(p_mm=10.0, s_mm=s_mm, ia_mm=ia_mm)
    assert q == 0.0


def test_scs_cn_event_equals_zero_at_threshold():
    """P exactly at Ia → Q = 0 (boundary condition)."""
    s_mm, ia_mm = _scs_cn_retention(71)
    q = _scs_cn_event(p_mm=ia_mm, s_mm=s_mm, ia_mm=ia_mm)
    assert q == 0.0


def test_scs_cn_event_formula_arithmetic():
    """
    Known input: P=50mm, S=103.8mm, Ia=20.76mm
    Q = (50 - 20.76)² / (50 - 20.76 + 103.8)
      = (29.24)² / (133.04)
      = 854.98 / 133.04 ≈ 6.43 mm
    """
    s_mm, ia_mm = _scs_cn_retention(71)
    q = _scs_cn_event(p_mm=50.0, s_mm=s_mm, ia_mm=ia_mm)
    assert q == pytest.approx(6.43, rel=5e-2)  # ≈6.4 mm


def test_scs_cn_event_positive_above_threshold():
    """P > Ia → Q > 0."""
    s_mm, ia_mm = _scs_cn_retention(71)
    q = _scs_cn_event(p_mm=50.0, s_mm=s_mm, ia_mm=ia_mm)
    assert q > 0.0


def test_scs_cn_event_never_exceeds_rainfall():
    """Runoff can never exceed total rainfall (conservation of mass)."""
    s_mm, ia_mm = _scs_cn_retention(71)
    for p in [30.0, 50.0, 100.0, 200.0]:
        q = _scs_cn_event(p, s_mm, ia_mm)
        assert q <= p


# ── _scs_cn_monthly_distributed tests ────────────────────────────────────────


def test_annual_volume_units_are_cubic_metres():
    """Volume = depth_mm/1000 × area_m². Units must be m³."""
    monthly_avg = [0.0] * 12
    monthly_avg[6] = 300.0  # July: 300 mm
    area_m2 = 10_000.0  # 1 ha
    monthly_runoff_m3, annual_depth_mm, _ = _scs_cn_monthly_distributed(
        monthly_avg, area_m2, cn=71
    )
    # July daily avg = 300/31 ≈ 9.7 mm < Ia=20.8mm → Q=0 → volume=0
    assert sum(monthly_runoff_m3) == pytest.approx(0.0, abs=0.1)


def test_high_rainfall_month_produces_runoff():
    """High daily rainfall (> Ia) must yield non-zero runoff volume."""
    monthly_avg = [0.0] * 12
    monthly_avg[6] = 900.0  # July: 900 mm → daily ≈ 29 mm/day > Ia=20.8mm
    area_m2 = 50_000.0  # 5 ha
    monthly_runoff_m3, annual_depth_mm, peak_month = _scs_cn_monthly_distributed(
        monthly_avg, area_m2, cn=71
    )
    assert annual_depth_mm > 0.0
    assert sum(monthly_runoff_m3) > 0.0
    assert peak_month == 7  # July


def test_zero_rainfall_gives_zero_runoff():
    """All-zero monthly rainfall → zero annual runoff."""
    monthly_avg = [0.0] * 12
    area_m2 = 10_000.0
    _, annual_depth_mm, _ = _scs_cn_monthly_distributed(monthly_avg, area_m2, cn=71)
    assert annual_depth_mm == 0.0


# ── estimate_runoff integration tests ────────────────────────────────────────


def test_wet_season_exceeds_dry_season():
    """For a typical Indian catchment, JJAS runoff > Oct-May runoff."""
    stats = _make_rainfall_stats()
    result = estimate_runoff(
        catchment_area_ha=5.0,
        rainfall_stats=stats,
    )
    # Monsoon dominates — wet season must be larger than dry season
    assert result.wet_season_avg_m3 >= result.dry_season_avg_m3


def test_peak_month_in_monsoon_range():
    """For a typical India rainfall pattern, peak runoff in Jun–Sep."""
    stats = _make_rainfall_stats()
    result = estimate_runoff(catchment_area_ha=5.0, rainfall_stats=stats)
    assert result.peak_month in {6, 7, 8, 9}


def test_default_method_is_scs_cn():
    """When monthly data is present, method must be 'scs_cn_monthly_distributed'."""
    stats = _make_rainfall_stats()
    result = estimate_runoff(catchment_area_ha=5.0, rainfall_stats=stats)
    assert result.method == "scs_cn_monthly_distributed"


def test_buildup_fraction_above_threshold_raises_cn():
    """>30% built-up in bowl → CN=85 (not default 71)."""
    stats = _make_rainfall_stats()
    result = estimate_runoff(
        catchment_area_ha=5.0,
        rainfall_stats=stats,
        builtup_fraction=0.35,  # above 30% threshold
        hsg="B",
    )
    assert result.curve_number == 85
    assert result.land_cover_assumed == "built_up"


def test_non_builtup_gives_default_cn():
    """<30% built-up → CN=71 (mixed_agriculture, HSG B)."""
    stats = _make_rainfall_stats()
    result = estimate_runoff(
        catchment_area_ha=5.0,
        rainfall_stats=stats,
        builtup_fraction=0.05,
        hsg="B",
    )
    assert result.curve_number == 71
    assert result.land_cover_assumed == "mixed_agriculture"


def test_fallback_method_used_when_monthly_data_unavailable():
    """Empty monthly_avg_mm → rational_annual_fallback method."""
    stats = _make_rainfall_stats(annual_avg_mm=1000.0, monthly_avg_mm=[0.0] * 12)
    result = estimate_runoff(
        catchment_area_ha=5.0,
        rainfall_stats=stats,
        runoff_coefficient_fallback=0.30,
    )
    assert result.method == "rational_annual_fallback"
    # Volume = 0.30 × (1000/1000) × 50000 = 15000 m³
    assert result.annual_avg_m3 == pytest.approx(15000.0, rel=1e-3)


def test_catchment_area_echoed_in_result():
    """catchment_area_ha in result must match the input."""
    stats = _make_rainfall_stats()
    result = estimate_runoff(catchment_area_ha=12.5, rainfall_stats=stats)
    assert result.catchment_area_ha == 12.5


def test_annual_volume_scales_with_area():
    """Doubling catchment area should double the runoff volume."""
    stats = _make_rainfall_stats()
    r1 = estimate_runoff(catchment_area_ha=5.0, rainfall_stats=stats)
    r2 = estimate_runoff(catchment_area_ha=10.0, rainfall_stats=stats)
    assert r2.annual_avg_m3 == pytest.approx(r1.annual_avg_m3 * 2, rel=1e-3)


def test_rational_annual_fallback_arithmetic():
    """Direct test of the fallback function: V = C × P/1000 × A."""
    vol = _rational_annual_fallback(
        annual_avg_mm=1000.0,
        area_m2=10_000.0,
        runoff_coefficient=0.3,
    )
    assert vol == pytest.approx(3000.0, rel=1e-3)
