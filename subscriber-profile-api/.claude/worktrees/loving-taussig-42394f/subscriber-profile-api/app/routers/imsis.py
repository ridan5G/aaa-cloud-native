import re
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.db import get_conn
from app.auth import require_auth

router = APIRouter()

IMSI_RE = re.compile(r"^\d{15}$")


def _val_err(field: str, msg: str):
    raise HTTPException(
        status_code=400,
        detail={"error": "validation_failed", "details": [{"field": field, "message": msg}]},
    )


class ApnIpEntry(BaseModel):
    apn: Optional[str] = None
    static_ip: str
    pool_id: Optional[str] = None
    pool_name: Optional[str] = None


class ImsiCreate(BaseModel):
    imsi: str
    priority: int = 1
    apn_ips: list[ApnIpEntry] = []


class ImsiPatch(BaseModel):
    status: Optional[str] = None
    priority: Optional[int] = None
    # Convenience shorthand for imsi/iccid modes (no APN key needed):
    # PATCH …/imsis/{imsi} {"static_ip": "x.x.x.x", "pool_id": "…"} is
    # equivalent to passing apn_ips=[{"static_ip": …, "pool_id": …}].
    static_ip: Optional[str] = None
    pool_id: Optional[str] = None
    apn_ips: Optional[list[ApnIpEntry]] = None


async def _require_profile(sim_id: str, conn):
    row = await conn.fetchrow(
        "SELECT sim_id FROM sim_profiles WHERE sim_id = $1::uuid AND status != 'terminated'",
        sim_id,
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "subscriber_profile", "sim_id": str(sim_id)},
        )


@router.get("/profiles/{sim_id}/imsis", dependencies=[Depends(require_auth)])
async def list_imsis(sim_id: uuid.UUID, conn=Depends(get_conn)):
    await _require_profile(sim_id, conn)
    rows = await conn.fetch(
        """
        SELECT si.imsi, si.status, si.priority,
               COALESCE(
                   json_agg(
                       json_build_object(
                           'id', sa.id,
                           'apn', sa.apn,
                           'static_ip', host(sa.static_ip),
                           'pool_id', sa.pool_id::text,
                           'pool_name', sa.pool_name
                       ) ORDER BY sa.id
                   ) FILTER (WHERE sa.id IS NOT NULL),
                   '[]'::json
               ) AS apn_ips
        FROM imsi2sim si
        LEFT JOIN imsi_apn_ips sa ON sa.imsi = si.imsi
        WHERE si.sim_id = $1::uuid
        GROUP BY si.imsi, si.status, si.priority
        ORDER BY si.priority, si.imsi
        """,
        sim_id,
    )
    result = []
    for row in rows:
        d = dict(row)
        if not isinstance(d["apn_ips"], list):
            d["apn_ips"] = []
        result.append(d)
    return result


@router.get("/profiles/{sim_id}/imsis/{imsi}", dependencies=[Depends(require_auth)])
async def get_imsi(sim_id: uuid.UUID, imsi: str, conn=Depends(get_conn)):
    await _require_profile(sim_id, conn)
    row = await conn.fetchrow(
        """
        SELECT si.imsi, si.status, si.priority,
               COALESCE(
                   json_agg(
                       json_build_object(
                           'id', sa.id,
                           'apn', sa.apn,
                           'static_ip', host(sa.static_ip),
                           'pool_id', sa.pool_id::text,
                           'pool_name', sa.pool_name
                       ) ORDER BY sa.id
                   ) FILTER (WHERE sa.id IS NOT NULL),
                   '[]'::json
               ) AS apn_ips
        FROM imsi2sim si
        LEFT JOIN imsi_apn_ips sa ON sa.imsi = si.imsi
        WHERE si.sim_id = $1::uuid AND si.imsi = $2
        GROUP BY si.imsi, si.status, si.priority
        """,
        sim_id,
        imsi,
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "subscriber_imsi", "imsi": imsi},
        )
    d = dict(row)
    if not isinstance(d["apn_ips"], list):
        d["apn_ips"] = []
    return d


@router.post("/profiles/{sim_id}/imsis", status_code=201, dependencies=[Depends(require_auth)])
async def add_imsi(sim_id: uuid.UUID, body: ImsiCreate, conn=Depends(get_conn)):
    await _require_profile(sim_id, conn)

    if not IMSI_RE.match(body.imsi):
        _val_err("imsi", "must be exactly 15 digits")

    existing = await conn.fetchval(
        "SELECT sim_id::text FROM imsi2sim WHERE imsi = $1", body.imsi
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "imsi_conflict",
                "imsi": body.imsi,
                "existing_sim_id": existing,
            },
        )

    async with conn.transaction():
        await conn.execute(
            "INSERT INTO imsi2sim (imsi, sim_id, status, priority) VALUES ($1, $2::uuid, 'active', $3)",
            body.imsi, sim_id, body.priority,
        )
        for aip in body.apn_ips:
            await conn.execute(
                "INSERT INTO imsi_apn_ips (imsi, apn, static_ip, pool_id, pool_name) VALUES ($1, $2, $3::inet, $4::uuid, $5)",
                body.imsi, aip.apn, aip.static_ip, aip.pool_id, aip.pool_name,
            )

    return {"imsi": body.imsi, "sim_id": str(sim_id)}


@router.patch("/profiles/{sim_id}/imsis/{imsi}", dependencies=[Depends(require_auth)])
async def patch_imsi(sim_id: uuid.UUID, imsi: str, body: ImsiPatch, conn=Depends(get_conn)):
    await _require_profile(sim_id, conn)
    row = await conn.fetchrow(
        "SELECT imsi FROM imsi2sim WHERE sim_id = $1::uuid AND imsi = $2",
        sim_id, imsi,
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "subscriber_imsi", "imsi": imsi},
        )

    if body.status is not None:
        if body.status not in ("active", "suspended"):
            _val_err("status", "must be active or suspended")
        await conn.execute(
            "UPDATE imsi2sim SET status=$1, updated_at=now() WHERE imsi=$2",
            body.status, imsi,
        )

    if body.priority is not None:
        await conn.execute(
            "UPDATE imsi2sim SET priority=$1, updated_at=now() WHERE imsi=$2",
            body.priority, imsi,
        )

    # Normalise shorthand: top-level static_ip → single apn_ips entry (imsi/iccid modes).
    # Allows PATCH {"status":"active","static_ip":"x.x","pool_id":"…"} without nesting.
    effective_apn_ips = body.apn_ips
    if body.static_ip is not None and body.apn_ips is None:
        effective_apn_ips = [ApnIpEntry(static_ip=body.static_ip, pool_id=body.pool_id)]

    if effective_apn_ips is not None:
        async with conn.transaction():
            await conn.execute("DELETE FROM imsi_apn_ips WHERE imsi = $1", imsi)
            for aip in effective_apn_ips:
                await conn.execute(
                    "INSERT INTO imsi_apn_ips (imsi, apn, static_ip, pool_id, pool_name) VALUES ($1, $2, $3::inet, $4::uuid, $5)",
                    imsi, aip.apn, aip.static_ip, aip.pool_id, aip.pool_name,
                )

    return await get_imsi(sim_id, imsi, conn)


@router.delete("/profiles/{sim_id}/imsis/{imsi}", status_code=204, dependencies=[Depends(require_auth)])
async def delete_imsi(sim_id: uuid.UUID, imsi: str, conn=Depends(get_conn)):
    await _require_profile(sim_id, conn)
    row = await conn.fetchrow(
        "SELECT imsi FROM imsi2sim WHERE sim_id = $1::uuid AND imsi = $2",
        sim_id, imsi,
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "subscriber_imsi", "imsi": imsi},
        )
    async with conn.transaction():
        ip_rows = await conn.fetch(
            "SELECT pool_id::text, host(static_ip) AS ip FROM imsi_apn_ips "
            "WHERE imsi = $1 AND pool_id IS NOT NULL",
            imsi,
        )
        # CASCADE removes imsi_apn_ips
        await conn.execute("DELETE FROM imsi2sim WHERE imsi = $1", imsi)
        if ip_rows:
            await conn.executemany(
                "INSERT INTO ip_pool_available (pool_id, ip) VALUES ($1::uuid, $2::inet) ON CONFLICT DO NOTHING",
                [(r["pool_id"], r["ip"]) for r in ip_rows],
            )
