"""
subscriber-profile-api — FastAPI provisioning service.

Env vars (see app/config.py for full list):
  PRIMARY_URL       PostgreSQL RW URI
  HTTP_PORT         default 8080
  METRICS_PORT      default 9091
  JWT_SKIP_VERIFY   "true" for dev
"""
import logging
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import HTTP_PORT, METRICS_PORT, CORS_ORIGINS
from app.db import init_db, close_db
from app.metrics import start_metrics_server, api_request_duration, http_requests_in_flight
from app.routers import health, pools, routing_domains, range_configs, iccid_range_configs, profiles, imsis, first_connection, bulk
import asyncpg
import time

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":%(message)s}',
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    start_metrics_server(METRICS_PORT)
    logger.info('"subscriber-profile-api started"')
    yield
    await close_db()
    logger.info('"subscriber-profile-api stopped"')


app = FastAPI(
    title="subscriber-profile-api",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — must be added before any other middleware.
# Origins are configured via CORS_ORIGINS env var (comma-separated).
# Empty → no CORS headers (correct when the UI nginx proxy handles routing).
if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    logger.info('"CORS enabled for origins: %s"', CORS_ORIGINS)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.monotonic()
    path = request.url.path
    # Normalize path for label cardinality
    if path.startswith("/v1/"):
        label_path = "/" + "/".join(path.split("/")[2:3])  # e.g. /profiles
    else:
        label_path = path
    http_requests_in_flight.labels(method=request.method, path=label_path).inc()
    try:
        response = await call_next(request)
    finally:
        elapsed_ms = (time.monotonic() - start) * 1000
        api_request_duration.labels(method=request.method, path=label_path).observe(elapsed_ms)
        http_requests_in_flight.labels(method=request.method, path=label_path).dec()
    return response


# Register all routers under /v1
PREFIX = "/v1"

app.include_router(health.router, tags=["health"])
app.include_router(routing_domains.router, prefix=PREFIX, tags=["routing-domains"])
app.include_router(pools.router, prefix=PREFIX, tags=["pools"])
app.include_router(range_configs.router, prefix=PREFIX, tags=["range-configs"])
app.include_router(iccid_range_configs.router, prefix=PREFIX, tags=["iccid-range-configs"])
app.include_router(profiles.router, prefix=PREFIX, tags=["profiles"])
app.include_router(imsis.router, prefix=PREFIX, tags=["imsis"])
app.include_router(first_connection.router, prefix=PREFIX, tags=["first-connection"])
app.include_router(bulk.router, prefix=PREFIX, tags=["bulk"])


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Return HTTPException.detail directly when it is a dict.

    FastAPI's default handler wraps everything in {"detail": ...}, which
    means tests that do resp.json().get("error") would never find the key.
    When detail is already a dict we return it as the top-level response body.
    String details (e.g. auth errors) keep the standard {"detail": "..."} shape.
    """
    if isinstance(exc.detail, dict):
        content = exc.detail
    else:
        content = {"detail": exc.detail}
    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return 422 with a consistent {error, details} body for Pydantic/schema errors."""
    return JSONResponse(
        status_code=422,
        content={"error": "validation_error", "details": exc.errors()},
    )


def _asyncpg_response(exc: asyncpg.PostgresError) -> JSONResponse | None:
    """Map a known asyncpg DB error to an HTTP JSONResponse, or return None."""
    if isinstance(exc, asyncpg.UniqueViolationError):
        constraint = getattr(exc, "constraint_name", None) or ""
        logger.warning("Unique constraint violation: %s — %s", constraint, exc)
        return JSONResponse(
            status_code=409,
            content={"error": "conflict", "detail": str(exc), "constraint": constraint},
        )
    if isinstance(exc, asyncpg.ForeignKeyViolationError):
        logger.warning("Foreign key violation: %s", exc)
        return JSONResponse(
            status_code=409,
            content={"error": "conflict", "detail": str(exc)},
        )
    if isinstance(exc, asyncpg.CheckViolationError):
        constraint = getattr(exc, "constraint_name", None) or ""
        logger.warning("Check constraint violation: %s — %s", constraint, exc)
        return JSONResponse(
            status_code=422,
            content={"error": "constraint_violation", "detail": str(exc), "constraint": constraint},
        )
    return None


@app.exception_handler(asyncpg.PostgresError)
async def asyncpg_exception_handler(request: Request, exc: asyncpg.PostgresError):
    """Catch asyncpg DB errors that escape router try/except blocks."""
    response = _asyncpg_response(exc)
    if response:
        return response
    logger.exception("Unhandled DB error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error": "db_error", "detail": str(exc)},
    )


@app.exception_handler(ExceptionGroup)
async def exception_group_handler(request: Request, exc: ExceptionGroup):
    """Unwrap Python 3.11 ExceptionGroup (raised by asyncio TaskGroup).

    Starlette's ExceptionMiddleware does not handle ExceptionGroup, so asyncpg
    errors wrapped inside a TaskGroup escape the entire middleware stack and
    crash the ASGI application with a 500 Internal Server Error log storm.
    We unwrap the group, map any known DB error to a proper HTTP response, and
    fall back to 500 for anything else.
    """
    # Flatten one level — TaskGroup wraps exactly one sub-exception in practice.
    causes = list(exc.exceptions)
    for cause in causes:
        if isinstance(cause, asyncpg.PostgresError):
            response = _asyncpg_response(cause)
            if response:
                return response
        if isinstance(cause, HTTPException):
            return await http_exception_handler(request, cause)
    # Unknown sub-exception — log and return 500.
    logger.exception("Unhandled ExceptionGroup: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "detail": str(exc)},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "detail": str(exc)},
    )


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=HTTP_PORT,
        log_level="info",
        access_log=True,
    )
