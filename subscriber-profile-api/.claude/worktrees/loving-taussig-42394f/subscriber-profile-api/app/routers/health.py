from fastapi import APIRouter, Depends
from app.db import get_conn

router = APIRouter()


@router.get("/health")
async def liveness():
    return {"status": "ok"}


@router.get("/health/db")
async def readiness(conn=Depends(get_conn)):
    try:
        await conn.fetchval("SELECT 1")
        return {"status": "ok", "db": "ok"}
    except Exception as exc:
        return {"status": "error", "db": str(exc)}
