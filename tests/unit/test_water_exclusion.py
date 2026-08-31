"""
Unit tests for the water exclusion mask layer.

All tests use synthetic geometries and DEM objects — no live Overpass call,
no real KML file. The goal is to prove that:

  1. rasterize_water_mask burns geometries correctly onto the grid.
  2. flat_area_heuristic_mask flags large flat regions only.
  3. find_candidates hard-vetoes bowls that overlap the water mask.
  4. build_water_geometries correctly handles all OSM tag families.
"""

import types

import numpy as np
from shapely.geometry import LineString, Polygon

from src.external.water.water_source import build_water_geometries
from src.geometry.water_mask import flat_area_heuristic_mask, rasterize_water_mask


# ---------------------------------------------------------------------------
# Helpers — tiny fake objects so we don't need real DEM files
# ---------------------------------------------------------------------------
def _fake_dem(shape=(20, 20), cell_size=10.0, origin_x=0.0, origin_y=200.0):
    """Return a minimal DEM-like namespace sufficient for rasterize_water_mask."""
    dem = types.SimpleNamespace(
        array=np.zeros(shape, dtype=np.float32),
        origin_x=origin_x,
        origin_y=origin_y,
        cell_size=cell_size,
        rows=shape[0],
        cols=shape[1],
        crs="EPSG:32644",
    )
    return dem


def _fake_settings(**kwargs):
    """Return a minimal settings namespace."""
    defaults = dict(
        veto_minor_waterways=True,
        water_buffer_margin_m=5.0,
        default_river_width_m=15.0,
        default_stream_width_m=3.0,
        default_canal_width_m=8.0,
        default_drain_width_m=1.5,
    )
    defaults.update(kwargs)
    return types.SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# rasterize_water_mask
# ---------------------------------------------------------------------------
class TestRasterizeWaterMask:
    def test_empty_geoms_returns_all_false(self):
        dem = _fake_dem()
        mask = rasterize_water_mask([], dem)
        assert mask.dtype == bool
        assert mask.shape == dem.array.shape
        assert not mask.any()

    def test_polygon_covering_whole_grid_masks_everything(self):
        dem = _fake_dem(shape=(10, 10), cell_size=10.0, origin_x=0.0, origin_y=100.0)
        # Polygon that covers the entire 100x100 m grid (with slight overshoot)
        big_poly = Polygon([(-5, -5), (105, -5), (105, 105), (-5, 105)])
        mask = rasterize_water_mask([big_poly], dem)
        assert mask.all(), "Every cell should be masked"

    def test_small_polygon_masks_subset(self):
        # 20×20 m DEM (2m cells) — polygon in the middle
        dem = _fake_dem(shape=(10, 10), cell_size=2.0, origin_x=0.0, origin_y=20.0)
        # Small polygon around grid centre (rows 4-6, cols 4-6)
        center_poly = Polygon([(8, 8), (12, 8), (12, 12), (8, 12)])
        mask = rasterize_water_mask([center_poly], dem)
        assert mask.sum() > 0
        assert mask.sum() < mask.size

    def test_linestring_after_buffering_creates_mask(self):
        """Test that a buffered LineString (already a Polygon) masks cells."""
        dem = _fake_dem(shape=(20, 20), cell_size=10.0, origin_x=0.0, origin_y=200.0)
        river_line = LineString([(0, 100), (200, 100)])
        river_buffered = river_line.buffer(15)  # already in metric coords
        mask = rasterize_water_mask([river_buffered], dem)
        assert mask.sum() > 0


# ---------------------------------------------------------------------------
# flat_area_heuristic_mask
# ---------------------------------------------------------------------------
class TestFlatAreaHeuristicMask:
    def test_no_large_flat_region_returns_empty(self):
        # Uniformly steep slope — nothing should be flagged
        slope = np.full((20, 20), 5.0)
        mask = flat_area_heuristic_mask(slope, cell_size=10.0, min_area_ha=0.5)
        assert not mask.any()

    def test_large_flat_region_is_flagged(self):
        # 10×10 cells of 0° slope in a 20×20 grid at 10m resolution → 1 ha
        slope = np.full((20, 20), 5.0)
        slope[5:15, 5:15] = 0.0
        mask = flat_area_heuristic_mask(slope, cell_size=10.0, min_area_ha=0.5)
        # The central flat patch (100 cells × 100 m² = 1 ha) should be flagged
        assert mask[10, 10], "Central flat cell should be masked"
        assert not mask[0, 0], "Steep corner cell should not be masked"

    def test_small_flat_region_below_threshold_is_ignored(self):
        slope = np.full((20, 20), 5.0)
        slope[9:11, 9:11] = 0.0  # 4 cells × 100 m² = 400 m² = 0.04 ha
        mask = flat_area_heuristic_mask(slope, cell_size=10.0, min_area_ha=0.5)
        assert not mask.any(), "Tiny flat patch below min_area_ha should not be flagged"


# ---------------------------------------------------------------------------
# build_water_geometries
# ---------------------------------------------------------------------------
class TestBuildWaterGeometries:
    def _make_xml(self, osm_id, tags, coords):
        xml_nodes = []
        for i, (lon, lat) in enumerate(coords):
            xml_nodes.append(f'<node id="{osm_id*1000+i}" lat="{lat}" lon="{lon}"/>')

        xml_tags = []
        for k, v in tags.items():
            xml_tags.append(f'<tag k="{k}" v="{v}"/>')

        xml_nds = []
        for i in range(len(coords)):
            xml_nds.append(f'<nd ref="{osm_id*1000+i}"/>')

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6">
    {"".join(xml_nodes)}
    <way id="{osm_id}">
        {"".join(xml_nds)}
        {"".join(xml_tags)}
    </way>
</osm>"""

    def test_natural_water_polygon_parsed(self):
        xml = self._make_xml(
            1,
            {"natural": "water", "water": "lake"},
            [(80.0, 21.0), (80.1, 21.0), (80.1, 21.1), (80.0, 21.1)],
        )
        geoms = build_water_geometries(xml, _fake_settings())
        assert len(geoms) == 1
        geom, label = geoms[0]
        assert geom.geom_type == "Polygon"
        assert label == "lake"

    def test_waterway_river_linestring_parsed(self):
        xml = self._make_xml(
            2,
            {"waterway": "river"},
            [(80.0, 21.0), (80.1, 21.0), (80.2, 20.9)],
        )
        geoms = build_water_geometries(xml, _fake_settings())
        assert len(geoms) == 1
        geom, label = geoms[0]
        assert geom.geom_type == "LineString"
        assert label == "waterway:river"

    def test_minor_waterway_skipped_when_veto_false(self):
        xml = self._make_xml(
            3,
            {"waterway": "stream"},
            [(80.0, 21.0), (80.05, 21.0)],
        )
        settings = _fake_settings(veto_minor_waterways=False)
        geoms = build_water_geometries(xml, settings)
        assert len(geoms) == 0

    def test_minor_waterway_included_when_veto_true(self):
        xml = self._make_xml(
            4,
            {"waterway": "stream"},
            [(80.0, 21.0), (80.05, 21.0)],
        )
        settings = _fake_settings(veto_minor_waterways=True)
        geoms = build_water_geometries(xml, settings)
        assert len(geoms) == 1

    def test_unknown_tags_ignored(self):
        xml = self._make_xml(
            5,
            {"highway": "primary"},
            [(80.0, 21.0), (80.1, 21.1)],
        )
        geoms = build_water_geometries(xml, _fake_settings())
        assert len(geoms) == 0


# ---------------------------------------------------------------------------
# find_candidates water mask hard veto
# ---------------------------------------------------------------------------
class TestFindCandidatesWaterVeto:
    """
    Integration-style test: build a synthetic DEM that has exactly one
    clearly-identifiable depression. Confirm that:
    - Without a water mask, the depression is found.
    - With a water mask covering it, it is vetoed.
    """

    def _make_bowl_dem(self):
        """
        Return (raw_dem, filled_dem) for a 30×30 grid with a single central bowl.
        The bowl is 6×6 cells centred at (12:18, 12:18), depth 0.5 m.
        """
        from src.schemas.dem import DEM

        array = np.full((30, 30), 285.0, dtype=np.float32)
        # Create a bowl by lowering the centre
        array[12:18, 12:18] = 284.5
        # Ensure no edge contact
        raw_dem = DEM(
            array=array,
            origin_x=0.0,
            origin_y=60.0,
            cell_size=2.0,
            crs="EPSG:32644",
        )
        # filled_dem = same but bowl is raised back to 285
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

    def test_bowl_found_without_water_mask(self, monkeypatch):
        from src.catchment import candidates as cand_module
        from src.catchment.candidates import find_candidates

        # Relax all area/depth thresholds so the toy 6×6 bowl passes every filter
        monkeypatch.setattr(cand_module.settings, "min_catchment_area_ha", 0.0)
        monkeypatch.setattr(cand_module.settings, "min_depression_area_sqm", 0.0)
        monkeypatch.setattr(cand_module.settings, "min_depression_depth_m", 0.05)

        raw_dem, filled_dem = self._make_bowl_dem()
        candidates, *_ = find_candidates(raw_dem, filled_dem, water_mask=None)
        assert len(candidates) > 0, "Should find the central bowl with no water mask"

    def test_bowl_vetoed_with_water_mask_covering_it(self, monkeypatch):
        from src.catchment import candidates as cand_module
        from src.catchment.candidates import find_candidates

        monkeypatch.setattr(cand_module.settings, "min_catchment_area_ha", 0.0)
        monkeypatch.setattr(cand_module.settings, "min_depression_area_sqm", 0.0)
        monkeypatch.setattr(cand_module.settings, "min_depression_depth_m", 0.05)

        raw_dem, filled_dem = self._make_bowl_dem()
        # Mask covers the entire bowl region
        water_mask = np.zeros((30, 30), dtype=bool)
        water_mask[12:18, 12:18] = True
        candidates, *_ = find_candidates(raw_dem, filled_dem, water_mask=water_mask)
        assert len(candidates) == 0, "Bowl overlapping water mask should be vetoed"
