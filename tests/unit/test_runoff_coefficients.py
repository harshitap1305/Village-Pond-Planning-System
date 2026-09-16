"""
Unit tests for src/hydrology/runoff_coefficients.py
"""

import pytest

from src.hydrology.runoff_coefficients import (
    BUILTUP_THRESHOLD_FRACTION,
    CN_TABLE,
    VALID_HSG,
    derive_curve_number,
)


def test_cn_table_has_all_categories():
    """5 land types × 4 soil groups = 20 entries."""
    land_covers = {
        "mixed_agriculture",
        "woodland_scrub",
        "grassland",
        "built_up",
        "rocky_barren",
    }
    hsgs = {"A", "B", "C", "D"}
    for lc in land_covers:
        for hsg in hsgs:
            assert (lc, hsg) in CN_TABLE, f"Missing CN for ({lc!r}, {hsg!r})"


def test_default_cn_is_71():
    """Default inputs (0% built-up, HSG B) → mixed_agriculture + B → CN=71."""
    cn, land_cover = derive_curve_number(builtup_fraction=0.0, hsg="B")
    assert cn == 71
    assert land_cover == "mixed_agriculture"


def test_builtup_catchment_detected():
    """builtup_fraction > threshold (30%) → land_cover='built_up', CN=85 for HSG B."""
    cn, land_cover = derive_curve_number(builtup_fraction=0.35, hsg="B")
    assert land_cover == "built_up"
    assert cn == 85


def test_non_builtup_catchment():
    """builtup_fraction well below threshold → mixed_agriculture category."""
    cn, land_cover = derive_curve_number(builtup_fraction=0.10, hsg="B")
    assert land_cover == "mixed_agriculture"
    assert cn == 71


def test_threshold_exact_boundary():
    """Exactly at threshold is NOT above it — still mixed_agriculture."""
    cn, land_cover = derive_curve_number(
        builtup_fraction=BUILTUP_THRESHOLD_FRACTION, hsg="B"
    )
    assert land_cover == "mixed_agriculture"


def test_hsg_a_gives_lower_cn_than_hsg_d():
    """HSG A (sandy, well-drained) always produces lower CN than HSG D (clay)."""
    cn_a, _ = derive_curve_number(builtup_fraction=0.0, hsg="A")
    cn_d, _ = derive_curve_number(builtup_fraction=0.0, hsg="D")
    assert cn_a < cn_d


def test_invalid_hsg_raises_value_error():
    with pytest.raises(ValueError, match="Invalid Hydrologic Soil Group"):
        derive_curve_number(builtup_fraction=0.0, hsg="Z")


def test_hsg_case_insensitive():
    """'b' and 'B' should produce the same CN."""
    cn_lower, _ = derive_curve_number(builtup_fraction=0.0, hsg="b")
    cn_upper, _ = derive_curve_number(builtup_fraction=0.0, hsg="B")
    assert cn_lower == cn_upper


def test_all_valid_hsg_accepted():
    for hsg in VALID_HSG:
        cn, _ = derive_curve_number(builtup_fraction=0.0, hsg=hsg)
        assert 0 < cn <= 100
