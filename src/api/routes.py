"""
FastAPI route for POST /analyzeContour.

Accepts a KML/KMZ file upload, runs the analysis pipeline in a threadpool
(to avoid blocking the async event loop on CPU-bound work), and returns the
structured AnalysisResult JSON response.
"""

import logging
import uuid

from fastapi import APIRouter, HTTPException, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from src.api.analysis_service import analysis_service
from src.config import settings
from src.db.engine import get_async_session, is_db_configured
from src.db.models import AnalysisRun
from src.schemas.response import AnalysisResult
from src.terrain.exceptions import FileTooLargeError

_log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health", summary="Health check")
async def health_check():
    """Returns 200 OK when the service is running."""
    return {"status": "ok"}


@router.post(
    "/analyzeContour",
    response_model=AnalysisResult,
    responses={
        400: {"description": "Malformed or unreadable KML/KMZ file"},
        413: {"description": "File exceeds the upload size limit"},
        415: {"description": "Unsupported file format — must be .kml or .kmz"},
        422: {
            "description": (
                "Valid KML but no suitable pond candidates found in the terrain, "
                "or request body validation failed"
            )
        },
    },
    summary="Analyze a KML/KMZ contour file and delineate a pond catchment",
    description=(
        "Upload a KML or KMZ file containing elevation contour lines. "
        "The API parses the contours, builds a DEM, runs hydrological routing, "
        "identifies optimal pond locations, and returns the delineated catchment "
        "polygon with terrain statistics, historical rainfall data, runoff estimates, "
        "and recommended pond dimensions. Hydrological fields degrade gracefully "
        "when external data sources are unavailable — check ``warnings`` in the "
        "response for machine-readable degraded-state codes."
    ),
)
async def analyze_contour(
    request: Request,
    contour_map: UploadFile,
    cell_size: float | None = None,
) -> AnalysisResult:
    """
    Run the full village pond analysis pipeline.

    - **contour_map**: KML or KMZ file containing elevation contour lines.
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

    contents = await contour_map.read()
    result = await run_in_threadpool(
        analysis_service.run,
        contents,
        contour_map.filename or "upload.kml",
        cell_size,
    )

    # ── Module 8: Persist result if DB is configured ──────────────────────
    if is_db_configured():
        try:
            async with get_async_session() as session:
                run = AnalysisRun(
                    filename=contour_map.filename or "upload.kml",
                    result_json=result.model_dump(mode="json"),
                )
                session.add(run)
                await session.commit()
                await session.refresh(run)
                # Attach the generated DB UUID to the API response
                result = result.model_copy(update={"result_id": run.id})
                _log.info("Analysis result persisted: id=%s", run.id)
        except Exception as exc:
            # Non-fatal: log and continue — don't fail the user's request
            # because the DB is down.
            _log.error(
                "Failed to persist analysis result (DB error): %s — "
                "result returned without result_id.",
                exc,
            )

    return result


@router.get(
    "/results/{result_id}",
    response_model=AnalysisResult,
    summary="Retrieve a previously stored analysis result by ID",
    responses={
        404: {"description": "No result found for this ID"},
        503: {"description": "Database not configured — persistence is disabled"},
    },
)
async def get_result(result_id: uuid.UUID) -> AnalysisResult:
    """
    Return a previously stored AnalysisResult by its UUID.

    The ``result_id`` is returned in the POST /analyzeContour response
    when the database is configured. Returns 503 if DATABASE_URL is not set.
    """
    if not is_db_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Persistence is not configured on this server. "
                "Set DATABASE_URL to enable GET /api/results/{id}."
            ),
        )
    async with get_async_session() as session:
        run = await session.get(AnalysisRun, result_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Result {result_id} not found.")
    return AnalysisResult.model_validate(run.result_json)
