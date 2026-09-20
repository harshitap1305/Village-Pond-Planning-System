"""
FastAPI application entry point.

Run locally with:
    uvicorn src.api.main:app --reload

Open API docs at:
    http://localhost:8000/docs
"""

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.error_handlers import register_error_handlers
from src.api.routes import router
from src.config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    description=(
        "AI-based Village Pond Planning System — identifies optimal pond sites "
        "from KML/KMZ contour maps and returns delineated catchment polygons."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
register_error_handlers(app)

# Serve the frontend SPA at "/".
# Must be mounted LAST so API routes registered above always take priority.
# Guarded by os.path.isdir so the API works without the frontend dir (e.g. in CI).
_frontend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.api.main:app", host="0.0.0.0", port=settings.port, reload=True)
