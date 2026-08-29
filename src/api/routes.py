"""
FastAPI route for POST /analyzeContour.

Accepts a KML/KMZ file upload, runs the analysis pipeline in a threadpool
(to avoid blocking the async event loop on CPU-bound work), and returns the
structured AnalysisResult JSON response.
"""

from fastapi import APIRouter, UploadFile
from starlette.concurrency import run_in_threadpool

from src.api.analysis_service import analysis_service
from src.schemas.response import AnalysisResult

router = APIRouter()


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
    file: UploadFile,
    cell_size: float | None = None,
) -> AnalysisResult:
    """
    Run the full village pond analysis pipeline.

    - **file**: KML or KMZ file containing elevation contour lines.
    - **cell_size**: Optional DEM grid resolution override in metres (default: 2.0 m).
    """
    contents = await file.read()
    result = await run_in_threadpool(
        analysis_service.run,
        contents,
        file.filename or "upload.kml",
        cell_size,
    )
    return result
