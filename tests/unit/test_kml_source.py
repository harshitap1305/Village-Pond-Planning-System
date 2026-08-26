"""
Unit and integration tests for KMLTerrainSource (Module 2).

Test structure:
  TestContourLineSchema     — Pydantic model validators
  TestKMLParsing            — core parsing logic using minimal inline KML
  TestKMZSupport            — zip extraction and KMZ-specific paths
  TestKMLErrors             — error cases (bad XML, empty KMZ, etc.)
  TestRealFixture           — integration test against tests/fixtures/contours_1m.kml
                              (skipped if fixture not present so CI doesn't break
                               on machines without the large file)
"""

import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from src.schemas.terrain import ContourLine
from src.terrain.base import TerrainSource
from src.terrain.exceptions import TerrainParseError
from src.terrain.kml_source import KMLTerrainSource

FIXTURE_PATH = Path("tests/fixtures/contours_1m.kml")

# ── Minimal KML fixtures (inline bytes — fast, no file I/O) ──────────────────

MINIMAL_KML = b"""<?xml version="1.0" encoding="UTF-8"?>
<Folder xmlns="http://www.opengis.net/kml/2.2">
  <Placemark>
    <name>280.0</name>
    <LineString>
      <coordinates>81.286,21.263 81.287,21.264 81.288,21.265</coordinates>
    </LineString>
  </Placemark>
  <Placemark>
    <name>281.0</name>
    <LineString>
      <coordinates>81.290,21.270 81.291,21.271 81.292,21.272</coordinates>
    </LineString>
  </Placemark>
</Folder>"""

# Mirrors the real file: lxml py:pytype namespace on name elements
PYTYPE_NAMESPACE_KML = b"""<?xml version="1.0" encoding="UTF-8"?>
<Folder xmlns="http://www.opengis.net/kml/2.2">
  <Placemark>
    <name xmlns:py="http://codespeak.net/lxml/objectify/pytype" py:pytype="str">277.0</name>
    <LineString>
      <coordinates>81.286,21.263 81.287,21.264 81.288,21.265</coordinates>
    </LineString>
  </Placemark>
</Folder>"""

# Contains one label Placemark (non-numeric name) and one valid contour
LABEL_PLACEMARK_KML = b"""<?xml version="1.0" encoding="UTF-8"?>
<Folder xmlns="http://www.opengis.net/kml/2.2">
  <Placemark>
    <name>ContourMapGenerator</name>
    <LineString>
      <coordinates>81.286,21.263 81.287,21.264</coordinates>
    </LineString>
  </Placemark>
  <Placemark>
    <name>280.0</name>
    <LineString>
      <coordinates>81.286,21.263 81.287,21.264 81.288,21.265</coordinates>
    </LineString>
  </Placemark>
</Folder>"""

# 3D coordinates — Z value should be silently ignored
THREE_D_COORDS_KML = b"""<?xml version="1.0" encoding="UTF-8"?>
<Folder xmlns="http://www.opengis.net/kml/2.2">
  <Placemark>
    <name>280.0</name>
    <LineString>
      <coordinates>81.286,21.263,280.0 81.287,21.264,280.0 81.288,21.265,280.0</coordinates>
    </LineString>
  </Placemark>
</Folder>"""

# Deeply nested — mimics the real file's Folder > Folder > Folder > Placemark structure
NESTED_KML = b"""<?xml version="1.0" encoding="UTF-8"?>
<Folder xmlns="http://www.opengis.net/kml/2.2">
  <name>ContourMapGenerator</name>
  <Folder>
    <name>contours_1.0m</name>
    <Folder>
      <name>lines</name>
      <Placemark>
        <name>280.0</name>
        <LineString>
          <coordinates>81.286,21.263 81.287,21.264 81.288,21.265</coordinates>
        </LineString>
      </Placemark>
    </Folder>
  </Folder>
</Folder>"""


# ── Helper ────────────────────────────────────────────────────────────────────


def make_kmz(kml_bytes: bytes, inner_name: str = "doc.kml") -> bytes:
    """Wrap KML bytes in an in-memory KMZ (ZIP) file."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner_name, kml_bytes)
    return buf.getvalue()


# ── Tests: ContourLine schema ─────────────────────────────────────────────────


class TestContourLineSchema:

    def test_valid_contour_line_created(self):
        c = ContourLine(elevation=280.0, points=[(81.286, 21.263), (81.287, 21.264)])
        assert c.elevation == 280.0
        assert len(c.points) == 2

    def test_rejects_single_point(self):
        with pytest.raises(ValueError, match="at least 2 points"):
            ContourLine(elevation=280.0, points=[(81.286, 21.263)])

    def test_rejects_empty_points(self):
        with pytest.raises(ValueError, match="at least 2 points"):
            ContourLine(elevation=280.0, points=[])

    def test_rejects_infinite_elevation(self):
        import math

        with pytest.raises(ValueError, match="finite"):
            ContourLine(elevation=math.inf, points=[(81.0, 21.0), (81.1, 21.1)])

    def test_rejects_nan_elevation(self):
        import math

        with pytest.raises(ValueError, match="finite"):
            ContourLine(elevation=math.nan, points=[(81.0, 21.0), (81.1, 21.1)])


# ── Tests: TerrainSource ABC ──────────────────────────────────────────────────


class TestTerrainSourceInterface:

    def test_kml_source_is_terrain_source(self):
        """KMLTerrainSource must implement the TerrainSource contract."""
        source = KMLTerrainSource(MINIMAL_KML, filename="test.kml")
        assert isinstance(source, TerrainSource)

    def test_cannot_instantiate_abstract_base(self):
        """TerrainSource itself must not be instantiable."""
        with pytest.raises(TypeError):
            TerrainSource()  # type: ignore


# ── Tests: core KML parsing ───────────────────────────────────────────────────


class TestKMLParsing:

    def test_parses_two_contours_from_minimal_kml(self):
        source = KMLTerrainSource(MINIMAL_KML, filename="test.kml")
        contours = source.extract_contours()
        assert len(contours) == 2

    def test_returns_contour_line_instances(self):
        source = KMLTerrainSource(MINIMAL_KML, filename="test.kml")
        contours = source.extract_contours()
        assert all(isinstance(c, ContourLine) for c in contours)

    def test_elevation_values_are_correct(self):
        source = KMLTerrainSource(MINIMAL_KML, filename="test.kml")
        contours = source.extract_contours()
        assert {c.elevation for c in contours} == {280.0, 281.0}

    def test_coordinate_order_is_lon_lat(self):
        source = KMLTerrainSource(MINIMAL_KML, filename="test.kml")
        contours = source.extract_contours()
        c = next(c for c in contours if c.elevation == 280.0)
        lon, lat = c.points[0]
        # Chhattisgarh area: lon ≈ 81, lat ≈ 21
        assert 80 < lon < 82, f"Expected lon ≈ 81, got {lon}"
        assert 20 < lat < 22, f"Expected lat ≈ 21, got {lat}"

    def test_point_count_is_correct(self):
        source = KMLTerrainSource(MINIMAL_KML, filename="test.kml")
        contours = source.extract_contours()
        c = next(c for c in contours if c.elevation == 280.0)
        assert len(c.points) == 3

    def test_handles_pytype_namespace_on_name_tag(self):
        """Elevation must parse correctly even when <name> has py:pytype attribute."""
        source = KMLTerrainSource(PYTYPE_NAMESPACE_KML, filename="test.kml")
        contours = source.extract_contours()
        assert len(contours) == 1
        assert contours[0].elevation == 277.0

    def test_non_numeric_name_placemark_skipped(self):
        """Placemarks with non-numeric names (labels) must be silently skipped."""
        source = KMLTerrainSource(LABEL_PLACEMARK_KML, filename="test.kml")
        contours = source.extract_contours()
        assert len(contours) == 1
        assert contours[0].elevation == 280.0

    def test_3d_coordinates_z_value_ignored(self):
        """Z component in coordinates is ignored; elevation always from <name>."""
        source = KMLTerrainSource(THREE_D_COORDS_KML, filename="test.kml")
        contours = source.extract_contours()
        assert len(contours) == 1
        assert contours[0].elevation == 280.0
        # Elevation from name, not from Z coord
        lon, lat = contours[0].points[0]
        assert lon == pytest.approx(81.286)
        assert lat == pytest.approx(21.263)

    def test_parses_deeply_nested_placemarks(self):
        """Parser must find Placemarks at any nesting depth."""
        source = KMLTerrainSource(NESTED_KML, filename="test.kml")
        contours = source.extract_contours()
        assert len(contours) == 1
        assert contours[0].elevation == 280.0

    def test_from_file_classmethod(self, tmp_path):
        kml_file = tmp_path / "test.kml"
        kml_file.write_bytes(MINIMAL_KML)
        source = KMLTerrainSource.from_file(kml_file)
        contours = source.extract_contours()
        assert len(contours) == 2

    def test_from_file_accepts_string_path(self, tmp_path):
        kml_file = tmp_path / "test.kml"
        kml_file.write_bytes(MINIMAL_KML)
        source = KMLTerrainSource.from_file(str(kml_file))  # string, not Path
        assert len(source.extract_contours()) == 2


# ── Tests: KMZ support ────────────────────────────────────────────────────────


class TestKMZSupport:

    def test_parses_kmz_with_doc_kml(self):
        kmz = make_kmz(MINIMAL_KML, "doc.kml")
        source = KMLTerrainSource(kmz, filename="test.kmz")
        contours = source.extract_contours()
        assert len(contours) == 2

    def test_parses_kmz_with_non_standard_kml_name(self):
        """KMZ where inner file is not named doc.kml — fallback to first .kml."""
        kmz = make_kmz(MINIMAL_KML, "contours.kml")
        source = KMLTerrainSource(kmz, filename="test.kmz")
        contours = source.extract_contours()
        assert len(contours) == 2

    def test_kmz_prefers_doc_kml_over_other_kml(self):
        """When both doc.kml and another .kml exist, doc.kml takes priority."""
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("other.kml", b"<Folder/>")  # empty, would give 0 contours
            zf.writestr("doc.kml", MINIMAL_KML)  # has 2 contours
        kmz = buf.getvalue()

        source = KMLTerrainSource(kmz, filename="test.kmz")
        contours = source.extract_contours()
        assert len(contours) == 2  # proves doc.kml was selected

    def test_kmz_elevation_values_preserved(self):
        kmz = make_kmz(MINIMAL_KML, "doc.kml")
        source = KMLTerrainSource(kmz, filename="test.kmz")
        contours = source.extract_contours()
        assert {c.elevation for c in contours} == {280.0, 281.0}


# ── Tests: error handling ─────────────────────────────────────────────────────


class TestKMLErrors:

    def test_raises_on_invalid_xml(self):
        with pytest.raises(TerrainParseError, match="could not be parsed"):
            source = KMLTerrainSource(b"not xml at all <<<", filename="bad.kml")
            source.extract_contours()

    def test_raises_on_truncated_xml(self):
        truncated = b"<?xml version='1.0'?><Folder xmlns='http://www.opengis.net/kml/2.2'><Place"
        with pytest.raises(TerrainParseError, match="could not be parsed"):
            source = KMLTerrainSource(truncated, filename="truncated.kml")
            source.extract_contours()

    def test_raises_on_kmz_with_no_kml(self):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("readme.txt", "nothing here")
        with pytest.raises(TerrainParseError, match="no .kml files"):
            KMLTerrainSource(buf.getvalue(), filename="empty.kmz")

    def test_raises_on_bad_zip_as_kmz(self):
        with pytest.raises(TerrainParseError, match="valid ZIP"):
            KMLTerrainSource(b"not a zip file", filename="fake.kmz")

    def test_empty_kml_returns_empty_list(self):
        """A valid KML with no Placemarks should return an empty list (not crash)."""
        empty_kml = b"""<?xml version="1.0"?>
<Folder xmlns="http://www.opengis.net/kml/2.2"/>"""
        source = KMLTerrainSource(empty_kml, filename="empty.kml")
        contours = source.extract_contours()
        assert contours == []


# ── Integration test against the real fixture ─────────────────────────────────


@pytest.mark.skipif(
    not FIXTURE_PATH.exists(),
    reason="Real fixture not available (tests/fixtures/contours_1m.kml)",
)
class TestRealFixture:
    """
    Integration tests against the actual contours_1m.kml provided for the project.
    These use hard-coded expected values because the fixture is a fixed file —
    if the parser returns different numbers, something is wrong.
    """

    @pytest.fixture(autouse=True)
    def parse_fixture(self):
        source = KMLTerrainSource.from_file(FIXTURE_PATH)
        self.contours = source.extract_contours()

    def test_correct_total_count(self):
        # 1355 LineString Placemarks = actual contour lines
        # 1355 Point Placemarks = elevation label dots (correctly skipped)
        # 2 other Placemarks = containing-folder labels (skipped)
        assert len(self.contours) == 1355

    def test_elevation_full_range(self):
        elevs = [c.elevation for c in self.contours]
        assert min(elevs) == 267.0
        assert max(elevs) == 298.0

    def test_all_terrain_elevations_present(self):
        """Every integer elevation from 267 to 298 must have at least one contour."""
        elevs = {c.elevation for c in self.contours}
        for expected in range(267, 299):
            assert float(expected) in elevs, f"Missing elevation {expected}.0 m"

    def test_unique_elevation_count(self):
        assert len({c.elevation for c in self.contours}) == 32

    def test_all_contours_have_minimum_two_points(self):
        failures = [c.elevation for c in self.contours if len(c.points) < 2]
        assert not failures, f"Contours with <2 points at elevations: {failures}"

    def test_all_coordinates_within_india_bounds(self):
        """Coarse geographic sanity: all points should be inside India's bounding box."""
        for contour in self.contours:
            for lon, lat in contour.points:
                assert 68 <= lon <= 97, f"lon {lon} outside India bounds"
                assert 8 <= lat <= 37, f"lat {lat} outside India bounds"

    def test_all_coordinates_are_two_element_tuples(self):
        for contour in self.contours:
            for point in contour.points:
                assert len(point) == 2
                assert isinstance(point[0], float)
                assert isinstance(point[1], float)

    def test_no_nan_coordinates(self):
        import math

        for contour in self.contours:
            for lon, lat in contour.points:
                assert math.isfinite(
                    lon
                ), f"NaN/inf longitude in contour {contour.elevation}"
                assert math.isfinite(
                    lat
                ), f"NaN/inf latitude in contour {contour.elevation}"
