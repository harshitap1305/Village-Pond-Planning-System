import logging
import traceback

from fastapi import Request
from fastapi.responses import JSONResponse

from src.terrain.exceptions import (
    FileTooLargeError,
    InvalidGeometryError,
    TerrainParseError,
    UnsupportedFormatError,
)

_log = logging.getLogger(__name__)


def _error_body(detail: str) -> dict:
    return {"detail": detail}


async def terrain_parse_error_handler(request: Request, exc: TerrainParseError):
    return JSONResponse(status_code=400, content=_error_body(str(exc)))


async def invalid_geometry_error_handler(request: Request, exc: InvalidGeometryError):
    return JSONResponse(status_code=422, content=_error_body(str(exc)))


async def unsupported_format_error_handler(
    request: Request, exc: UnsupportedFormatError
):
    return JSONResponse(status_code=415, content=_error_body(str(exc)))


async def file_too_large_error_handler(request: Request, exc: FileTooLargeError):
    return JSONResponse(status_code=413, content=_error_body(str(exc)))


async def value_error_handler(request: Request, exc: ValueError):
    # ValueError from find_candidates → "no suitable candidates" → 422
    return JSONResponse(status_code=422, content=_error_body(str(exc)))


async def generic_error_handler(request: Request, exc: Exception):
    # Log full traceback for debugging, but return a safe generic message
    _log.error(
        "Unhandled exception on %s %s:\n%s",
        request.method,
        request.url.path,
        traceback.format_exc(),
    )
    return JSONResponse(
        status_code=500,
        content=_error_body("An internal server error occurred. Please try again."),
    )


def register_error_handlers(app) -> None:
    """Register all exception handlers on the FastAPI app."""
    app.exception_handler(TerrainParseError)(terrain_parse_error_handler)
    app.exception_handler(InvalidGeometryError)(invalid_geometry_error_handler)
    app.exception_handler(UnsupportedFormatError)(unsupported_format_error_handler)
    app.exception_handler(FileTooLargeError)(file_too_large_error_handler)
    app.exception_handler(ValueError)(value_error_handler)
    app.exception_handler(Exception)(generic_error_handler)
