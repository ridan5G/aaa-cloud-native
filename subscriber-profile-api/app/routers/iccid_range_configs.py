import re
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.db import get_conn
from app.auth import require_auth

router = APIRouter()

ICCID_RE = re.compile(r"^\d{19,20}$")
IMSI_RE = re.compile(r"^\d{15}$")
IP_RES_VALUES = ("imsi", "imsi_apn", "iccid", "iccid_apn")


def _val_err(field: str, msg: str):
    raise HTTPException(
        status_code=400,
        detail={"error": "validation_failed", "details": [{"field": field, "message": msg}]},
    )


class IccidRangeCreate(BaseModel):
    account_name: Optional[str] = None
    f_iccid: str
    t_iccid: str
    pool_id: Optional[str] = None  # nullable: each IMSI slot may define its own pool
    ip_resolution: str = "imsi"
    imsi_count: int = 1
    description: Optional[str] = None
    status: str = "active"


class IccidRangePatch(BaseModel):
    description: Optional[str] = None
    status: Optional[str] = None
    pool_id: Optional[str] = None


class ImsiSlotCreate(BaseModel):
    f_imsi: str
    t_imsi: str
    pool_id: Optional[str] = None
    ip_resolution: Optional[str] = None
    imsi_slot: int
    description: Optional[str] = None
    status: str = "active"


class ImsiSlotPatch(BaseModel):
    f_imsi: Optional[str] = None
    t_imsi: Optional[str] = None
    pool_id: Optional[str] = None
    ip_resolution: Optional[str] = None
    status: Optional[str] = None
    description: Optional[str] = None


@router.post("/iccid-range-configs", status_code=201, dependencies=[Depends(require_auth)])
async def create_iccid_range_config(body: IccidRangeCreate, conn=Depends(get_conn)):
    if not ICCID_RE.match(body.f_iccid):
        _val_err("f_iccid", "must be 19-20 digits")
    if not ICCID_RE.match(body.t_iccid):
        _val_err("t_iccid", "must be 19-20 digits")
    if body.f_iccid > body.t_iccid:
        _val_err("f_iccid", "f_iccid must be <= t_iccid")
    if body.ip_resolution not in IP_RES_VALUES:
        _val_err("ip_resolution", f"must be one of {IP_RES_VALUES}")
    if not (1 <= body.imsi_count <= 10):
        _val_err("imsi_count", "must be between 1 and 10")
    if body.status not in ("active", "suspended"):
        _val_err("status", "must be active or suspended")

    if body.pool_id is not None:
        pool_exists = await conn.fetchval(
            "SELECT 1 FROM ip_pools WHERE pool_id = $1::uuid", body.pool_id
        )
        if not pool_exists:
            _val_err("pool_id", "pool not found")

    row_id = await conn.fetchval(
        """
        INSERT INTO iccid_range_configs
            (account_name, f_iccid, t_iccid, pool_id, ip_resolution, imsi_count, description, status)
        VALUES ($1, $2, $3, $4::uuid, $5, $6, $7, $8)
        RETURNING id
        """,
        body.account_name,
        body.f_iccid,
        body.t_iccid,
        body.pool_id,
        body.ip_resolution,
        body.imsi_count,
        body.description,
        body.status,
    )
    return {"id": row_id}


@router.get("/iccid-range-configs/{config_id}", dependencies=[Depends(require_auth)])
async def get_iccid_range_config(config_id: int, conn=Depends(get_conn)):
    row = await conn.fetchrow(
        """
        SELECT id, account_name, f_iccid, t_iccid, pool_id::text,
               ip_resolution, imsi_count, description, status, created_at, updated_at
        FROM iccid_range_configs WHERE id = $1
        """,
        config_id,
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "iccid_range_config", "id": config_id},
        )

    imsi_slots = await conn.fetch(
        """
        SELECT id, f_imsi, t_imsi, pool_id::text, ip_resolution,
               imsi_slot, description, status
        FROM imsi_range_configs WHERE iccid_range_id = $1
        ORDER BY imsi_slot
        """,
        config_id,
    )

    result = dict(row)
    result["imsi_ranges"] = [dict(s) for s in imsi_slots]
    return result


@router.get("/iccid-range-configs", dependencies=[Depends(require_auth)])
async def list_iccid_range_configs(
    account_name: Optional[str] = None,
    status: Optional[str] = None,
    pool_id: Optional[str] = None,
    ip_resolution: Optional[str] = None,
    conn=Depends(get_conn),
):
    conditions = []
    params = []
    idx = 1

    if account_name:
        conditions.append(f"account_name = ${idx}")
        params.append(account_name)
        idx += 1
    if status:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1
    if pool_id:
        conditions.append(f"pool_id = ${idx}::uuid")
        params.append(pool_id)
        idx += 1
    if ip_resolution:
        conditions.append(f"ip_resolution = ${idx}")
        params.append(ip_resolution)
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = await conn.fetch(
        f"""
        SELECT id, account_name, f_iccid, t_iccid, pool_id::text,
               ip_resolution, imsi_count, description, status
        FROM iccid_range_configs {where}
        ORDER BY id
        """,
        *params,
    )
    return {"items": [dict(r) for r in rows]}


@router.patch("/iccid-range-configs/{config_id}", dependencies=[Depends(require_auth)])
async def patch_iccid_range_config(config_id: int, body: IccidRangePatch, conn=Depends(get_conn)):
    row = await conn.fetchrow(
        "SELECT id FROM iccid_range_configs WHERE id = $1", config_id
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "iccid_range_config", "id": config_id},
        )

    updates = []
    params = []
    idx = 1

    if body.description is not None:
        updates.append(f"description = ${idx}")
        params.append(body.description)
        idx += 1

    if body.status is not None:
        if body.status not in ("active", "suspended"):
            _val_err("status", "must be active or suspended")
        updates.append(f"status = ${idx}")
        params.append(body.status)
        idx += 1

    if body.pool_id is not None:
        pool_exists = await conn.fetchval(
            "SELECT 1 FROM ip_pools WHERE pool_id = $1::uuid", body.pool_id
        )
        if not pool_exists:
            _val_err("pool_id", "pool not found")
        updates.append(f"pool_id = ${idx}::uuid")
        params.append(body.pool_id)
        idx += 1

    if updates:
        updates.append("updated_at = now()")
        params.append(config_id)
        await conn.execute(
            f"UPDATE iccid_range_configs SET {', '.join(updates)} WHERE id = ${idx}",
            *params,
        )

    return {"id": config_id}


@router.delete("/iccid-range-configs/{config_id}", status_code=204, dependencies=[Depends(require_auth)])
async def delete_iccid_range_config(config_id: int, conn=Depends(get_conn)):
    row = await conn.fetchrow(
        "SELECT id FROM iccid_range_configs WHERE id = $1", config_id
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "iccid_range_config", "id": config_id},
        )
    # CASCADE delete will handle child imsi_range_configs rows
    await conn.execute("DELETE FROM iccid_range_configs WHERE id = $1", config_id)


@router.get("/iccid-range-configs/{config_id}/imsi-slots", dependencies=[Depends(require_auth)])
async def list_imsi_slots(config_id: int, conn=Depends(get_conn)):
    parent = await conn.fetchrow(
        "SELECT id FROM iccid_range_configs WHERE id = $1", config_id
    )
    if not parent:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "iccid_range_config", "id": config_id},
        )
    rows = await conn.fetch(
        """
        SELECT id, imsi_slot, f_imsi, t_imsi, pool_id::text, ip_resolution,
               description, status
        FROM imsi_range_configs
        WHERE iccid_range_id = $1
        ORDER BY imsi_slot
        """,
        config_id,
    )
    return {"items": [dict(r) for r in rows]}


@router.post("/iccid-range-configs/{config_id}/imsi-slots", status_code=201, dependencies=[Depends(require_auth)])
async def add_imsi_slot(config_id: int, body: ImsiSlotCreate, conn=Depends(get_conn)):
    parent = await conn.fetchrow(
        "SELECT id, f_iccid, t_iccid, pool_id::text, ip_resolution FROM iccid_range_configs WHERE id = $1",
        config_id,
    )
    if not parent:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "iccid_range_config", "id": config_id},
        )

    if not IMSI_RE.match(body.f_imsi):
        _val_err("f_imsi", "must be exactly 15 digits")
    if not IMSI_RE.match(body.t_imsi):
        _val_err("t_imsi", "must be exactly 15 digits")
    if body.f_imsi > body.t_imsi:
        _val_err("f_imsi", "f_imsi must be <= t_imsi")
    if not (1 <= body.imsi_slot <= 10):
        _val_err("imsi_slot", "must be between 1 and 10")

    # ip_resolution must match parent
    slot_ip_res = body.ip_resolution or parent["ip_resolution"]
    if slot_ip_res != parent["ip_resolution"]:
        _val_err(
            "ip_resolution",
            f"imsi slot ip_resolution '{slot_ip_res}' conflicts with parent iccid range ip_resolution '{parent['ip_resolution']}'",
        )

    # Cardinality check: t_imsi - f_imsi must equal t_iccid - f_iccid
    imsi_cardinality = int(body.t_imsi) - int(body.f_imsi)
    iccid_cardinality = int(parent["t_iccid"]) - int(parent["f_iccid"])
    if imsi_cardinality != iccid_cardinality:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "validation_failed",
                "details": [
                    {
                        "field": "imsi_range",
                        "message": f"cardinality {imsi_cardinality + 1} does not match iccid range cardinality {iccid_cardinality + 1}",
                    }
                ],
            },
        )

    pool_id = body.pool_id or parent["pool_id"]

    try:
        range_config_id = await conn.fetchval(
            """
            INSERT INTO imsi_range_configs
                (account_name, f_imsi, t_imsi, pool_id, ip_resolution,
                 iccid_range_id, imsi_slot, description, status)
            VALUES (
                (SELECT account_name FROM iccid_range_configs WHERE id = $1),
                $2, $3, $4::uuid, $5, $1, $6, $7, $8
            )
            RETURNING id
            """,
            config_id,
            body.f_imsi,
            body.t_imsi,
            pool_id,
            slot_ip_res,
            body.imsi_slot,
            body.description,
            body.status,
        )
    except Exception as exc:
        if "uq_iccid_range_slot" in str(exc):
            _val_err("imsi_slot", f"slot {body.imsi_slot} already exists for this iccid range")
        raise

    return {"range_config_id": range_config_id}


@router.patch(
    "/iccid-range-configs/{config_id}/imsi-slots/{slot}",
    dependencies=[Depends(require_auth)],
)
async def patch_imsi_slot(config_id: int, slot: int, body: ImsiSlotPatch, conn=Depends(get_conn)):
    parent = await conn.fetchrow(
        "SELECT id, f_iccid, t_iccid, ip_resolution FROM iccid_range_configs WHERE id = $1",
        config_id,
    )
    if not parent:
        raise HTTPException(status_code=404, detail={"error": "not_found"})

    row = await conn.fetchrow(
        "SELECT id, f_imsi, t_imsi FROM imsi_range_configs WHERE iccid_range_id = $1 AND imsi_slot = $2",
        config_id, slot,
    )
    if not row:
        raise HTTPException(status_code=404, detail={"error": "not_found"})

    if body.ip_resolution is not None and body.ip_resolution != parent["ip_resolution"]:
        _val_err(
            "ip_resolution",
            f"imsi slot ip_resolution '{body.ip_resolution}' conflicts with parent iccid range ip_resolution '{parent['ip_resolution']}'",
        )

    # Revalidate cardinality if imsi range changes
    new_f = body.f_imsi or row["f_imsi"]
    new_t = body.t_imsi or row["t_imsi"]
    if body.f_imsi or body.t_imsi:
        imsi_cardinality = int(new_t) - int(new_f)
        iccid_cardinality = int(parent["t_iccid"]) - int(parent["f_iccid"])
        if imsi_cardinality != iccid_cardinality:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "validation_failed",
                    "details": [
                        {
                            "field": "imsi_range",
                            "message": f"cardinality {imsi_cardinality + 1} does not match iccid range cardinality {iccid_cardinality + 1}",
                        }
                    ],
                },
            )

    updates = []
    params = []
    idx = 1

    for field, val in [
        ("f_imsi", body.f_imsi),
        ("t_imsi", body.t_imsi),
        ("description", body.description),
        ("status", body.status),
    ]:
        if val is not None:
            updates.append(f"{field} = ${idx}")
            params.append(val)
            idx += 1

    if body.pool_id is not None:
        updates.append(f"pool_id = ${idx}::uuid")
        params.append(body.pool_id)
        idx += 1

    if body.ip_resolution is not None:
        updates.append(f"ip_resolution = ${idx}")
        params.append(body.ip_resolution)
        idx += 1

    if updates:
        updates.append("updated_at = now()")
        params.append(row["id"])
        await conn.execute(
            f"UPDATE imsi_range_configs SET {', '.join(updates)} WHERE id = ${idx}",
            *params,
        )

    return {"id": row["id"]}


@router.delete(
    "/iccid-range-configs/{config_id}/imsi-slots/{slot}",
    status_code=204,
    dependencies=[Depends(require_auth)],
)
async def delete_imsi_slot(config_id: int, slot: int, conn=Depends(get_conn)):
    row = await conn.fetchrow(
        "SELECT id FROM imsi_range_configs WHERE iccid_range_id = $1 AND imsi_slot = $2",
        config_id, slot,
    )
    if not row:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    await conn.execute("DELETE FROM imsi_range_configs WHERE id = $1", row["id"])
