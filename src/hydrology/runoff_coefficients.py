"""
Curve Number (CN) lookup table and derivation helpers for the SCS-CN runoff
estimation method.

The Curve Number encodes combined land use and soil hydrologic properties into
a single dimensionless parameter (0–100).  Higher CN = more runoff-prone.

Land cover categories and their HSG-indexed CN values follow:
  - USDA TR-55 (Technical Release 55, Urban Hydrology for Small Watersheds)
  - USDA NEH Part 630, Chapter 9 (Hydrologic Soil–Cover Complexes)
  - NRSC/ISRO IMSD Technical Guidelines for Indian Watershed Assessment
  - IS 5477 Part 1 (Methods for fixing capacities of low dams)

All CN values are for Antecedent Moisture Condition II (AMC-II — average
soil moisture, the standard design condition).  For long-run annual average
estimation, AMC variability averages out across 10 years of daily data, so
no per-event AMC adjustment is applied.

Hydrologic Soil Groups:
  A — High infiltration; deep, well-drained sands/gravels. (Lowest runoff)
  B — Moderate infiltration; moderately deep soils (laterite, red soil).
  C — Low infiltration; soils with impeding layers (black cotton soil).
  D — Very low infiltration; clay-heavy, high shrink-swell, shallow depth.

Typical Indian context:
  Most village sites in Chhattisgarh, MP, Maharashtra, Rajasthan fall in
  Group B (laterite, red loam) or Group C (black cotton soil / vertisols).
  Group B is used as the system default (conservative, well-documented).
"""

from __future__ import annotations

# ── CN lookup table ───────────────────────────────────────────────────────────
# Key: (land_cover_label, hsg)  →  CN (AMC-II)
# Sources: USDA TR-55 Table 2-2, NRSC IMSD Guidelines Table 6, IS 5477.
CN_TABLE: dict[tuple[str, str], int] = {
    # Mixed / rainfed agriculture (most common Indian village catchment)
    ("mixed_agriculture", "A"): 59,
    ("mixed_agriculture", "B"): 71,
    ("mixed_agriculture", "C"): 79,
    ("mixed_agriculture", "D"): 83,
    # Woodland / scrub forest (deciduous, moderate cover)
    ("woodland_scrub", "A"): 36,
    ("woodland_scrub", "B"): 60,
    ("woodland_scrub", "C"): 73,
    ("woodland_scrub", "D"): 79,
    # Grassland / pasture / fallow (fair hydrologic condition)
    ("grassland", "A"): 39,
    ("grassland", "B"): 61,
    ("grassland", "C"): 74,
    ("grassland", "D"): 80,
    # Built-up / residential / commercial (impervious fraction dominant)
    # CN values from TR-55 Table 2-2 for residential/commercial areas.
    ("built_up", "A"): 77,
    ("built_up", "B"): 85,
    ("built_up", "C"): 90,
    ("built_up", "D"): 92,
    # Rocky / barren / degraded land (thin or absent soil cover)
    ("rocky_barren", "A"): 45,
    ("rocky_barren", "B"): 66,
    ("rocky_barren", "C"): 77,
    ("rocky_barren", "D"): 83,
}

# ── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_LAND_COVER: str = "mixed_agriculture"
DEFAULT_HSG: str = "B"

# Fraction of bowl cells classified as built-up above which the catchment
# is treated as built-up dominant.  Below this, mixed_agriculture is used.
BUILTUP_THRESHOLD_FRACTION: float = 0.30

# Supported HSG codes (validated on input)
VALID_HSG: frozenset[str] = frozenset({"A", "B", "C", "D"})


def derive_curve_number(
    builtup_fraction: float = 0.0,
    hsg: str = DEFAULT_HSG,
) -> tuple[int, str]:
    """
    Determine the SCS Curve Number and land-cover label for a catchment.

    The land-cover category is inferred from the built-up fraction of bowl
    cells (computed from the Module 1 land exclusion mask).  No satellite
    land-cover map is required — this avoids adding a new external data
    dependency while still producing a physically meaningful CN adjustment
    when urban/peri-urban catchments are detected.

    Decision logic:
      - builtup_fraction > BUILTUP_THRESHOLD_FRACTION (30%) → "built_up"
      - Otherwise                                            → "mixed_agriculture"

    Args:
        builtup_fraction: Fraction of DEM cells in the bowl that were
                          classified as built-up by Module 1 (0.0–1.0).
        hsg:              Hydrologic Soil Group ("A", "B", "C", or "D").
                          Defaults to "B" (standard for Indian village sites).

    Returns:
        A (cn_value, land_cover_label) tuple, e.g. ``(71, "mixed_agriculture")``.

    Raises:
        ValueError: If ``hsg`` is not one of "A", "B", "C", "D".
    """
    hsg = hsg.upper().strip()
    if hsg not in VALID_HSG:
        raise ValueError(
            f"Invalid Hydrologic Soil Group '{hsg}'. "
            f"Must be one of {sorted(VALID_HSG)}."
        )

    land_cover = (
        "built_up"
        if builtup_fraction > BUILTUP_THRESHOLD_FRACTION
        else DEFAULT_LAND_COVER
    )
    cn = CN_TABLE[(land_cover, hsg)]
    return cn, land_cover
