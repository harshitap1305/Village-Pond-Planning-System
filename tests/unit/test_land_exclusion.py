"""
Unit tests for Module 1 — Land Suitability Hardening (Phase 3).

Tests cover:
  1. build_builtup_geometries — OSM XML parser for built-up land.
  2. Built-up polygon rasterization (reuses rasterize_water_mask).
  3. find_candidates bowl-footprint land veto (critical spatial distinction test).
  4. find_candidates rim slope constraint.

All tests use synthetic fixtures — no live Overpass call, no real KML file.
"""

import types

import numpy as np
from shapely.geometry import Polygon

from src.external.water.water_source import build_builtup_geometries
from src.geometry.water_mask import rasterize_water_mask

# ---------------------------------------------------------------------------
# Helpers — shared across test classes
# ---------------------------------------------------------------------------


def _fake_dem(shape=(20, 20), cell_size=10.0, origin_x=0.0, origin_y=200.0):
    """Minimal DEM-like namespace for rasterize_water_mask / find_candidates."""
    return types.SimpleNamespace(
        array=np.zeros(shape, dtype=np.float32),
        origin_x=origin_x,
        origin_y=origin_y,
        cell_size=cell_size,
        rows=shape[0],
        cols=shape[1],
        crs="EPSG:32644",
    )


def _make_xml(osm_id: int, tags: dict, coords: list) -> str:
    """Build a minimal OSM XML snippet with one way and its nodes."""
    xml_nodes = []
    for i, (lon, lat) in enumerate(coords):
        xml_nodes.append(f'<node id="{osm_id * 1000 + i}" lat="{lat}" lon="{lon}"/>')

    xml_tags = [f'<tag k="{k}" v="{v}"/>' for k, v in tags.items()]
    xml_nds = [f'<nd ref="{osm_id * 1000 + i}"/>' for i in range(len(coords))]

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<osm version="0.6">'
        + "".join(xml_nodes)
        + f'<way id="{osm_id}">'
        + "".join(xml_nds)
        + "".join(xml_tags)
        + "</way>"
        + "</osm>"
    )


_SQUARE_COORDS = [(80.0, 21.0), (80.1, 21.0), (80.1, 21.1), (80.0, 21.1), (80.0, 21.0)]


# ---------------------------------------------------------------------------
# 1. TestBuildBuiltupGeometries — parser unit tests
# ---------------------------------------------------------------------------


class TestBuildBuiltupGeometries:
    """Verify that the OSM built-up parser includes and excludes the right tags."""

    def test_building_house_returns_polygon(self):
        xml = _make_xml(1, {"building": "house"}, _SQUARE_COORDS)
        geoms = build_builtup_geometries(xml)
        assert len(geoms) == 1
        assert geoms[0].geom_type == "Polygon"

    def test_building_yes_returns_polygon(self):
        xml = _make_xml(2, {"building": "yes"}, _SQUARE_COORDS)
        geoms = build_builtup_geometries(xml)
        assert len(geoms) == 1

    def test_building_school_returns_polygon(self):
        xml = _make_xml(3, {"building": "school"}, _SQUARE_COORDS)
        geoms = build_builtup_geometries(xml)
        assert len(geoms) == 1

    def test_landuse_residential_returns_polygon(self):
        xml = _make_xml(4, {"landuse": "residential"}, _SQUARE_COORDS)
        geoms = build_builtup_geometries(xml)
        assert len(geoms) == 1

    def test_landuse_commercial_returns_polygon(self):
        xml = _make_xml(5, {"landuse": "commercial"}, _SQUARE_COORDS)
        geoms = build_builtup_geometries(xml)
        assert len(geoms) == 1

    def test_landuse_cemetery_returns_polygon(self):
        xml = _make_xml(6, {"landuse": "cemetery"}, _SQUARE_COORDS)
        geoms = build_builtup_geometries(xml)
        assert len(geoms) == 1, "Cemetery should be excluded (culturally incompatible)"

    def test_landuse_farmyard_not_returned(self):
        """Farmyard is open land — should NOT be excluded."""
        xml = _make_xml(7, {"landuse": "farmyard"}, _SQUARE_COORDS)
        geoms = build_builtup_geometries(xml)
        assert len(geoms) == 0, "Farmyard should not be in the exclusion list"

    def test_landuse_farm_not_returned(self):
        """Agricultural land is the target setting — should NOT be excluded."""
        xml = _make_xml(8, {"landuse": "farm"}, _SQUARE_COORDS)
        geoms = build_builtup_geometries(xml)
        assert len(geoms) == 0

    def test_highway_not_returned(self):
        xml = _make_xml(9, {"highway": "primary"}, _SQUARE_COORDS[:3])
        geoms = build_builtup_geometries(xml)
        assert len(geoms) == 0

    def test_natural_water_not_returned(self):
        """Water features belong to build_water_geometries, not here."""
        xml = _make_xml(10, {"natural": "water"}, _SQUARE_COORDS)
        geoms = build_builtup_geometries(xml)
        assert len(geoms) == 0

    def test_way_with_only_two_coords_skipped(self):
        """A two-point way cannot form a polygon — must be skipped."""
        xml = _make_xml(11, {"building": "yes"}, [(80.0, 21.0), (80.1, 21.0)])
        geoms = build_builtup_geometries(xml)
        assert len(geoms) == 0

    def test_empty_xml_returns_empty(self):
        xml = '<?xml version="1.0" encoding="UTF-8"?><osm version="0.6"></osm>'
        geoms = build_builtup_geometries(xml)
        assert geoms == []

    def test_malformed_xml_returns_empty(self):
        geoms = build_builtup_geometries("<this is not xml")
        assert geoms == []

    def test_building_no_returns_empty(self):
        """building=no means it's not a building, should be excluded."""
        xml = _make_xml(12, {"building": "no"}, _SQUARE_COORDS)
        geoms = build_builtup_geometries(xml)
        assert len(geoms) == 0

    def test_building_false_returns_empty(self):
        """building=false means it's not a building, should be excluded."""
        xml = _make_xml(13, {"building": "false"}, _SQUARE_COORDS)
        geoms = build_builtup_geometries(xml)
        assert len(geoms) == 0


# ---------------------------------------------------------------------------
# 2. TestBuiltupRasterization — smoke test reusing rasterize_water_mask
# ---------------------------------------------------------------------------


class TestBuiltupRasterization:
    """Built-up polygons rasterize onto the DEM grid correctly."""

    def test_building_polygon_masks_cells(self):
        """A building polygon covering part of the grid should mask those cells."""
        dem = _fake_dem(shape=(10, 10), cell_size=10.0, origin_x=0.0, origin_y=100.0)
        # Polygon covering the top-left 4×4 cells (40m × 40m)
        building = Polygon([(-5, 55), (35, 55), (35, 105), (-5, 105)])
        mask = rasterize_water_mask([building], dem)
        assert mask.sum() > 0, "Some cells should be masked by the building polygon"
        assert mask.sum() < mask.size, "Not all cells should be masked"


# ---------------------------------------------------------------------------
# 3. TestFindCandidatesLandVeto — critical spatial distinction test
# ---------------------------------------------------------------------------


class TestFindCandidatesLandVeto:
    """
    Prove that the land mask veto applies ONLY to the bowl footprint, not to
    the upstream catchment cells. This is the key engineering insight: built-up
    land in the catchment is fine; built-up land in the bowl itself is not.
    """

    def _make_bowl_dem(self):
        """30×30 DEM with a single central bowl (cells 12:18, 12:18)."""
        from src.schemas.dem import DEM

        array = np.full((30, 30), 285.0, dtype=np.float32)
        array[12:18, 12:18] = 284.5  # bowl interior, 0.5m depth
        raw_dem = DEM(
            array=array, origin_x=0.0, origin_y=60.0, cell_size=2.0, crs="EPSG:32644"
        )
        filled_arr = array.copy()
        filled_arr[12:18, 12:18] = 285.0
        filled_dem = DEM(
            array=filled_arr,
            origin_x=0.0,
            origin_y=60.0,
            cell_size=2.0,
            crs="EPSG:32644",
        )
        return raw_dem, filled_dem

    def _relax_thresholds(self, monkeypatch):
        from src.catchment import candidates as cand_module

        monkeypatch.setattr(cand_module.settings, "min_catchment_area_ha", 0.0)
        monkeypatch.setattr(cand_module.settings, "min_depression_area_sqm", 0.0)
        monkeypatch.setattr(cand_module.settings, "min_depression_depth_m", 0.05)
        monkeypatch.setattr(cand_module.settings, "max_dam_site_slope_deg", 90.0)

    def test_bowl_found_with_no_land_mask(self, monkeypatch):
        """Baseline: with no land mask, the bowl is found."""
        from src.catchment.candidates import find_candidates

        self._relax_thresholds(monkeypatch)
        raw_dem, filled_dem = self._make_bowl_dem()
        candidates, *_ = find_candidates(raw_dem, filled_dem, land_mask=None)
        assert len(candidates) > 0

    def test_bowl_vetoed_when_land_mask_covers_bowl(self, monkeypatch):
        """Bowl overlapping the land mask must be vetoed."""
        from src.catchment.candidates import find_candidates

        self._relax_thresholds(monkeypatch)
        raw_dem, filled_dem = self._make_bowl_dem()

        # Land mask covers the bowl footprint
        land_mask = np.zeros((30, 30), dtype=bool)
        land_mask[12:18, 12:18] = True  # exactly the bowl cells

        candidates, *_ = find_candidates(raw_dem, filled_dem, land_mask=land_mask)
        assert (
            len(candidates) == 0
        ), "Bowl overlapping the built-up land mask should be vetoed"

    def test_bowl_NOT_vetoed_when_land_mask_covers_only_catchment(self, monkeypatch):
        """
        CRITICAL: land mask covering upstream cells (not the bowl) must NOT
        veto the candidate. This proves the spatial distinction is implemented
        correctly — the veto is bowl-footprint-only.
        """
        from src.catchment.candidates import find_candidates

        self._relax_thresholds(monkeypatch)
        raw_dem, filled_dem = self._make_bowl_dem()

        # Land mask covers upstream catchment rows only — NOT the bowl rows 12-17
        land_mask = np.zeros((30, 30), dtype=bool)
        land_mask[0:10, :] = True  # top rows — upstream of the bowl

        candidates, *_ = find_candidates(raw_dem, filled_dem, land_mask=land_mask)
        assert len(candidates) > 0, (
            "Land mask covering only upstream catchment cells should NOT veto "
            "the bowl — built-up land in the catchment is acceptable."
        )


# ---------------------------------------------------------------------------
# 4. TestFindCandidatesSlopeVeto — dam wall slope constraint
# ---------------------------------------------------------------------------


class TestFindCandidatesSlopeVeto:
    """
    Prove that the slope veto checks only the BOUNDARY RING (rim) cells,
    not the bowl interior. Steep interior, gentle rim → candidate survives.
    Gentle interior, steep rim → candidate vetoed.
    """

    def _make_bowl_raw_and_filled(self):
        from src.schemas.dem import DEM

        array = np.full((30, 30), 285.0, dtype=np.float32)
        array[12:18, 12:18] = 284.5
        raw_dem = DEM(
            array=array, origin_x=0.0, origin_y=60.0, cell_size=2.0, crs="EPSG:32644"
        )
        filled_arr = array.copy()
        filled_arr[12:18, 12:18] = 285.0
        filled_dem = DEM(
            array=filled_arr,
            origin_x=0.0,
            origin_y=60.0,
            cell_size=2.0,
            crs="EPSG:32644",
        )
        return raw_dem, filled_dem

    def _relax_thresholds(self, monkeypatch, max_slope_deg):
        from src.catchment import candidates as cand_module

        monkeypatch.setattr(cand_module.settings, "min_catchment_area_ha", 0.0)
        monkeypatch.setattr(cand_module.settings, "min_depression_area_sqm", 0.0)
        monkeypatch.setattr(cand_module.settings, "min_depression_depth_m", 0.05)
        monkeypatch.setattr(
            cand_module.settings, "max_dam_site_slope_deg", max_slope_deg
        )

    def test_bowl_found_when_rim_slope_within_limit(self, monkeypatch):
        from src.catchment.candidates import find_candidates

        self._relax_thresholds(monkeypatch, max_slope_deg=90.0)  # effectively disabled
        raw_dem, filled_dem = self._make_bowl_raw_and_filled()

        # Flat slope everywhere — well within any reasonable limit
        slope = np.full((30, 30), 2.0, dtype=np.float32)

        candidates, *_ = find_candidates(raw_dem, filled_dem, slope_deg=slope)
        assert len(candidates) > 0

    def test_bowl_vetoed_when_rim_slope_exceeds_limit(self, monkeypatch):
        from src.catchment.candidates import find_candidates

        self._relax_thresholds(monkeypatch, max_slope_deg=20.0)
        raw_dem, filled_dem = self._make_bowl_raw_and_filled()

        # Very steep slope everywhere — rim will exceed 20°
        slope = np.full((30, 30), 45.0, dtype=np.float32)

        candidates, *_ = find_candidates(raw_dem, filled_dem, slope_deg=slope)
        assert (
            len(candidates) == 0
        ), "Bowl with rim slope > max_dam_site_slope_deg should be vetoed"

    def test_bowl_NOT_vetoed_when_only_interior_steep(self, monkeypatch):
        """
        CRITICAL: steep slope INSIDE the bowl interior must NOT trigger the veto.
        Only the boundary ring (dam wall) slope is checked.
        """
        from src.catchment.candidates import find_candidates

        self._relax_thresholds(monkeypatch, max_slope_deg=20.0)
        raw_dem, filled_dem = self._make_bowl_raw_and_filled()

        # Gentle slope everywhere except the interior bowl cells (rows 12:18, cols 12:18)
        slope = np.full((30, 30), 5.0, dtype=np.float32)
        slope[12:18, 12:18] = 45.0  # steep INSIDE the bowl — should be ignored

        candidates, *_ = find_candidates(raw_dem, filled_dem, slope_deg=slope)
        assert len(candidates) > 0, (
            "Steep slope inside bowl interior should NOT trigger the rim slope veto — "
            "only the boundary ring (embankment) cells are checked."
        )

    def test_slope_none_skips_check(self, monkeypatch):
        """Passing slope_deg=None must skip the slope filter entirely."""
        from src.catchment.candidates import find_candidates

        # Very strict threshold — would veto everything if slope were checked
        self._relax_thresholds(monkeypatch, max_slope_deg=0.01)
        raw_dem, filled_dem = self._make_bowl_raw_and_filled()

        candidates, *_ = find_candidates(raw_dem, filled_dem, slope_deg=None)
        assert (
            len(candidates) > 0
        ), "slope_deg=None should skip the slope filter completely"
