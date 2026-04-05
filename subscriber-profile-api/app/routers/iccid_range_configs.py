import re
import json
import logging
import uuid as _uuid
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from app.db import get_conn, get_pool
from app.auth import require_auth
from app.config import BULK_BATCH_SIZE
from app.routers.first_connection import _allocate_ip, _load_apn_pools
from app.routers.range_configs import _check_pool_capacity

router = APIRouter()
logger = logging.getLogger(__name__)

ICCID_RE = re.compile(r"^\d{19,20}$")
IMSI_RE = re.compile(r"^\d{15}$")
IP_RES_VALUES = ("imsi", "imsi_apn", "iccid", "iccid_apn")
PROV_MODE_VALUES = ("first_connect", "immediate")


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
    provisioning_mode: str = "first_connect"


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


class ApnPoolCreate(BaseModel):
    apn: str
    pool_id: str


async def _run_provision_iccid_job(
    job_id: str,
    iccid_range_id: int,
    parent: dict,
    slot_rows: list[dict],
):
    """Background task: provision every card in the ICCID range in BULK_BATCH_SIZE chunks.

    For each card offset, creates one sim_profile with the derived ICCID, then links
    all IMSI slots and allocates IPs for each slot.
    """
    f_iccid = parent["f_iccid"]
    t_iccid = parent["t_iccid"]
    iccid_len = len(f_iccid)
    ip_resolution = parent["ip_resolution"]
    account_name = parent["account_name"] or ""
    card_count = int(t_iccid) - int(f_iccid) + 1
    metadata = json.dumps({"tags": ["auto-allocated", "multi-imsi"]})
    processed = failed = 0
    errors = []

    try:
        async with get_pool().acquire() as conn:
            for batch_start in range(0, card_count, BULK_BATCH_SIZE):
                batch_offsets = range(batch_start, min(batch_start + BULK_BATCH_SIZE, card_count))
                async with conn.transaction():
                    for offset in batch_offsets:
                        derived_iccid = str(int(f_iccid) + offset).zfill(iccid_len)
                        try:
                            existing = await conn.fetchval(
                                "SELECT sim_id::text FROM sim_profiles WHERE iccid = $1",
                                derived_iccid,
                            )
                            if existing:
                                processed += 1
                                continue

                            sim_id = await conn.fetchval(
                                "INSERT INTO sim_profiles (account_name, status, ip_resolution, iccid, metadata) "
                                "VALUES ($1,'active',$2,$3,$4::jsonb) RETURNING sim_id::text",
                                account_name,
                                ip_resolution,
                                derived_iccid,
                                metadata,
                            )

                            for slot in slot_rows:
                                slot_imsi = str(int(slot["f_imsi"]) + offset).zfill(15)
                                slot_pool = slot["pool_id"] or parent.get("pool_id")
                                await conn.execute(
                                    "INSERT INTO imsi2sim (imsi, sim_id, status, priority) "
                                    "VALUES ($1,$2::uuid,'active',$3) ON CONFLICT DO NOTHING",
                                    slot_imsi,
                                    sim_id,
                                    slot["imsi_slot"],
                                )
                                if ip_resolution in ("imsi", "imsi_apn"):
                                    apn_pools = await _load_apn_pools(
                                        conn, slot["id"], slot_pool, ip_resolution
                                    )
                                    if ip_resolution == "imsi_apn" and not apn_pools:
                                        raise RuntimeError(
                                            f"missing_apn_config: slot {slot['imsi_slot']} has no APN pool "
                                            f"entries for imsi_apn mode"
                                        )
                                    for apn_val, apn_pool in apn_pools:
                                        ip = await _allocate_ip(conn, apn_pool)
                                        if not ip:
                                            raise RuntimeError(f"pool_exhausted:{apn_pool}")
                                        await conn.execute(
                                            "INSERT INTO imsi_apn_ips (imsi,apn,static_ip,pool_id) "
                                            "VALUES ($1,$2,$3::inet,$4::uuid)",
                                            slot_imsi,
                                            apn_val,
                                            ip,
                                            apn_pool,
                                        )
                                # iccid/iccid_apn: allocate card-level IPs from slot 1 only
                                elif slot["imsi_slot"] == 1:
                                    apn_pools = await _load_apn_pools(
                                        conn, slot["id"], slot_pool, ip_resolution
                                    )
                                    if ip_resolution == "iccid_apn" and not apn_pools:
                                        raise RuntimeError(
                                            f"missing_apn_config: slot {slot['imsi_slot']} has no APN pool "
                                            f"entries for iccid_apn mode"
                                        )
                                    for apn_val, apn_pool in apn_pools:
                                        ip = await _allocate_ip(conn, apn_pool)
                                        if not ip:
                                            raise RuntimeError(f"pool_exhausted:{apn_pool}")
                                        await conn.execute(
                                            "INSERT INTO sim_apn_ips (sim_id,apn,static_ip,pool_id) "
                                            "VALUES ($1::uuid,$2,$3::inet,$4::uuid)",
                                            sim_id,
                                            apn_val,
                                            ip,
                                            apn_pool,
                                        )
                            processed += 1
                        except Exception as exc:
                            failed += 1
                            errors.append({"iccid": derived_iccid, "message": str(exc)})

            status = "completed" if not errors else "completed_with_errors"
            await conn.execute(
                "UPDATE bulk_jobs SET status=$1, processed=$2, failed=$3, "
                "errors=$4::jsonb, updated_at=now() WHERE job_id=$5::uuid",
                status,
                processed,
                failed,
                errors,
                job_id,
            )
    except Exception as job_exc:
        logger.error("Unhandled exception in _run_provision_iccid_job %s: %s", job_id, job_exc)
        try:
            async with get_pool().acquire() as _conn:
                await _conn.execute(
                    "UPDATE bulk_jobs SET status='failed', "
                    "errors=$1::jsonb, updated_at=now() WHERE job_id=$2::uuid",
                    [{"message": str(job_exc)}],
                    job_id,
                )
        except Exception:
            pass


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
    if body.provisioning_mode not in PROV_MODE_VALUES:
        _val_err("provisioning_mode", f"must be one of {PROV_MODE_VALUES}")

    if body.pool_id is not None:
        pool_exists = await conn.fetchval(
            "SELECT 1 FROM ip_pools WHERE pool_id = $1::uuid", body.pool_id
        )
        if not pool_exists:
            _val_err("pool_id", "pool not found")

    row_id = await conn.fetchval(
        """
        INSERT INTO iccid_range_configs
            (account_name, f_iccid, t_iccid, pool_id, ip_resolution, imsi_count,
             description, status, provisioning_mode)
        VALUES ($1, $2, $3, $4::uuid, $5, $6, $7, $8, $9)
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
        body.provisioning_mode,
    )
    return {"id": row_id}


@router.get("/iccid-range-configs/{config_id}", dependencies=[Depends(require_auth)])
async def get_iccid_range_config(config_id: int, conn=Depends(get_conn)):
    row = await conn.fetchrow(
        """
        SELECT id, account_name, f_iccid, t_iccid, pool_id::text,
               ip_resolution, imsi_count, description, status, provisioning_mode,
               created_at, updated_at
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
               ip_resolution, imsi_count, description, status, provisioning_mode
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
        "SELECT id, f_iccid, t_iccid, provisioning_mode FROM iccid_range_configs WHERE id = $1",
        config_id,
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "iccid_range_config", "id": config_id},
        )

    if row["provisioning_mode"] == "immediate":
        while True:
            sim_ids = [
                r["sim_id"]
                for r in await conn.fetch(
                    "SELECT sim_id::text AS sim_id FROM sim_profiles "
                    "WHERE iccid >= $1 AND iccid <= $2 LIMIT $3",
                    row["f_iccid"],
                    row["t_iccid"],
                    BULK_BATCH_SIZE,
                )
            ]
            if not sim_ids:
                break
            async with conn.transaction():
                imsi_ips = await conn.fetch(
                    "SELECT pool_id::text, host(static_ip) AS ip FROM imsi_apn_ips "
                    "WHERE imsi IN (SELECT imsi FROM imsi2sim WHERE sim_id=ANY($1::uuid[])) "
                    "AND pool_id IS NOT NULL",
                    sim_ids,
                )
                sim_ips = await conn.fetch(
                    "SELECT pool_id::text, host(static_ip) AS ip FROM sim_apn_ips "
                    "WHERE sim_id=ANY($1::uuid[]) AND pool_id IS NOT NULL",
                    sim_ids,
                )
                all_ips = [(r["pool_id"], r["ip"]) for r in list(imsi_ips) + list(sim_ips)]
                if all_ips:
                    await conn.executemany(
                        "INSERT INTO ip_pool_available (pool_id,ip) VALUES ($1::uuid,$2::inet) "
                        "ON CONFLICT DO NOTHING",
                        all_ips,
                    )
                await conn.execute(
                    "DELETE FROM sim_profiles WHERE sim_id=ANY($1::uuid[])", sim_ids
                )

    # CASCADE delete handles child imsi_range_configs rows
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
async def add_imsi_slot(
    config_id: int,
    body: ImsiSlotCreate,
    background_tasks: BackgroundTasks,
    conn=Depends(get_conn),
):
    parent = await conn.fetchrow(
        "SELECT id, f_iccid, t_iccid, pool_id::text, ip_resolution, imsi_count, "
        "account_name, provisioning_mode FROM iccid_range_configs WHERE id = $1",
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
    job_id = None
    slot_count = None
    slot_rows = None

    try:
        async with conn.transaction():
            range_config_id = await conn.fetchval(
                """
                INSERT INTO imsi_range_configs
                    (account_name, f_imsi, t_imsi, pool_id, ip_resolution,
                     iccid_range_id, imsi_slot, description, status, provisioning_mode)
                VALUES (
                    (SELECT account_name FROM iccid_range_configs WHERE id = $1),
                    $2, $3, $4::uuid, $5, $1, $6, $7, $8,
                    (SELECT provisioning_mode FROM iccid_range_configs WHERE id = $1)
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

            if parent["provisioning_mode"] == "immediate":
                slot_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM imsi_range_configs "
                    "WHERE iccid_range_id = $1 AND status = 'active'",
                    config_id,
                )
                if slot_count == parent["imsi_count"]:
                    card_count = int(parent["t_iccid"]) - int(parent["f_iccid"]) + 1
                    slot_rows_raw = await conn.fetch(
                        "SELECT id, f_imsi, imsi_slot, COALESCE(pool_id::text, $2) AS pool_id "
                        "FROM imsi_range_configs WHERE iccid_range_id = $1 AND status='active'",
                        config_id,
                        parent["pool_id"],
                    )
                    slot_rows = [dict(s) for s in slot_rows_raw]
                    for slot in slot_rows:
                        await _check_pool_capacity(
                            conn, slot["id"], card_count, slot["pool_id"], parent["ip_resolution"]
                        )
                    job_id = str(_uuid.uuid4())
                    await conn.execute(
                        "INSERT INTO bulk_jobs (job_id, status, submitted) "
                        "VALUES ($1::uuid,'queued',$2)",
                        job_id,
                        card_count * len(slot_rows),
                    )
    except HTTPException:
        raise
    except Exception as exc:
        if "uq_iccid_range_slot" in str(exc):
            _val_err("imsi_slot", f"slot {body.imsi_slot} already exists for this iccid range")
        raise

    if job_id and slot_rows is not None:
        background_tasks.add_task(
            _run_provision_iccid_job,
            job_id,
            config_id,
            dict(parent),
            slot_rows,
        )
        return {"range_config_id": range_config_id, "job_id": job_id}

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


async def _require_slot(config_id: int, slot: int, conn) -> int:
    """Return the imsi_range_configs.id for the given slot, or 404."""
    parent = await conn.fetchval(
        "SELECT id FROM iccid_range_configs WHERE id = $1", config_id
    )
    if not parent:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "iccid_range_config", "id": config_id},
        )
    slot_id = await conn.fetchval(
        "SELECT id FROM imsi_range_configs WHERE iccid_range_id = $1 AND imsi_slot = $2",
        config_id, slot,
    )
    if not slot_id:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "imsi_slot", "imsi_slot": slot},
        )
    return slot_id


@router.get(
    "/iccid-range-configs/{config_id}/imsi-slots/{slot}/apn-pools",
    dependencies=[Depends(require_auth)],
)
async def list_slot_apn_pools(config_id: int, slot: int, conn=Depends(get_conn)):
    slot_id = await _require_slot(config_id, slot, conn)
    rows = await conn.fetch(
        "SELECT id, apn, pool_id::text FROM range_config_apn_pools "
        "WHERE range_config_id = $1 ORDER BY apn",
        slot_id,
    )
    return {"items": [dict(r) for r in rows]}


@router.post(
    "/iccid-range-configs/{config_id}/imsi-slots/{slot}/apn-pools",
    status_code=201,
    dependencies=[Depends(require_auth)],
)
async def create_slot_apn_pool(
    config_id: int, slot: int, body: ApnPoolCreate, conn=Depends(get_conn)
):
    slot_id = await _require_slot(config_id, slot, conn)
    if not body.apn:
        _val_err("apn", "apn is required")
    pool_exists = await conn.fetchval(
        "SELECT 1 FROM ip_pools WHERE pool_id = $1::uuid", body.pool_id
    )
    if not pool_exists:
        _val_err("pool_id", "pool not found")
    try:
        row_id = await conn.fetchval(
            "INSERT INTO range_config_apn_pools (range_config_id, apn, pool_id) "
            "VALUES ($1, $2, $3::uuid) RETURNING id",
            slot_id, body.apn, body.pool_id,
        )
    except Exception as exc:
        if "uq_range_config_apn" in str(exc):
            _val_err("apn", f"APN '{body.apn}' already has a pool override for this slot")
        raise
    return {"id": row_id, "apn": body.apn, "pool_id": body.pool_id}


@router.delete(
    "/iccid-range-configs/{config_id}/imsi-slots/{slot}/apn-pools/{apn}",
    status_code=204,
    dependencies=[Depends(require_auth)],
)
async def delete_slot_apn_pool(config_id: int, slot: int, apn: str, conn=Depends(get_conn)):
    slot_id = await _require_slot(config_id, slot, conn)
    row = await conn.fetchrow(
        "SELECT id FROM range_config_apn_pools WHERE range_config_id = $1 AND apn = $2",
        slot_id, apn,
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "apn_pool", "apn": apn},
        )
    await conn.execute(
        "DELETE FROM range_config_apn_pools WHERE range_config_id = $1 AND apn = $2",
        slot_id, apn,
    )
