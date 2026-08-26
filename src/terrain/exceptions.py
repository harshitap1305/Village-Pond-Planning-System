"""
Custom exception hierarchy for terrain data ingestion errors.

All exceptions inherit from TerrainError so callers can catch the entire
family with a single `except TerrainError` when fine-grained distinction
isn't needed.

HTTP status code mapping (wired up in Module 13's error handlers):
  UnsupportedFormatError  →  HTTP 415  Unsupported Media Type
  FileTooLargeError       →  HTTP 413  Request Entity Too Large
  TerrainParseError       →  HTTP 400  Bad Request
  InvalidGeometryError    →  HTTP 422  Unprocessable Entity
"""


class TerrainError(Exception):
    """Base class for all terrain-ingestion errors."""


class UnsupportedFormatError(TerrainError):
    """
    File extension is not in settings.allowed_extensions (.kml / .kmz).
    Maps to HTTP 415 Unsupported Media Type.
    """


class FileTooLargeError(TerrainError):
    """
    File size exceeds settings.max_upload_mb.
    Maps to HTTP 413 Request Entity Too Large.
    """


class TerrainParseError(TerrainError):
    """
    File bytes cannot be parsed as valid KML or KMZ.
    Raised by KMLTerrainSource for malformed XML and corrupt ZIPs.
    Maps to HTTP 400 Bad Request.
    """


class InvalidGeometryError(TerrainError):
    """
    File parsed successfully but the contours are semantically invalid
    for DEM interpolation (too few lines, flat terrain, zero spatial extent).
    Maps to HTTP 422 Unprocessable Entity.
    """
