# Module 13: Error Handling, Logging & Reliability Hardening

## Overview

Module 13 hardens the FastAPI application for production use. It introduces a comprehensive global exception handling strategy, pre-read upload size guards, and a health-check endpoint. It ensures the application is highly predictable and idempotent.

## Design Decisions

- **Fast-fail Guards**: Oversized files are rejected before being completely buffered into memory by checking the `Content-Length` header in the API layer.
- **Predictable HTTP Statuses**: Raised exceptions are mapped carefully to standard HTTP codes so consumers (frontends) understand exactly what failed (e.g. 422 for a flat terrain, 415 for a CSV upload, 400 for corrupt XML).
- **Idempotency Guarantee**: The pipeline uses standard sorts and deterministic algorithms (stable candidate ranking) so repeated requests with the same input file consistently yield the exact same response.

## Core Components

### 1. Global Exception Handlers
Located in `src/api/error_handlers.py`. Attached to the FastAPI application, these intercept domain-specific errors and convert them to secure JSON responses.
- `TerrainParseError` → **HTTP 400** (Bad Request)
- `FileTooLargeError` → **HTTP 413** (Payload Too Large)
- `UnsupportedFormatError` → **HTTP 415** (Unsupported Media Type)
- `InvalidGeometryError` → **HTTP 422** (Unprocessable Entity)
- `ValueError` (No candidates) → **HTTP 422** (Unprocessable Entity)
- `Exception` (Catch-all) → **HTTP 500** (Internal Server Error, with safe external message).

### 2. `GET /health`
Located in `src/api/routes.py`. A simple unauthenticated endpoint returning `{"status": "ok"}`, used by external load balancers and orchestrators to check service availability.

## Testing

Tested heavily using FastAPI's `TestClient` in `tests/unit/test_error_handlers.py`. Verified that the correct JSON details and status codes are bubbled up by the server even if internal algorithms crash. Pipeline idempotency was confirmed during verification against `contours_1m.kml`.
