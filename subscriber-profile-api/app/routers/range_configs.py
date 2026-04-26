import re
import json
import uuid as _uuid
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from app.db import get_conn, get_pool
from app.auth import require_auth
from app.config import BULK_BATCH_SIZE
from app.routers.first_connection import _allocate_ip, _load_apn_pools

router = APIRouter()

IMSI_RE = re.compile(r"^\d{15}$")
IP_RES_VALUES = ("imsi", "imsi_apn", "iccid", "iccid_apn")
PROV_MODE_VALUES = ("first_connect", "immediate")


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
    provisioning_mode: str = "first_connect"


class RangeConfigPatch(BaseModel):
    pool_id: Optional[str] = None
    ip_resolution: Optional[str] = None
    status: Optional[str] = None
    description: Optional[str] = None


async def _pool_total_available(conn, pool_id: str) -> int:
    """Total free IPs across all subnets of a pool — unclaimed + already-claimed-unallocated.

    `start_ip`/`end_ip` in `ip_pool_subnets` are inclusive, so per-subnet capacity is
    `(end_ip - start_ip + 1)`.
    """
    row = await conn.fetchrow(
        """
        SELECT
            COALESCE(SUM((s.end_ip - s.start_ip + 1) - s.next_ip_offset), 0)
            + (SELECT COUNT(*) FROM ip_pool_available WHERE pool_id = $1::uuid)
            AS available
        FROM ip_pool_subnets s
        WHERE s.pool_id = $1::uuid
        """,
        pool_id,
    )
    if row is None or row["available"] is None:
        # Legacy pool with no ip_pool_subnets row — fall back to ip_pool_available count.
        legacy = await conn.fetchval(
            "SELECT COUNT(*) FROM ip_pool_available WHERE pool_id = $1::uuid", pool_id
        )
        return int(legacy or 0)
    return int(row["available"])


async def _compute_pools_needed(
    conn, range_config_id: int, range_size: int, default_pool: str, ip_resolution: str
) -> dict:
    """Return {pool_id: required_count} for a range config — mirrors _check_pool_capacity."""
    if ip_resolution not in ("imsi_apn", "iccid_apn"):
        return {default_pool: range_size} if default_pool else {}
    rows = await conn.fetch(
        "SELECT COALESCE(pool_id::text, $2) AS pool_id "
        "FROM range_config_apn_pools WHERE range_config_id = $1",
        range_config_id,
        default_pool,
    )
    pools_needed: dict = (
        {default_pool: range_size} if not rows and default_pool else {}
    )
    for r in rows:
        pid = r["pool_id"]
        if pid is None:
            continue
        pools_needed[pid] = pools_needed.get(pid, 0) + range_size
    return pools_needed


async def _claim_ips_from_pool(conn, pool_id: str, n: int) -> int:
    """Claim up to n IPs from pool's subnets in priority order, INSERTing into ip_pool_available.

    Returns the count actually claimed (may be less than n if pool exhausted).
    Caller must run inside a transaction.
    """
    if n <= 0:
        return 0

    subnets = await conn.fetch(
        """
        SELECT id, start_ip::text AS start_ip, next_ip_offset,
               (end_ip - start_ip + 1) - next_ip_offset AS remaining
        FROM ip_pool_subnets
        WHERE pool_id = $1::uuid
          AND ((end_ip - start_ip + 1) - next_ip_offset) > 0
        ORDER BY priority
        FOR UPDATE
        """,
        pool_id,
    )

    total_claimed = 0
    remaining = n
    for s in subnets:
        if remaining <= 0:
            break
        claim = min(remaining, int(s["remaining"]))
        row = await conn.fetchrow(
            """
            UPDATE ip_pool_subnets
               SET next_ip_offset = next_ip_offset + $2
             WHERE id = $1
            RETURNING (next_ip_offset - $2)::bigint AS start_offset, start_ip::text AS start_ip
            """,
            s["id"],
            claim,
        )
        await conn.execute(
            """
            INSERT INTO ip_pool_available (pool_id, ip)
            SELECT $1::uuid, ($2::inet + gs.n)::inet
              FROM generate_series($3::bigint, $4::bigint) gs(n)
            ON CONFLICT DO NOTHING
            """,
            pool_id,
            row["start_ip"],
            int(row["start_offset"]),
            int(row["start_offset"]) + claim - 1,
        )
        total_claimed += claim
        remaining -= claim

    return total_claimed


async def _set_job_running(conn, job_id: str) -> None:
    await conn.execute(
        "UPDATE bulk_jobs SET status='running', updated_at=now() WHERE job_id=$1::uuid",
        job_id,
    )


async def _update_job_progress(
    conn, job_id: str, processed: int, failed: int, errors: list
) -> None:
    await conn.execute(
        "UPDATE bulk_jobs SET processed=$1, failed=$2, errors=$3::jsonb, updated_at=now() "
        "WHERE job_id=$4::uuid",
        processed,
        failed,
        json.dumps(errors),
        job_id,
    )


async def _finalize_job(conn, job_id: str, status: str) -> None:
    await conn.execute(
        "UPDATE bulk_jobs SET status=$1, updated_at=now() WHERE job_id=$2::uuid",
        status,
        job_id,
    )


async def _check_pool_capacity(
    conn, range_config_id: int, range_size: int, default_pool: str, ip_resolution: str
) -> None:
    """Raise 503 if any pool lacks sufficient free IPs (counting both unclaimed-in-subnet
    and already-claimed-unallocated)."""
    pools_needed = await _compute_pools_needed(
        conn, range_config_id, range_size, default_pool, ip_resolution
    )
    for pid, required in pools_needed.items():
        available = await _pool_total_available(conn, pid)
        if available < required:
            raise HTTPException(
                503,
                detail={
                    "error": "pool_exhausted",
                    "pool_id": pid,
                    "available": available,
                    "required": required,
                },
            )


async def _run_provision_imsi_job(
    job_id: str,
    range_config_id: int,
    f_imsi: str,
    t_imsi: str,
    pool_id: str,
    ip_resolution: str,
    account_name: str,
):
    """Background task: provision every IMSI in [f_imsi..t_imsi] in BULK_BATCH_SIZE chunks.

    Phase 0: claim range_size IPs per pool into ip_pool_available (in chunks, with progress).
    Phase 1: per-IMSI provisioning (existing logic), with progress emitted per batch.
    """
    imsi_len = len(f_imsi)
    metadata = json.dumps({"tags": ["auto-allocated"]})
    imsi_list = [str(n).zfill(imsi_len) for n in range(int(f_imsi), int(t_imsi) + 1)]
    range_size = len(imsi_list)
    processed = failed = 0
    errors: list = []

    async with get_pool().acquire() as conn:
        await _set_job_running(conn, job_id)

        # ── Phase 0: pre-claim IPs from each pool needed for this range ──
        pools_needed = await _compute_pools_needed(
            conn, range_config_id, range_size, pool_id, ip_resolution
        )
        for pid, count in pools_needed.items():
            remaining = count
            while remaining > 0:
                chunk = min(remaining, BULK_BATCH_SIZE)
                async with conn.transaction():
                    claimed = await _claim_ips_from_pool(conn, pid, chunk)
                if claimed < chunk:
                    errors.append(
                        {
                            "pool_id": pid,
                            "message": "pool_exhausted",
                            "shortfall": chunk - claimed,
                        }
                    )
                    failed = range_size  # cannot proceed; mark whole range failed
                    await _update_job_progress(conn, job_id, 0, failed, errors)
                    await _finalize_job(conn, job_id, "failed")
                    return
                # Progress in Phase 0 surfaces as `errors` empty + processed=0; emit
                # an updated_at heartbeat so observers can see liveness.
                await _update_job_progress(conn, job_id, 0, 0, errors)
                remaining -= chunk

        # ── Phase 1: per-IMSI provisioning, progress per BULK_BATCH_SIZE ──
        for i in range(0, len(imsi_list), BULK_BATCH_SIZE):
            batch = imsi_list[i : i + BULK_BATCH_SIZE]
            async with conn.transaction():
                for imsi in batch:
                    try:
                        existing = await conn.fetchval(
                            "SELECT 1 FROM imsi2sim WHERE imsi = $1", imsi
                        )
                        if existing:
                            processed += 1
                            continue
                        sim_id = await conn.fetchval(
                            "INSERT INTO sim_profiles (account_name, status, ip_resolution, metadata) "
                            "VALUES ($1,'active',$2,$3::jsonb) RETURNING sim_id::text",
                            account_name,
                            ip_resolution,
                            metadata,
                        )
                        await conn.execute(
                            "INSERT INTO imsi2sim (imsi, sim_id, status, priority) "
                            "VALUES ($1,$2::uuid,'active',1)",
                            imsi,
                            sim_id,
                        )
                        apn_pools = await _load_apn_pools(
                            conn, range_config_id, pool_id, ip_resolution
                        )
                        for apn_val, apn_pool in apn_pools:
                            ip = await _allocate_ip(conn, apn_pool)
                            if not ip:
                                raise RuntimeError(f"pool_exhausted:{apn_pool}")
                            if ip_resolution in ("imsi", "imsi_apn"):
                                await conn.execute(
                                    "INSERT INTO imsi_apn_ips (imsi,apn,static_ip,pool_id) "
                                    "VALUES ($1,$2,$3::inet,$4::uuid)",
                                    imsi,
                                    apn_val,
                                    ip,
                                    apn_pool,
                                )
                            else:
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
                        errors.append({"imsi": imsi, "message": str(exc)})
            # Emit progress AFTER each chunk's transaction commits, so other
            # connections see processed/failed advance during the run.
            await _update_job_progress(conn, job_id, processed, failed, errors)

        final_status = "completed" if not errors else "completed_with_errors"
        await _finalize_job(conn, job_id, final_status)


async def _run_prepopulate_pool_job(
    job_id: str,
    range_config_id: int,
    pool_id: str,
    range_size: int,
    ip_resolution: str,
):
    """Background task for first_connect mode: claim range_size IPs per relevant pool
    into ip_pool_available, in chunks, with per-chunk progress reporting."""
    processed = failed = 0
    errors: list = []
    async with get_pool().acquire() as conn:
        await _set_job_running(conn, job_id)
        pools_needed = await _compute_pools_needed(
            conn, range_config_id, range_size, pool_id, ip_resolution
        )
        for pid, count in pools_needed.items():
            remaining = count
            while remaining > 0:
                chunk = min(remaining, BULK_BATCH_SIZE)
                async with conn.transaction():
                    claimed = await _claim_ips_from_pool(conn, pid, chunk)
                processed += claimed
                if claimed < chunk:
                    failed += chunk - claimed
                    errors.append(
                        {
                            "pool_id": pid,
                            "message": "pool_exhausted",
                            "shortfall": chunk - claimed,
                        }
                    )
                    await _update_job_progress(conn, job_id, processed, failed, errors)
                    await _finalize_job(conn, job_id, "failed")
                    return
                await _update_job_progress(conn, job_id, processed, failed, errors)
                remaining -= chunk

        final_status = "completed" if not errors else "completed_with_errors"
        await _finalize_job(conn, job_id, final_status)


@router.post("/range-configs", dependencies=[Depends(require_auth)])
async def create_range_config(
    body: RangeConfigCreate,
    background_tasks: BackgroundTasks,
    conn=Depends(get_conn),
):
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
    if body.provisioning_mode not in PROV_MODE_VALUES:
        _val_err("provisioning_mode", f"must be one of {PROV_MODE_VALUES}")

    if not body.pool_id:
        _val_err("pool_id", "pool_id is required")
    pool_exists = await conn.fetchval(
        "SELECT 1 FROM ip_pools WHERE pool_id = $1::uuid", body.pool_id
    )
    if not pool_exists:
        _val_err("pool_id", "pool not found")

    range_size = int(body.t_imsi) - int(body.f_imsi) + 1
    job_id = None

    async with conn.transaction():
        row_id = await conn.fetchval(
            """
            INSERT INTO imsi_range_configs
                (account_name, f_imsi, t_imsi, pool_id, ip_resolution, description, status,
                 provisioning_mode)
            VALUES ($1, $2, $3, $4::uuid, $5, $6, $7, $8)
            RETURNING id
            """,
            body.account_name,
            body.f_imsi,
            body.t_imsi,
            body.pool_id,
            body.ip_resolution,
            body.description,
            body.status,
            body.provisioning_mode,
        )
        # Both modes need a bulk job: immediate provisions IMSIs+IPs; first_connect
        # pre-claims IPs into ip_pool_available so first-connection requests can pop them.
        await _check_pool_capacity(conn, row_id, range_size, body.pool_id, body.ip_resolution)
        job_id = str(_uuid.uuid4())
        await conn.execute(
            "INSERT INTO bulk_jobs (job_id, status, submitted) VALUES ($1::uuid, 'queued', $2)",
            job_id,
            range_size,
        )

    if body.provisioning_mode == "immediate":
        background_tasks.add_task(
            _run_provision_imsi_job,
            job_id,
            row_id,
            body.f_imsi,
            body.t_imsi,
            body.pool_id,
            body.ip_resolution,
            body.account_name or "",
        )
    else:  # first_connect
        background_tasks.add_task(
            _run_prepopulate_pool_job,
            job_id,
            row_id,
            body.pool_id,
            range_size,
            body.ip_resolution,
        )

    return JSONResponse(status_code=202, content={"id": row_id, "job_id": job_id})


@router.get("/range-configs/{config_id}", dependencies=[Depends(require_auth)])
async def get_range_config(config_id: int, conn=Depends(get_conn)):
    row = await conn.fetchrow(
        """
        SELECT id, account_name, f_imsi, t_imsi, pool_id::text,
               ip_resolution, description, status, iccid_range_id, imsi_slot,
               provisioning_mode, created_at, updated_at
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
async def list_range_configs(
    account_name: Optional[str] = None,
    status: Optional[str] = None,
    pool_id: Optional[str] = None,
    ip_resolution: Optional[str] = None,
    conn=Depends(get_conn),
):
    conditions = ["iccid_range_id IS NULL"]
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

    where = f"WHERE {' AND '.join(conditions)}"
    rows = await conn.fetch(
        f"""
        SELECT id, account_name, f_imsi, t_imsi, pool_id::text,
               ip_resolution, description, status, provisioning_mode
        FROM imsi_range_configs {where}
        ORDER BY id
        """,
        *params,
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
        "SELECT id, f_imsi, t_imsi, provisioning_mode FROM imsi_range_configs WHERE id = $1",
        config_id,
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "range_config", "id": config_id},
        )

    if row["provisioning_mode"] == "immediate":
        while True:
            sim_ids = [
                r["sim_id"]
                for r in await conn.fetch(
                    "SELECT DISTINCT i.sim_id::text AS sim_id FROM imsi2sim i "
                    "WHERE i.imsi >= $1 AND i.imsi <= $2 LIMIT $3",
                    row["f_imsi"],
                    row["t_imsi"],
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

    await conn.execute("DELETE FROM imsi_range_configs WHERE id = $1", config_id)


# ── APN Pool Override endpoints ───────────────────────────────────────────────
# Allow different APNs to draw IPs from different pools for ip_resolution=imsi_apn/iccid_apn.
# first-connection checks these overrides before falling back to the range config's pool_id.


class ApnPoolCreate(BaseModel):
    apn: str
    pool_id: str


async def _require_range_config(config_id: int, conn):
    row = await conn.fetchrow("SELECT id FROM imsi_range_configs WHERE id = $1", config_id)
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "range_config", "id": config_id},
        )


@router.get("/range-configs/{config_id}/apn-pools", dependencies=[Depends(require_auth)])
async def list_apn_pools(config_id: int, conn=Depends(get_conn)):
    await _require_range_config(config_id, conn)
    rows = await conn.fetch(
        "SELECT id, apn, pool_id::text, created_at FROM range_config_apn_pools WHERE range_config_id = $1 ORDER BY apn",
        config_id,
    )
    return {"items": [dict(r) for r in rows]}


@router.post("/range-configs/{config_id}/apn-pools", status_code=201, dependencies=[Depends(require_auth)])
async def create_apn_pool(config_id: int, body: ApnPoolCreate, conn=Depends(get_conn)):
    await _require_range_config(config_id, conn)
    if not body.apn:
        _val_err("apn", "apn must not be empty")
    pool_exists = await conn.fetchval(
        "SELECT 1 FROM ip_pools WHERE pool_id = $1::uuid", body.pool_id
    )
    if not pool_exists:
        _val_err("pool_id", "pool not found")
    try:
        row_id = await conn.fetchval(
            """
            INSERT INTO range_config_apn_pools (range_config_id, apn, pool_id)
            VALUES ($1, $2, $3::uuid)
            RETURNING id
            """,
            config_id, body.apn, body.pool_id,
        )
    except Exception as exc:
        if "uq_range_config_apn" in str(exc):
            _val_err("apn", f"apn '{body.apn}' already has a pool override for this range config")
        raise
    return {"id": row_id, "range_config_id": config_id, "apn": body.apn, "pool_id": body.pool_id}


@router.delete("/range-configs/{config_id}/apn-pools/{apn}", status_code=204, dependencies=[Depends(require_auth)])
async def delete_apn_pool(config_id: int, apn: str, conn=Depends(get_conn)):
    row = await conn.fetchrow(
        "SELECT id FROM range_config_apn_pools WHERE range_config_id = $1 AND apn = $2",
        config_id, apn,
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "apn_pool", "range_config_id": config_id, "apn": apn},
        )
    await conn.execute(
        "DELETE FROM range_config_apn_pools WHERE range_config_id = $1 AND apn = $2",
        config_id, apn,
    )
