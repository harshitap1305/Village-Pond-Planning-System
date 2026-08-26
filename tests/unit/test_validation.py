"""
Validation tests for Module 3 — Input Validation & File Upload Handling.

Test structure:
  TestExceptionHierarchy  — class inheritance and catch-all behaviour
  TestValidateFile        — extension and size checks
  TestValidateContours    — semantic DEM-readiness checks
  TestKMLSourceExceptions — KMLTerrainSource raises typed exceptions (not ValueError)
  TestFixtureFiles        — integration tests against the 4 broken fixture files
"""

import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from src.schemas.terrain import ContourLine
from src.terrain.exceptions import (
    FileTooLargeError,
    InvalidGeometryError,
    TerrainError,
    TerrainParseError,
    UnsupportedFormatError,
)
from src.terrain.kml_source import KMLTerrainSource
from src.terrain.validators import validate_contours, validate_file

FIXTURES = Path("tests/fixtures")


# ── Helper ────────────────────────────────────────────────────────────────────


def make_contour(
    elevation: float, n_points: int = 3, offset: float = 0.0
) -> ContourLine:
    """Build a ContourLine at a slightly different location per offset."""
    pts = [
        (81.0 + offset + i * 0.001, 21.0 + offset + i * 0.001) for i in range(n_points)
    ]
    return ContourLine(elevation=elevation, points=pts)


def make_spread_contours(elevations: list) -> list:
    """
    Build contours spread far enough apart to pass the spatial-extent check.
    Each contour is spaced 0.01 degrees apart (≈ 1 km).
    """
    return [make_contour(float(e), offset=i * 0.01) for i, e in enumerate(elevations)]


# ── Exception hierarchy ───────────────────────────────────────────────────────


class TestExceptionHierarchy:

    def test_terrain_error_is_exception(self):
        assert issubclass(TerrainError, Exception)

    def test_all_subclasses_inherit_from_terrain_error(self):
        for cls in (
            TerrainParseError,
            InvalidGeometryError,
            UnsupportedFormatError,
            FileTooLargeError,
        ):
            assert issubclass(cls, TerrainError), f"{cls.__name__} not a TerrainError"

    def test_catch_all_with_terrain_error(self):
        """A single except TerrainError must catch all subtypes."""
        for cls in (
            TerrainParseError,
            InvalidGeometryError,
            UnsupportedFormatError,
            FileTooLargeError,
        ):
            with pytest.raises(TerrainError):
                raise cls("test")

    def test_subclasses_are_also_exceptions(self):
        for cls in (
            TerrainParseError,
            InvalidGeometryError,
            UnsupportedFormatError,
            FileTooLargeError,
        ):
            assert issubclass(cls, Exception)

    def test_exception_message_preserved(self):
        exc = TerrainParseError("custom message here")
        assert "custom message here" in str(exc)

    def test_subclasses_are_distinct(self):
        """Ensure you can distinguish between error types."""
        assert TerrainParseError is not InvalidGeometryError
        assert UnsupportedFormatError is not FileTooLargeError


# ── validate_file() ───────────────────────────────────────────────────────────


class TestValidateFile:

    # ── Accepted formats ──────────────────────────────────────────────────────

    def test_accepts_lowercase_kml(self):
        validate_file("contours.kml", 100)

    def test_accepts_lowercase_kmz(self):
        validate_file("contours.kmz", 100)

    def test_accepts_uppercase_kml(self):
        validate_file("CONTOURS.KML", 100)

    def test_accepts_uppercase_kmz(self):
        validate_file("contours.KMZ", 100)

    def test_accepts_mixed_case(self):
        validate_file("Contours.Kml", 100)

    def test_accepts_file_with_dots_in_name(self):
        validate_file("my.terrain.data.kml", 100)

    def test_accepts_zero_byte_file(self):
        """Extension check must pass even for empty file (parser will catch the error)."""
        validate_file("data.kml", 0)

    # ── Rejected formats ──────────────────────────────────────────────────────

    def test_rejects_txt(self):
        with pytest.raises(UnsupportedFormatError):
            validate_file("data.txt", 100)

    def test_rejects_csv(self):
        with pytest.raises(UnsupportedFormatError):
            validate_file("contours.csv", 100)

    def test_rejects_geotiff(self):
        with pytest.raises(UnsupportedFormatError):
            validate_file("dem.tif", 100)

    def test_rejects_shapefile(self):
        with pytest.raises(UnsupportedFormatError):
            validate_file("contours.shp", 100)

    def test_rejects_no_extension(self):
        with pytest.raises(UnsupportedFormatError):
            validate_file("contours", 100)

    def test_error_message_mentions_bad_extension(self):
        with pytest.raises(UnsupportedFormatError, match=r"\.csv"):
            validate_file("data.csv", 100)

    def test_error_message_mentions_accepted_formats(self):
        with pytest.raises(UnsupportedFormatError, match=r"\.kml"):
            validate_file("data.csv", 100)

    # ── Size checks ───────────────────────────────────────────────────────────

    def test_accepts_file_at_exact_limit(self):
        """Exactly 20 MB should be accepted (inclusive boundary)."""
        validate_file("contours.kml", 20 * 1024 * 1024)

    def test_rejects_file_one_byte_over_limit(self):
        with pytest.raises(FileTooLargeError):
            validate_file("contours.kml", 20 * 1024 * 1024 + 1)

    def test_rejects_very_large_file(self):
        with pytest.raises(FileTooLargeError):
            validate_file("contours.kml", 100 * 1024 * 1024)

    def test_error_message_mentions_actual_size(self):
        with pytest.raises(FileTooLargeError, match="25.0 MB"):
            validate_file("contours.kml", 25 * 1024 * 1024)

    def test_error_message_mentions_limit(self):
        with pytest.raises(FileTooLargeError, match="20 MB"):
            validate_file("contours.kml", 25 * 1024 * 1024)

    def test_file_too_large_is_terrain_error(self):
        with pytest.raises(TerrainError):
            validate_file("contours.kml", 25 * 1024 * 1024)

    def test_unsupported_format_is_terrain_error(self):
        with pytest.raises(TerrainError):
            validate_file("data.csv", 100)


# ── validate_contours() ───────────────────────────────────────────────────────


class TestValidateContours:

    # ── Happy paths ───────────────────────────────────────────────────────────

    def test_accepts_minimal_valid_pair(self):
        contours = make_spread_contours([280.0, 281.0])
        validate_contours(contours)  # must not raise

    def test_accepts_many_contours(self):
        contours = make_spread_contours(list(range(267, 299)))
        validate_contours(contours)

    def test_accepts_non_integer_elevations(self):
        contours = make_spread_contours([280.5, 281.5])
        validate_contours(contours)

    def test_accepts_duplicate_elevations_if_third_differs(self):
        """Two contours at same elevation is fine as long as a third differs."""
        contours = make_spread_contours([280.0, 280.0, 281.0])
        validate_contours(contours)

    # ── Count check ───────────────────────────────────────────────────────────

    def test_rejects_empty_list(self):
        with pytest.raises(InvalidGeometryError, match="At least 2"):
            validate_contours([])

    def test_rejects_single_contour(self):
        with pytest.raises(InvalidGeometryError, match="got 1"):
            validate_contours([make_contour(280.0)])

    def test_error_is_invalid_geometry_error(self):
        with pytest.raises(InvalidGeometryError):
            validate_contours([])

    def test_invalid_geometry_error_is_terrain_error(self):
        with pytest.raises(TerrainError):
            validate_contours([])

    # ── Elevation variety check ───────────────────────────────────────────────

    def test_rejects_two_contours_same_elevation(self):
        contours = make_spread_contours([280.0, 280.0])
        with pytest.raises(InvalidGeometryError, match="flat surface"):
            validate_contours(contours)

    def test_rejects_many_contours_same_elevation(self):
        contours = make_spread_contours([280.0] * 10)
        with pytest.raises(InvalidGeometryError, match="flat surface"):
            validate_contours(contours)

    def test_error_message_mentions_elevation_value(self):
        contours = make_spread_contours([280.0, 280.0])
        with pytest.raises(InvalidGeometryError, match="280.0"):
            validate_contours(contours)

    # ── Spatial extent check ──────────────────────────────────────────────────

    def test_rejects_single_point_contours(self):
        """All points at exactly the same location → zero bbox."""
        c1 = ContourLine(elevation=280.0, points=[(81.286, 21.263), (81.286, 21.263)])
        c2 = ContourLine(elevation=281.0, points=[(81.286, 21.263), (81.286, 21.263)])
        with pytest.raises(InvalidGeometryError, match="spatial extent"):
            validate_contours([c1, c2])

    def test_rejects_tiny_bbox(self):
        """Points spread over only 0.00001 degrees → below threshold."""
        c1 = ContourLine(
            elevation=280.0,
            points=[(81.286000, 21.263000), (81.286001, 21.263001)],
        )
        c2 = ContourLine(
            elevation=281.0,
            points=[(81.286002, 21.263002), (81.286003, 21.263003)],
        )
        with pytest.raises(InvalidGeometryError, match="spatial extent"):
            validate_contours([c1, c2])


# ── KMLTerrainSource exception types ─────────────────────────────────────────


class TestKMLSourceExceptions:

    def test_invalid_xml_raises_terrain_parse_error(self):
        with pytest.raises(TerrainParseError):
            KMLTerrainSource(b"not xml <<<", filename="bad.kml").extract_contours()

    def test_parse_error_catchable_as_terrain_error(self):
        with pytest.raises(TerrainError):
            KMLTerrainSource(b"not xml <<<", filename="bad.kml").extract_contours()

    def test_bad_zip_kmz_raises_terrain_parse_error(self):
        with pytest.raises(TerrainParseError, match="valid ZIP"):
            KMLTerrainSource(b"not a zip", filename="bad.kmz")

    def test_empty_kmz_raises_terrain_parse_error(self):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("readme.txt", "no kml here")
        with pytest.raises(TerrainParseError, match="no .kml files"):
            KMLTerrainSource(buf.getvalue(), filename="empty.kmz")

    def test_parse_error_is_not_value_error(self):
        """TerrainParseError must NOT be a subclass of ValueError."""
        assert not issubclass(TerrainParseError, ValueError)

    def test_truncated_xml_raises_terrain_parse_error(self):
        truncated = (
            b"<?xml version='1.0'?><Folder xmlns='http://www.opengis.net/kml/2.2'><Pl"
        )
        with pytest.raises(TerrainParseError):
            KMLTerrainSource(truncated, filename="truncated.kml").extract_contours()


# ── Fixture file integration tests ────────────────────────────────────────────


class TestFixtureFiles:

    @pytest.mark.skipif(
        not (FIXTURES / "empty.kml").exists(),
        reason="empty.kml fixture not present",
    )
    def test_empty_kml_passes_file_check_but_fails_semantic(self):
        data = (FIXTURES / "empty.kml").read_bytes()
        validate_file("empty.kml", len(data))  # passes (valid extension + small size)
        contours = KMLTerrainSource(data, filename="empty.kml").extract_contours()
        assert contours == [], f"Expected [], got {contours}"
        with pytest.raises(InvalidGeometryError, match="At least 2"):
            validate_contours(contours)

    @pytest.mark.skipif(
        not (FIXTURES / "single_contour.kml").exists(),
        reason="single_contour.kml fixture not present",
    )
    def test_single_contour_fails_semantic_validation(self):
        data = (FIXTURES / "single_contour.kml").read_bytes()
        contours = KMLTerrainSource(
            data, filename="single_contour.kml"
        ).extract_contours()
        assert len(contours) == 1
        with pytest.raises(InvalidGeometryError, match="got 1"):
            validate_contours(contours)

    @pytest.mark.skipif(
        not (FIXTURES / "flat_terrain.kml").exists(),
        reason="flat_terrain.kml fixture not present",
    )
    def test_flat_terrain_fails_elevation_variety_check(self):
        data = (FIXTURES / "flat_terrain.kml").read_bytes()
        contours = KMLTerrainSource(
            data, filename="flat_terrain.kml"
        ).extract_contours()
        assert len(contours) == 3
        with pytest.raises(InvalidGeometryError, match="flat surface"):
            validate_contours(contours)

    @pytest.mark.skipif(
        not (FIXTURES / "not_xml.kml").exists(),
        reason="not_xml.kml fixture not present",
    )
    def test_not_xml_raises_terrain_parse_error(self):
        data = (FIXTURES / "not_xml.kml").read_bytes()
        validate_file("not_xml.kml", len(data))  # extension is fine
        with pytest.raises(TerrainParseError):
            KMLTerrainSource(data, filename="not_xml.kml").extract_contours()
