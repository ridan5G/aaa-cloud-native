import re
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.db import get_conn
from app.auth import require_auth

router = APIRouter()

IMSI_RE = re.compile(r"^\d{15}$")
IP_RES_VALUES = ("imsi", "imsi_apn", "iccid", "iccid_apn")


def _val_err(field: str, msg: str):
    raise HTTPException(
        status_code=400,
        detail={"error": "validation_failed", "details": [{"field": field, "message": msg}]},
    )


class RangeConfigCreate(BaseModel):
    account_name: Optional[str] = None
    f_imsi: str
    t_imsi: str
    pool_id: str
    ip_resolution: str = "imsi"
    description: Optional[str] = None
    status: str = "active"


class RangeConfigPatch(BaseModel):
    pool_id: Optional[str] = None
    ip_resolution: Optional[str] = None
    status: Optional[str] = None
    description: Optional[str] = None


@router.post("/range-configs", status_code=201, dependencies=[Depends(require_auth)])
async def create_range_config(body: RangeConfigCreate, conn=Depends(get_conn)):
    if not IMSI_RE.match(body.f_imsi):
        _val_err("f_imsi", "must be exactly 15 digits")
    if not IMSI_RE.match(body.t_imsi):
        _val_err("t_imsi", "must be exactly 15 digits")
    if body.f_imsi > body.t_imsi:
        _val_err("f_imsi", "f_imsi must be <= t_imsi")
    if body.ip_resolution not in IP_RES_VALUES:
        _val_err("ip_resolution", f"must be one of {IP_RES_VALUES}")
    if body.status not in ("active", "suspended"):
        _val_err("status", "must be active or suspended")

    pool_exists = await conn.fetchval(
        "SELECT 1 FROM ip_pools WHERE pool_id = $1::uuid", body.pool_id
    )
    if not pool_exists:
        _val_err("pool_id", "pool not found")

    row_id = await conn.fetchval(
        """
        INSERT INTO imsi_range_configs
            (account_name, f_imsi, t_imsi, pool_id, ip_resolution, description, status)
        VALUES ($1, $2, $3, $4::uuid, $5, $6, $7)
        RETURNING id
        """,
        body.account_name,
        body.f_imsi,
        body.t_imsi,
        body.pool_id,
        body.ip_resolution,
        body.description,
        body.status,
    )
    return {"id": row_id}


@router.get("/range-configs/{config_id}", dependencies=[Depends(require_auth)])
async def get_range_config(config_id: int, conn=Depends(get_conn)):
    row = await conn.fetchrow(
        """
        SELECT id, account_name, f_imsi, t_imsi, pool_id::text,
               ip_resolution, description, status, iccid_range_id, imsi_slot,
               created_at, updated_at
        FROM imsi_range_configs WHERE id = $1
        """,
        config_id,
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "range_config", "id": config_id},
        )
    return dict(row)


@router.get("/range-configs", dependencies=[Depends(require_auth)])
async def list_range_configs(account_name: Optional[str] = None, conn=Depends(get_conn)):
    if account_name:
        rows = await conn.fetch(
            """
            SELECT id, account_name, f_imsi, t_imsi, pool_id::text,
                   ip_resolution, description, status
            FROM imsi_range_configs
            WHERE account_name = $1 AND iccid_range_id IS NULL
            ORDER BY id
            """,
            account_name,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT id, account_name, f_imsi, t_imsi, pool_id::text,
                   ip_resolution, description, status
            FROM imsi_range_configs WHERE iccid_range_id IS NULL
            ORDER BY id
            """
        )
    return {"items": [dict(r) for r in rows]}


@router.patch("/range-configs/{config_id}", dependencies=[Depends(require_auth)])
async def patch_range_config(config_id: int, body: RangeConfigPatch, conn=Depends(get_conn)):
    row = await conn.fetchrow(
        "SELECT id FROM imsi_range_configs WHERE id = $1", config_id
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "range_config", "id": config_id},
        )

    updates = []
    params = []
    idx = 1

    if body.pool_id is not None:
        pool_exists = await conn.fetchval(
            "SELECT 1 FROM ip_pools WHERE pool_id = $1::uuid", body.pool_id
        )
        if not pool_exists:
            _val_err("pool_id", "pool not found")
        updates.append(f"pool_id = ${idx}::uuid")
        params.append(body.pool_id)
        idx += 1

    if body.ip_resolution is not None:
        if body.ip_resolution not in IP_RES_VALUES:
            _val_err("ip_resolution", f"must be one of {IP_RES_VALUES}")
        updates.append(f"ip_resolution = ${idx}")
        params.append(body.ip_resolution)
        idx += 1

    if body.status is not None:
        if body.status not in ("active", "suspended"):
            _val_err("status", "must be active or suspended")
        updates.append(f"status = ${idx}")
        params.append(body.status)
        idx += 1

    if body.description is not None:
        updates.append(f"description = ${idx}")
        params.append(body.description)
        idx += 1

    if updates:
        updates.append("updated_at = now()")
        params.append(config_id)
        await conn.execute(
            f"UPDATE imsi_range_configs SET {', '.join(updates)} WHERE id = ${idx}",
            *params,
        )

    return {"id": config_id}


@router.delete("/range-configs/{config_id}", status_code=204, dependencies=[Depends(require_auth)])
async def delete_range_config(config_id: int, conn=Depends(get_conn)):
    row = await conn.fetchrow(
        "SELECT id FROM imsi_range_configs WHERE id = $1", config_id
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "range_config", "id": config_id},
        )
    await conn.execute("DELETE FROM imsi_range_configs WHERE id = $1", config_id)
