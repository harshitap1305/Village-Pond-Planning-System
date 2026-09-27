"""
Runoff estimation for village pond catchments using the SCS-CN method.

Public interface:
    estimate_runoff(catchment_area_ha, rainfall_stats, ...) -> RunoffEstimate

Method: SCS Curve Number (monthly-distributed daily application)
─────────────────────────────────────────────────────────────────
The SCS-CN method (USDA TR-55 / NRSC IMSD) converts rainfall depth to runoff
depth at the event scale, using the catchment's Curve Number (CN) to encode
soil infiltration and land-cover characteristics.

Core equations:
    S  = (25400 / CN) - 254      # mm — potential maximum retention
    Ia = 0.2 × S                  # mm — initial abstraction (threshold)
    For each daily rainfall P (mm):
        if P > Ia:
            Q = (P - Ia)² / (P - Ia + S)
        else:
            Q = 0.0               # No runoff below the abstraction threshold

Key insight — the threshold effect:
    A 10 mm/day drizzle (P < Ia for CN=71, Ia≈20.8 mm) produces zero runoff.
    A 50 mm storm produces Q ≈ 6.4 mm of runoff — a fraction is abstracted,
    the rest runs off.  A simple C×P formula cannot capture this, because it
    applies the same fraction to every mm of rain regardless of intensity.

Daily time-series approach:
    Rather than working at the monthly-average total level, we distribute each
    monthly average evenly across the days of that month, giving a synthetic
    daily series.  This preserves the threshold effect across all months and
    produces a conservative annual estimate (real daily variance would produce
    more runoff on high-intensity days, so our uniform-day assumption
    underestimates peak contributions — appropriate for a safe design baseline).

Fallback:
    If monthly rainfall data is unavailable (RainfallStats is None or has
    zero-length monthly_avg_mm), the function degrades to:
        Volume = runoff_coefficient_fallback × annual_avg_mm/1000 × area_m²
    and sets method="rational_annual_fallback".

Authority references:
    - USDA TR-55, 1986 (Technical Release No. 55)
    - USDA NEH Part 630, Chapter 10 (Estimation of Direct Runoff from Storm Rainfall)
    - NRSC/ISRO IMSD Technical Guidelines for Watershed Assessment
    - IS 5477 Part 1 (Methods for Fixing the Capacities of Low Dams)
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from src.hydrology.rainfall_stats import RainfallStats
from src.hydrology.runoff_coefficients import DEFAULT_HSG, derive_curve_number

_log = logging.getLogger(__name__)

# ── Month calendar ────────────────────────────────────────────────────────────
# Average number of days per month (ignoring leap years — negligible for
# 10-year annual average estimation).
_DAYS_IN_MONTH: list[int] = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

# Wet season months (South-West Monsoon JJAS) — same definition as rainfall_stats
_WET_MONTHS: frozenset[int] = frozenset({6, 7, 8, 9})  # June–September


# ── Output schema ─────────────────────────────────────────────────────────────


class RunoffEstimate(BaseModel):
    """
    Estimated runoff volumes for the selected pond's catchment.

    Produced by applying the SCS Curve Number method to the 10-year historical
    monthly rainfall averages from Module 2.

    Attributes:
        annual_avg_m3:         Mean annual runoff volume (m³) reaching the bowl.
        wet_season_avg_m3:     Jun–Sep runoff volume (m³) — primary fill period.
        dry_season_avg_m3:     Oct–May runoff volume (m³).
        peak_month:            Calendar month (1-12) with highest mean monthly
                               runoff contribution.
        runoff_depth_mm:       Mean annual runoff depth (mm) over the catchment.
                               Useful as a cross-check against published regional
                               tables (e.g. IS 5477 Appendix A).
        curve_number:          Dimensionless CN value used in the SCS model.
        land_cover_assumed:    Land-cover category inferred from Module 1 data
                               (e.g. ``"mixed_agriculture"`` | ``"built_up"``).
        hsg_assumed:           Hydrologic Soil Group used (A/B/C/D).
        catchment_area_ha:     Catchment area (ha) — echoed from the candidate
                               for traceability.
        method:                ``"scs_cn_monthly_distributed"`` if the daily SCS
                               method was used; ``"rational_annual_fallback"``
                               if monthly data was unavailable.
    """

    annual_avg_m3: float
    wet_season_avg_m3: float
    dry_season_avg_m3: float
    peak_month: int  # 1–12
    runoff_depth_mm: float
    curve_number: int
    land_cover_assumed: str
    hsg_assumed: str
    catchment_area_ha: float
    method: str


# ── Internal helpers ──────────────────────────────────────────────────────────


def _scs_cn_retention(cn: int) -> tuple[float, float]:
    """
    Compute potential maximum retention S and initial abstraction Ia.

    Args:
        cn: Curve Number (1–100).

    Returns:
        (S_mm, Ia_mm) tuple.
    """
    s = (25400.0 / cn) - 254.0
    ia = 0.2 * s
    return s, ia


def _scs_cn_event(p_mm: float, s_mm: float, ia_mm: float) -> float:
    """
    SCS-CN runoff depth for a single rainfall event of depth P.

    Q = (P - Ia)² / (P - Ia + S)   if P > Ia
    Q = 0                            otherwise

    Args:
        p_mm:  Rainfall depth (mm).
        s_mm:  Potential maximum retention (mm).
        ia_mm: Initial abstraction threshold (mm).

    Returns:
        Runoff depth Q (mm), ≥ 0.
    """
    if p_mm <= ia_mm:
        return 0.0
    excess = p_mm - ia_mm
    return (excess * excess) / (excess + s_mm)


def _scs_cn_monthly_distributed(
    monthly_avg_mm: list[float],
    area_m2: float,
    cn: int,
) -> tuple[list[float], float, int]:
    """
    Apply SCS-CN daily event model to each month's average total, distributing
    that total uniformly across the month's days.

    This preserves the critical non-linear threshold effect: months with daily
    average rainfall below Ia contribute zero runoff, while months with higher
    daily averages contribute runoff that scales with (P - Ia)².

    Args:
        monthly_avg_mm: 12-element list of mean monthly rainfall totals (mm),
                        Jan=index 0 … Dec=index 11.
        area_m2:        Catchment area in m².
        cn:             Curve Number.

    Returns:
        (monthly_runoff_m3, annual_depth_mm, peak_month)
        - monthly_runoff_m3: 12-element list of monthly runoff volumes (m³).
        - annual_depth_mm:   Total annual runoff depth (mm).
        - peak_month:        1-indexed calendar month with highest runoff.
    """
    s_mm, ia_mm = _scs_cn_retention(cn)
    monthly_runoff_mm: list[float] = []

    for m_idx, month_total_mm in enumerate(monthly_avg_mm):
        # Apply SCS-CN directly to the monthly total.
        # While originally an event-based model, adapting it to monthly
        # totals is a standard simplification that avoids the "zero runoff"
        # bug caused by distributing rain too thinly across all 30 days.
        q_month_mm = _scs_cn_event(month_total_mm, s_mm, ia_mm)
        monthly_runoff_mm.append(q_month_mm)

    annual_depth_mm = sum(monthly_runoff_mm)
    # Convert each month to volume (m³): depth_mm / 1000 × area_m²
    monthly_runoff_m3 = [(q_mm / 1000.0) * area_m2 for q_mm in monthly_runoff_mm]

    # Peak month (1-indexed); default to July (month 7) if all zeros
    if max(monthly_runoff_mm) > 0:
        peak_month = monthly_runoff_mm.index(max(monthly_runoff_mm)) + 1
    else:
        peak_month = 7  # monsoon default

    return monthly_runoff_m3, annual_depth_mm, peak_month


def _rational_annual_fallback(
    annual_avg_mm: float,
    area_m2: float,
    runoff_coefficient: float,
) -> float:
    """
    Simple C × P × A fallback when monthly data is unavailable.

    Args:
        annual_avg_mm:      Mean annual rainfall (mm).
        area_m2:            Catchment area (m²).
        runoff_coefficient: Dimensionless runoff fraction (0–1).

    Returns:
        Annual runoff volume (m³).
    """
    return (annual_avg_mm / 1000.0) * area_m2 * runoff_coefficient


# ── Public interface ──────────────────────────────────────────────────────────


def estimate_runoff(
    catchment_area_ha: float,
    rainfall_stats: RainfallStats,
    builtup_fraction: float = 0.0,
    hsg: str = DEFAULT_HSG,
    runoff_coefficient_fallback: float = 0.30,
) -> RunoffEstimate:
    """
    Estimate mean annual and seasonal runoff volumes for a pond catchment.

    Uses the SCS Curve Number method applied to the 10-year monthly average
    rainfall from Module 2.  Falls back to a simple coefficient method if
    monthly data is unavailable.

    Args:
        catchment_area_ha:         Uphill catchment area draining to the bowl
                                   (hectares), taken from the selected candidate.
        rainfall_stats:            Aggregated historical rainfall from Module 2.
        builtup_fraction:          Fraction of DEM bowl cells classified as
                                   built-up by Module 1's land exclusion mask
                                   (0.0–1.0). Used to detect urban catchments.
        hsg:                       Hydrologic Soil Group ("A"/"B"/"C"/"D").
                                   Default is "B" (laterite / red soil dominant).
        runoff_coefficient_fallback: Simple C coefficient used only if monthly
                                     rainfall data is unavailable.

    Returns:
        :class:`RunoffEstimate` with seasonal and annual volumes.
    """
    area_m2 = catchment_area_ha * 10_000.0
    cn, land_cover = derive_curve_number(builtup_fraction, hsg)

    _log.info(
        "Runoff estimation: area=%.2f ha, CN=%d (%s, HSG-%s), " "builtup_fraction=%.3f",
        catchment_area_ha,
        cn,
        land_cover,
        hsg,
        builtup_fraction,
    )

    # ── Primary path: SCS-CN with monthly distribution ───────────────────────
    monthly_data = getattr(rainfall_stats, "monthly_avg_mm", None)
    if monthly_data and len(monthly_data) == 12 and any(v > 0 for v in monthly_data):
        monthly_runoff_m3, annual_depth_mm, peak_month = _scs_cn_monthly_distributed(
            monthly_avg_mm=monthly_data,
            area_m2=area_m2,
            cn=cn,
        )

        wet_m3 = sum(
            v for i, v in enumerate(monthly_runoff_m3) if (i + 1) in _WET_MONTHS
        )
        dry_m3 = sum(
            v for i, v in enumerate(monthly_runoff_m3) if (i + 1) not in _WET_MONTHS
        )
        annual_m3 = sum(monthly_runoff_m3)

        _log.info(
            "SCS-CN runoff: annual=%.0f m³, wet_season=%.0f m³, "
            "depth=%.1f mm, peak_month=%d",
            annual_m3,
            wet_m3,
            annual_depth_mm,
            peak_month,
        )

        return RunoffEstimate(
            annual_avg_m3=round(annual_m3, 1),
            wet_season_avg_m3=round(wet_m3, 1),
            dry_season_avg_m3=round(dry_m3, 1),
            peak_month=peak_month,
            runoff_depth_mm=round(annual_depth_mm, 1),
            curve_number=cn,
            land_cover_assumed=land_cover,
            hsg_assumed=hsg.upper(),
            catchment_area_ha=catchment_area_ha,
            method="scs_cn_monthly_distributed",
        )

    # ── Fallback: simple coefficient × annual rainfall ────────────────────────
    _log.warning(
        "Monthly rainfall data unavailable — falling back to rational method "
        "(C=%.2f).",
        runoff_coefficient_fallback,
    )
    annual_m3 = _rational_annual_fallback(
        annual_avg_mm=rainfall_stats.annual_avg_mm,
        area_m2=area_m2,
        runoff_coefficient=runoff_coefficient_fallback,
    )
    # Approximate seasonal split: 80% wet / 20% dry (typical India monsoon ratio)
    wet_m3 = annual_m3 * 0.80
    dry_m3 = annual_m3 * 0.20
    annual_depth_mm = rainfall_stats.annual_avg_mm * runoff_coefficient_fallback

    return RunoffEstimate(
        annual_avg_m3=round(annual_m3, 1),
        wet_season_avg_m3=round(wet_m3, 1),
        dry_season_avg_m3=round(dry_m3, 1),
        peak_month=7,  # default to July for monsoon India
        runoff_depth_mm=round(annual_depth_mm, 1),
        curve_number=cn,
        land_cover_assumed=land_cover,
        hsg_assumed=hsg.upper(),
        catchment_area_ha=catchment_area_ha,
        method="rational_annual_fallback",
    )
