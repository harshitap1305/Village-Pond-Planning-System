"""
Pond dimensioning and storage capacity recommendation for village pond sites.

Public interface:
    recommend_pond_design(runoff_estimate, topographic_storage_m3, ...) -> PondDesign

Design approach: Two-constraint reconciliation
──────────────────────────────────────────────
Module 3 tells us how much water *arrives* per year (m³).
This module asks: what physical pond dimensions are needed to store a
target fraction of it — subject to what the bowl can *physically* hold?

The two binding constraints:
  1. Hydrological supply:  runoff_estimate.annual_avg_m3 × target_capture_fraction
  2. Topographic capacity: selected.estimated_storage_m3 (DEM fill volume)

We take the minimum — you can't store more than the bowl holds, and you
shouldn't build a pond far larger than the water supply can fill.

Design chain (IS 5477 terminology):
  target_storage (= live storage)
      ↓  ÷ (1 - evap_fraction - seepage_fraction)
  gross_storage
      ↓  + dead_storage (IS 5477 Part 2 sediment allowance)
  total_storage
      ↓  / (surface_area × shape_factor)
  water_depth_m  [clamped to min/max]
      ↓  + freeboard
  embankment_height_m

Authority references:
  - IS 5477 Part 2 (Dead Storage), Part 3 (Live Storage), Part 4 (Freeboard)
  - IS 12169 (earthen dam embankment requirements)
  - NABARD Farm Pond Design Guidelines
  - MGNREGS Model Estimates (standard depth range 1.5–3m)
  - Central Water Commission (CWC): evaporation loss data for Indian reservoirs
  - MOEF Farm Pond Technical Manual: freeboard, seepage, side-slope standards
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from src.hydrology.runoff import RunoffEstimate

_log = logging.getLogger(__name__)

# ── Feasibility constraint labels ─────────────────────────────────────────────
_CONSTRAINED_BY_HYDROLOGY = "hydrology"
_CONSTRAINED_BY_TOPOGRAPHY = "topography"
_CONSTRAINED_BY_DEPTH_MIN = "depth_min"
_CONSTRAINED_BY_DEPTH_MAX = "depth_max"


# ── Output schema ─────────────────────────────────────────────────────────────


class PondDesign(BaseModel):
    """
    Recommended pond dimensions derived from hydrological and topographic inputs.

    Storage breakdown follows IS 5477 terminology:
        live_storage_m3   — useful storage between MDDL and FSL.
        dead_storage_m3   — sediment allowance below MDDL (IS 5477 Part 2).
        gross_storage_m3  — live_storage inflated to cover annual losses.
        total_storage_m3  — gross + dead (physical capacity to construct).

    Attributes:
        live_storage_m3:          Useful annual storage target (m³).
        dead_storage_m3:          IS 5477 Part 2 sediment allowance (m³).
        gross_storage_m3:         live_storage / (1 − evap − seepage) (m³).
        total_storage_m3:         gross_storage + dead_storage (m³).
        water_depth_m:            Recommended water depth at FSL (m).
                                  Clamped to [min_pond_depth_m, max_pond_depth_m].
        embankment_height_m:      water_depth_m + freeboard_m (m).
        surface_area_m2:          Pond footprint area at FSL (m²).
        embankment_top_width_m:   Standard bund crest width (m).
        target_capture_fraction:  Fraction of annual runoff targeted.
        freeboard_m:              Safety margin above FSL (m).
        side_slope:               H:V ratio for embankment faces (e.g. 2.0).
        shape_factor:             Bowl form factor used in depth back-calc.
        evaporation_loss_fraction: Annual evap loss as fraction of gross.
        seepage_loss_fraction:    Annual seepage loss as fraction of gross.
        topographic_storage_m3:   Upper-bound physical capacity from DEM.
        annual_runoff_m3:         Module 3 annual runoff volume (traceability).
        constrained_by:           Which limit bound the design:
                                  ``"hydrology"``  — runoff < topographic cap.
                                  ``"topography"`` — bowl can't hold 40% runoff.
                                  ``"depth_min"``  — formula depth < min_pond_depth.
                                  ``"depth_max"``  — formula depth > max_pond_depth.
        fills_in_wet_season:      True if wet-season runoff alone fills live storage.
        supply_deficit:           True if annual runoff < live storage
                                  (pond won't fill every year on average).
    """

    # Storage breakdown
    live_storage_m3: float
    dead_storage_m3: float
    gross_storage_m3: float
    total_storage_m3: float

    # Physical dimensions
    water_depth_m: float
    embankment_height_m: float
    surface_area_m2: float
    embankment_top_width_m: float

    # Design parameters used (for full traceability)
    target_capture_fraction: float
    freeboard_m: float
    side_slope: float
    shape_factor: float
    evaporation_loss_fraction: float
    seepage_loss_fraction: float

    # Source data (echoed for report rendering)
    topographic_storage_m3: float
    annual_runoff_m3: float

    # Feasibility flags
    constrained_by: str
    fills_in_wet_season: bool
    supply_deficit: bool


# ── Public interface ──────────────────────────────────────────────────────────


def recommend_pond_design(
    runoff_estimate: RunoffEstimate,
    topographic_storage_m3: float,
    depression_area_ha: float,
    settings,
) -> PondDesign:
    """
    Recommend pond dimensions based on hydrological supply and topographic capacity.

    The design reconciles two constraints:
    1. The water supply: ``runoff_estimate.annual_avg_m3 × target_capture_fraction``.
    2. The physical bowl: ``topographic_storage_m3`` (fill volume from the DEM).

    Args:
        runoff_estimate:        Module 3 output — annual/seasonal runoff volumes.
        topographic_storage_m3: Topographic fill volume of the depression bowl
                                (m³), from Phase 2 candidate detection.
        depression_area_ha:     Bowl footprint area (ha), used as pond surface
                                area at full supply level.
        settings:               Global Settings instance.

    Returns:
        :class:`PondDesign` with full storage breakdown, recommended depth,
        embankment height, and feasibility flags.

    Raises:
        ValueError: If ``depression_area_ha`` is zero or negative (no bowl to
                    design a pond in).
    """
    if depression_area_ha <= 0:
        raise ValueError(
            f"depression_area_ha must be positive, got {depression_area_ha}"
        )

    annual_runoff_m3 = runoff_estimate.annual_avg_m3
    wet_season_m3 = runoff_estimate.wet_season_avg_m3

    # ── Step 1: Determine target (live) storage ───────────────────────────────
    # The hydrological target is the fraction of annual runoff we aim to capture.
    hydrological_target_m3 = annual_runoff_m3 * settings.target_capture_fraction
    # Physical upper bound: the bowl cannot store more than it can hold.
    live_storage_m3 = min(hydrological_target_m3, topographic_storage_m3)

    if hydrological_target_m3 <= topographic_storage_m3:
        primary_constraint = _CONSTRAINED_BY_HYDROLOGY
    else:
        primary_constraint = _CONSTRAINED_BY_TOPOGRAPHY

    _log.info(
        "Pond design: hydro_target=%.0f m³, topo_cap=%.0f m³ → live_storage=%.0f m³ "
        "(constrained by %s)",
        hydrological_target_m3,
        topographic_storage_m3,
        live_storage_m3,
        primary_constraint,
    )

    # ── Step 2: Inflate for losses (live → gross storage) ────────────────────
    # The pond must be built slightly larger to account for annual losses:
    #   evaporation (CWC data: ~15% for central India) + seepage (~10% unlined).
    # Reference: IS 5477, NABARD farm pond design guidelines.
    loss_fraction = settings.evaporation_loss_fraction + settings.seepage_loss_fraction
    # Guard against misconfigured loss_fraction >= 1
    loss_fraction = min(loss_fraction, 0.90)
    gross_storage_m3 = live_storage_m3 / (1.0 - loss_fraction)

    # ── Step 3: Dead storage (IS 5477 Part 2 — sediment allowance) ───────────
    dead_storage_m3 = gross_storage_m3 * settings.dead_storage_fraction
    total_storage_m3 = gross_storage_m3 + dead_storage_m3

    # ── Step 4: Back-solve water depth from bowl geometry ────────────────────
    # Use bowl footprint area as the pond surface area at full supply level (FSL).
    # Volume ≈ surface_area × depth × shape_factor (bowl form factor = 0.4).
    # The shape_factor approximates the prismoidal formula for natural depressions
    # with A_bottom ≈ 0.3 × A_top (NABARD farm pond design guide, Table 4).
    surface_area_m2 = depression_area_ha * 10_000.0
    raw_depth_m = total_storage_m3 / (surface_area_m2 * settings.pond_shape_factor)

    # Clamp depth to engineering limits; track which limit was hit.
    constrained_by = primary_constraint
    if raw_depth_m < settings.min_pond_depth_m:
        water_depth_m = settings.min_pond_depth_m
        constrained_by = _CONSTRAINED_BY_DEPTH_MIN
        _log.info(
            "Raw depth %.2fm < min %.2fm — clamping to minimum.",
            raw_depth_m,
            settings.min_pond_depth_m,
        )
    elif raw_depth_m > settings.max_pond_depth_m:
        water_depth_m = settings.max_pond_depth_m
        constrained_by = _CONSTRAINED_BY_DEPTH_MAX
        _log.info(
            "Raw depth %.2fm > max %.2fm — clamping to maximum.",
            raw_depth_m,
            settings.max_pond_depth_m,
        )
    else:
        water_depth_m = raw_depth_m

    water_depth_m = round(water_depth_m, 2)

    # ── Step 5: Embankment height ─────────────────────────────────────────────
    # Total bund height = water depth + freeboard (IS 5477 Part 4).
    embankment_height_m = round(water_depth_m + settings.freeboard_m, 2)

    # ── Step 6: Feasibility flags ─────────────────────────────────────────────
    # Will the pond fill within the wet season alone?
    fills_in_wet_season = wet_season_m3 >= live_storage_m3
    # Will the annual supply ever fall short of the live storage target?
    supply_deficit = annual_runoff_m3 < live_storage_m3

    _log.info(
        "Pond design: depth=%.2fm, bund_height=%.2fm, surface=%.0fm², "
        "live=%.0f m³, fills_wet=%s, deficit=%s",
        water_depth_m,
        embankment_height_m,
        surface_area_m2,
        live_storage_m3,
        fills_in_wet_season,
        supply_deficit,
    )

    return PondDesign(
        live_storage_m3=round(live_storage_m3, 1),
        dead_storage_m3=round(dead_storage_m3, 1),
        gross_storage_m3=round(gross_storage_m3, 1),
        total_storage_m3=round(total_storage_m3, 1),
        water_depth_m=water_depth_m,
        embankment_height_m=embankment_height_m,
        surface_area_m2=round(surface_area_m2, 1),
        embankment_top_width_m=settings.embankment_top_width_m,
        target_capture_fraction=settings.target_capture_fraction,
        freeboard_m=settings.freeboard_m,
        side_slope=2.0,  # Standard 2:1 H:V for rural earthen embankments
        shape_factor=settings.pond_shape_factor,
        evaporation_loss_fraction=settings.evaporation_loss_fraction,
        seepage_loss_fraction=settings.seepage_loss_fraction,
        topographic_storage_m3=round(topographic_storage_m3, 1),
        annual_runoff_m3=round(annual_runoff_m3, 1),
        constrained_by=constrained_by,
        fills_in_wet_season=fills_in_wet_season,
        supply_deficit=supply_deficit,
    )
