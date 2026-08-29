"""
FastAPI route for POST /analyzeContour.

Accepts a KML/KMZ file upload, runs the analysis pipeline in a threadpool
(to avoid blocking the async event loop on CPU-bound work), and returns the
structured AnalysisResult JSON response.
"""

from fastapi import APIRouter, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from src.api.analysis_service import analysis_service
from src.config import settings
from src.schemas.response import AnalysisResult
from src.terrain.exceptions import FileTooLargeError

router = APIRouter()


@router.get("/health", summary="Health check")
async def health_check():
    """Returns 200 OK when the service is running."""
    return {"status": "ok"}


@router.post(
    "/analyzeContour",
    response_model=AnalysisResult,
    summary="Analyze a KML/KMZ contour file and delineate a pond catchment",
    description=(
        "Upload a KML or KMZ file containing elevation contour lines. "
        "The API parses the contours, builds a DEM, runs hydrological routing, "
        "identifies optimal pond locations, and returns the delineated catchment "
        "polygon with terrain statistics."
    ),
)
async def analyze_contour(
    request: Request,
    file: UploadFile,
    cell_size: float | None = None,
) -> AnalysisResult:
    """
    Run the full village pond analysis pipeline.

    - **file**: KML or KMZ file containing elevation contour lines.
    - **cell_size**: Optional DEM grid resolution override in metres (default: 2.0 m).
    """
    # Reject oversized files before reading content into memory
    content_length = request.headers.get("content-length")
    if content_length:
        max_bytes = settings.max_upload_mb * 1024 * 1024
        if int(content_length) > max_bytes:
            raise FileTooLargeError(
                f"Content-Length {int(content_length) // (1024*1024)}MB "
                f"exceeds the {settings.max_upload_mb}MB upload limit."
            )

    contents = await file.read()
    result = await run_in_threadpool(
        analysis_service.run,
        contents,
        file.filename or "upload.kml",
        cell_size,
    )
    return result
