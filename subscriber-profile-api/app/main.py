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
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.config import HTTP_PORT, METRICS_PORT
from app.db import init_db, close_db
from app.metrics import start_metrics_server, api_request_duration
from app.routers import health, pools, range_configs, iccid_range_configs, profiles, imsis, first_connection, bulk
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


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    elapsed_ms = (time.monotonic() - start) * 1000
    path = request.url.path
    # Normalize path for label cardinality
    if path.startswith("/v1/"):
        label_path = "/" + "/".join(path.split("/")[2:3])  # e.g. /profiles
    else:
        label_path = path
    api_request_duration.labels(method=request.method, path=label_path).observe(elapsed_ms)
    return response


# Register all routers under /v1
PREFIX = "/v1"

app.include_router(health.router, tags=["health"])
app.include_router(pools.router, prefix=PREFIX, tags=["pools"])
app.include_router(range_configs.router, prefix=PREFIX, tags=["range-configs"])
app.include_router(iccid_range_configs.router, prefix=PREFIX, tags=["iccid-range-configs"])
app.include_router(profiles.router, prefix=PREFIX, tags=["profiles"])
app.include_router(imsis.router, prefix=PREFIX, tags=["imsis"])
app.include_router(first_connection.router, prefix=PREFIX, tags=["first-connection"])
app.include_router(bulk.router, prefix=PREFIX, tags=["bulk"])


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
