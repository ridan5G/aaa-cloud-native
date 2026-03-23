import re
import json
from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from app.db import get_conn
from app.auth import require_auth

router = APIRouter()

IMSI_RE = re.compile(r"^\d{15}$")
ICCID_RE = re.compile(r"^\d{19,20}$")
IP_RES_VALUES = ("iccid", "iccid_apn", "imsi", "imsi_apn", "multi_imsi_sim", "vrf_reuse")


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


class ImsiEntry(BaseModel):
    imsi: str
    priority: int = 1
    apn_ips: list[ApnIpEntry] = []


class IccidIpEntry(BaseModel):
    apn: Optional[str] = None
    static_ip: str
    pool_id: Optional[str] = None
    pool_name: Optional[str] = None


class ProfileCreate(BaseModel):
    iccid: Optional[str] = None
    account_name: Optional[str] = None
    status: str = "active"
    ip_resolution: Optional[str] = None
    imsis: list[ImsiEntry] = []
    iccid_ips: list[IccidIpEntry] = []
    metadata: Optional[Any] = None


class ProfilePatch(BaseModel):
    iccid: Optional[str] = None
    account_name: Optional[str] = None
    status: Optional[str] = None
    ip_resolution: Optional[str] = None
    iccid_ips: Optional[list[IccidIpEntry]] = None
    metadata: Optional[Any] = None


async def _build_profile_response(sim_id: str, conn) -> dict:
    profile = await conn.fetchrow(
        """
        SELECT sim_id::text, iccid, account_name, status, ip_resolution,
               metadata, created_at, updated_at
        FROM sim_profiles WHERE sim_id = $1::uuid
        """,
        sim_id,
    )
    if not profile:
        return None

    imsis = await conn.fetch(
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

    iccid_ips = await conn.fetch(
        """
        SELECT id, apn, host(static_ip) AS static_ip, pool_id::text, pool_name
        FROM sim_apn_ips WHERE sim_id = $1::uuid
        ORDER BY id
        """,
        sim_id,
    )

    result = dict(profile)
    result["imsis"] = []
    for imsi_row in imsis:
        imsi_dict = {
            "imsi": imsi_row["imsi"],
            "status": imsi_row["status"],
            "priority": imsi_row["priority"],
            "apn_ips": imsi_row["apn_ips"] if isinstance(imsi_row["apn_ips"], list) else [],
        }
        result["imsis"].append(imsi_dict)
    result["iccid_ips"] = [dict(r) for r in iccid_ips]
    return result


@router.post("/profiles", status_code=201, dependencies=[Depends(require_auth)])
async def create_profile(body: ProfileCreate, conn=Depends(get_conn)):
    # Validation
    if body.iccid is not None and not ICCID_RE.match(body.iccid):
        _val_err("iccid", "must be 19-20 digits")
    if body.ip_resolution is None:
        _val_err("ip_resolution", "required")
    if body.ip_resolution not in IP_RES_VALUES:
        _val_err("ip_resolution", f"must be one of {IP_RES_VALUES}")
    if body.status not in ("active", "suspended", "terminated"):
        _val_err("status", "must be active, suspended, or terminated")

    for entry in body.imsis:
        if not IMSI_RE.match(entry.imsi):
            _val_err("imsi", f"IMSI '{entry.imsi}' must be exactly 15 digits")

    # Validate pool references
    all_pool_ids = set()
    for entry in body.imsis:
        for aip in entry.apn_ips:
            if aip.pool_id:
                all_pool_ids.add(aip.pool_id)
    for iip in body.iccid_ips:
        if iip.pool_id:
            all_pool_ids.add(iip.pool_id)

    for pid in all_pool_ids:
        exists = await conn.fetchval("SELECT 1 FROM ip_pools WHERE pool_id = $1::uuid", pid)
        if not exists:
            _val_err("pool_id", f"pool '{pid}' not found")

    metadata_val = body.metadata
    if metadata_val is not None and not isinstance(metadata_val, (dict, list)):
        metadata_val = None

    async with conn.transaction():
        # Check ICCID uniqueness
        if body.iccid:
            existing = await conn.fetchval(
                "SELECT sim_id::text FROM sim_profiles WHERE iccid = $1",
                body.iccid,
            )
            if existing:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "iccid_conflict",
                        "iccid": body.iccid,
                        "existing_sim_id": existing,
                    },
                )

        # Check IMSI uniqueness
        for entry in body.imsis:
            existing = await conn.fetchval(
                "SELECT si.sim_id::text FROM imsi2sim si "
                "JOIN sim_profiles sp ON sp.sim_id = si.sim_id "
                "WHERE si.imsi = $1 AND sp.status != 'terminated'",
                entry.imsi,
            )
            if existing:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "imsi_conflict",
                        "imsi": entry.imsi,
                        "existing_sim_id": existing,
                    },
                )

        import datetime
        sim_id = await conn.fetchval(
            """
            INSERT INTO sim_profiles (iccid, account_name, status, ip_resolution, metadata)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            RETURNING sim_id::text
            """,
            body.iccid,
            body.account_name,
            body.status,
            body.ip_resolution,
            json.dumps(metadata_val) if metadata_val is not None else None,
        )

        for entry in body.imsis:
            await conn.execute(
                "INSERT INTO imsi2sim (imsi, sim_id, status, priority) VALUES ($1, $2::uuid, 'active', $3)",
                entry.imsi,
                sim_id,
                entry.priority,
            )
            for aip in entry.apn_ips:
                await conn.execute(
                    """
                    INSERT INTO imsi_apn_ips (imsi, apn, static_ip, pool_id, pool_name)
                    VALUES ($1, $2, $3::inet, $4::uuid, $5)
                    """,
                    entry.imsi,
                    aip.apn,
                    aip.static_ip,
                    aip.pool_id,
                    aip.pool_name,
                )

        for iip in body.iccid_ips:
            await conn.execute(
                """
                INSERT INTO sim_apn_ips (sim_id, apn, static_ip, pool_id, pool_name)
                VALUES ($1::uuid, $2, $3::inet, $4::uuid, $5)
                """,
                sim_id,
                iip.apn,
                iip.static_ip,
                iip.pool_id,
                iip.pool_name,
            )

    created_at = await conn.fetchval(
        "SELECT created_at FROM sim_profiles WHERE sim_id = $1::uuid", sim_id
    )
    return {"sim_id": sim_id, "created_at": created_at}


@router.get("/profiles/accounts", dependencies=[Depends(require_auth)])
async def list_profile_accounts(conn=Depends(get_conn)):
    """Return distinct non-null account names, sorted alphabetically."""
    rows = await conn.fetch(
        "SELECT DISTINCT account_name FROM sim_profiles "
        "WHERE account_name IS NOT NULL ORDER BY account_name"
    )
    return [r["account_name"] for r in rows]


@router.get("/profiles/export", dependencies=[Depends(require_auth)])
async def export_profiles(
    account_name: Optional[str] = None,
    status: Optional[str] = None,
    ip_resolution: Optional[str] = None,
    imsi_prefix: Optional[str] = None,
    iccid_prefix: Optional[str] = None,
    ip: Optional[str] = None,
    conn=Depends(get_conn),
):
    """Return all profiles with per-IMSI/APN rows in the bulk-import format."""
    filters: list[str] = []
    params: list = []
    idx = 1

    if account_name:
        filters.append(f"sp.account_name = ${idx}")
        params.append(account_name); idx += 1
    if status:
        filters.append(f"sp.status = ${idx}")
        params.append(status); idx += 1
    if ip_resolution:
        filters.append(f"sp.ip_resolution = ${idx}")
        params.append(ip_resolution); idx += 1
    if imsi_prefix:
        filters.append(f"sp.sim_id IN (SELECT sim_id FROM imsi2sim WHERE imsi LIKE ${idx})")
        params.append(imsi_prefix + "%"); idx += 1
    if iccid_prefix:
        filters.append(f"sp.iccid LIKE ${idx}")
        params.append(iccid_prefix + "%"); idx += 1
    if ip:
        filters.append(
            f"sp.sim_id IN ("
            f"SELECT si.sim_id FROM imsi2sim si "
            f"JOIN imsi_apn_ips ia ON ia.imsi = si.imsi "
            f"WHERE ia.static_ip = ${idx}::inet "
            f"UNION "
            f"SELECT sim_id FROM sim_apn_ips "
            f"WHERE static_ip = ${idx}::inet"
            f")"
        )
        params.append(ip); idx += 1

    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    rows = await conn.fetch(
        f"""
        SELECT
            sp.sim_id::text,
            sp.iccid,
            sp.account_name,
            sp.status,
            sp.ip_resolution,
            si.imsi,
            ia.apn,
            host(ia.static_ip) AS static_ip,
            ia.pool_id::text    AS pool_id
        FROM sim_profiles sp
        LEFT JOIN imsi2sim       si ON si.sim_id = sp.sim_id
        LEFT JOIN imsi_apn_ips   ia ON ia.imsi   = si.imsi
        {where}
        ORDER BY sp.created_at DESC, si.priority, ia.id
        """,
        *params,
    )
    return [dict(r) for r in rows]


@router.get("/profiles/{sim_id}", dependencies=[Depends(require_auth)])
async def get_profile(sim_id: str, conn=Depends(get_conn)):
    result = await _build_profile_response(sim_id, conn)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "subscriber_profile", "sim_id": sim_id},
        )
    return result


@router.get("/profiles", dependencies=[Depends(require_auth)])
async def list_profiles(
    iccid: Optional[str] = None,
    imsi: Optional[str] = None,
    account_name: Optional[str] = None,
    status: Optional[str] = None,
    ip_resolution: Optional[str] = None,
    pool_id: Optional[str] = None,
    imsi_prefix: Optional[str] = None,
    iccid_prefix: Optional[str] = None,
    ip: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=100, ge=1, le=1000),
    conn=Depends(get_conn),
):
    if iccid:
        row = await conn.fetchrow(
            "SELECT sim_id::text FROM sim_profiles WHERE iccid = $1", iccid
        )
        if not row:
            raise HTTPException(
                status_code=404,
                detail={"error": "not_found", "resource": "subscriber_profile", "iccid": iccid},
            )
        result = await _build_profile_response(row["sim_id"], conn)
        return [result]

    if imsi:
        row = await conn.fetchrow(
            "SELECT sim_id::text FROM imsi2sim WHERE imsi = $1", imsi
        )
        if not row:
            raise HTTPException(
                status_code=404,
                detail={"error": "not_found", "resource": "subscriber_profile", "imsi": imsi},
            )
        result = await _build_profile_response(row["sim_id"], conn)
        return [result]

    # Paginated list with optional filters
    filters = []
    params = []
    idx = 1

    if pool_id:
        filters.append(
            f"sim_id IN ("
            f"SELECT si.sim_id FROM imsi2sim si "
            f"JOIN imsi_apn_ips iai ON iai.imsi = si.imsi "
            f"WHERE iai.pool_id = ${idx}::uuid "
            f"UNION "
            f"SELECT sim_id FROM sim_apn_ips "
            f"WHERE pool_id = ${idx}::uuid"
            f")"
        )
        params.append(pool_id)
        idx += 1

    if account_name:
        filters.append(f"account_name = ${idx}")
        params.append(account_name)
        idx += 1
    if status:
        filters.append(f"status = ${idx}")
        params.append(status)
        idx += 1
    if ip_resolution:
        filters.append(f"ip_resolution = ${idx}")
        params.append(ip_resolution)
        idx += 1
    if imsi_prefix:
        filters.append(
            f"sim_id IN (SELECT sim_id FROM imsi2sim WHERE imsi LIKE ${idx})"
        )
        params.append(imsi_prefix + "%")
        idx += 1
    if iccid_prefix:
        filters.append(f"iccid LIKE ${idx}")
        params.append(iccid_prefix + "%")
        idx += 1
    if ip:
        filters.append(
            f"sim_id IN ("
            f"SELECT si.sim_id FROM imsi2sim si "
            f"JOIN imsi_apn_ips ia ON ia.imsi = si.imsi "
            f"WHERE ia.static_ip = ${idx}::inet "
            f"UNION "
            f"SELECT sim_id FROM sim_apn_ips "
            f"WHERE static_ip = ${idx}::inet"
            f")"
        )
        params.append(ip)
        idx += 1

    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    offset = (page - 1) * limit

    total = await conn.fetchval(
        f"SELECT COUNT(*) FROM sim_profiles {where}", *params
    )
    rows = await conn.fetch(
        f"""
        SELECT sim_id::text, iccid, account_name, status, ip_resolution, created_at
        FROM sim_profiles {where}
        ORDER BY created_at DESC
        LIMIT ${idx} OFFSET ${idx + 1}
        """,
        *params,
        limit,
        offset,
    )

    return {"items": [dict(r) for r in rows], "total": int(total), "page": page}


@router.put("/profiles/{sim_id}", dependencies=[Depends(require_auth)])
async def replace_profile(sim_id: str, body: ProfileCreate, conn=Depends(get_conn)):
    existing = await conn.fetchrow(
        "SELECT sim_id FROM sim_profiles WHERE sim_id = $1::uuid", sim_id
    )
    if not existing:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "subscriber_profile", "sim_id": sim_id},
        )

    if body.iccid is not None and not ICCID_RE.match(body.iccid):
        _val_err("iccid", "must be 19-20 digits")
    if body.ip_resolution is None:
        _val_err("ip_resolution", "required")
    if body.ip_resolution not in IP_RES_VALUES:
        _val_err("ip_resolution", f"must be one of {IP_RES_VALUES}")

    for entry in body.imsis:
        if not IMSI_RE.match(entry.imsi):
            _val_err("imsi", f"IMSI '{entry.imsi}' must be exactly 15 digits")

    metadata_val = body.metadata
    if metadata_val is not None and not isinstance(metadata_val, (dict, list)):
        metadata_val = None

    async with conn.transaction():
        if body.iccid:
            conflict = await conn.fetchval(
                "SELECT sim_id::text FROM sim_profiles WHERE iccid = $1 AND sim_id != $2::uuid",
                body.iccid,
                sim_id,
            )
            if conflict:
                raise HTTPException(
                    status_code=409,
                    detail={"error": "iccid_conflict", "iccid": body.iccid, "existing_sim_id": conflict},
                )

        await conn.execute(
            """
            UPDATE sim_profiles
            SET iccid=$1, account_name=$2, status=$3, ip_resolution=$4, metadata=$5::jsonb, updated_at=now()
            WHERE sim_id=$6::uuid
            """,
            body.iccid,
            body.account_name,
            body.status,
            body.ip_resolution,
            json.dumps(metadata_val) if metadata_val is not None else None,
            sim_id,
        )

        # Replace IMSIs
        await conn.execute(
            "DELETE FROM imsi2sim WHERE sim_id = $1::uuid", sim_id
        )
        for entry in body.imsis:
            await conn.execute(
                "INSERT INTO imsi2sim (imsi, sim_id, status, priority) VALUES ($1, $2::uuid, 'active', $3)",
                entry.imsi, sim_id, entry.priority,
            )
            for aip in entry.apn_ips:
                await conn.execute(
                    "INSERT INTO imsi_apn_ips (imsi, apn, static_ip, pool_id, pool_name) VALUES ($1, $2, $3::inet, $4::uuid, $5)",
                    entry.imsi, aip.apn, aip.static_ip, aip.pool_id, aip.pool_name,
                )

        # Replace ICCID IPs
        await conn.execute(
            "DELETE FROM sim_apn_ips WHERE sim_id = $1::uuid", sim_id
        )
        for iip in body.iccid_ips:
            await conn.execute(
                "INSERT INTO sim_apn_ips (sim_id, apn, static_ip, pool_id, pool_name) VALUES ($1::uuid, $2, $3::inet, $4::uuid, $5)",
                sim_id, iip.apn, iip.static_ip, iip.pool_id, iip.pool_name,
            )

    return await _build_profile_response(sim_id, conn)


@router.patch("/profiles/{sim_id}", dependencies=[Depends(require_auth)])
async def patch_profile(sim_id: str, body: ProfilePatch, conn=Depends(get_conn)):
    existing = await conn.fetchrow(
        "SELECT sim_id FROM sim_profiles WHERE sim_id = $1::uuid", sim_id
    )
    if not existing:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "subscriber_profile", "sim_id": sim_id},
        )

    updates = []
    params = []
    idx = 1

    if body.iccid is not None:
        if body.iccid and not ICCID_RE.match(body.iccid):
            _val_err("iccid", "must be 19-20 digits")
        # Check ICCID uniqueness
        if body.iccid:
            conflict = await conn.fetchval(
                "SELECT sim_id::text FROM sim_profiles WHERE iccid = $1 AND sim_id != $2::uuid",
                body.iccid, sim_id,
            )
            if conflict:
                raise HTTPException(
                    status_code=409,
                    detail={"error": "iccid_conflict", "iccid": body.iccid, "existing_sim_id": conflict},
                )
        updates.append(f"iccid = ${idx}")
        params.append(body.iccid)
        idx += 1

    if body.account_name is not None:
        updates.append(f"account_name = ${idx}")
        params.append(body.account_name)
        idx += 1

    if body.status is not None:
        if body.status not in ("active", "suspended", "terminated"):
            _val_err("status", "must be active, suspended, or terminated")
        updates.append(f"status = ${idx}")
        params.append(body.status)
        idx += 1

    if body.ip_resolution is not None:
        if body.ip_resolution not in IP_RES_VALUES:
            _val_err("ip_resolution", f"must be one of {IP_RES_VALUES}")
        # When switching to APN-sensitive mode, verify existing IMSIs have specific-APN entries
        if body.ip_resolution in ("imsi_apn",):
            has_apn = await conn.fetchval(
                """
                SELECT EXISTS(
                    SELECT 1 FROM imsi_apn_ips sa
                    JOIN imsi2sim si ON si.imsi = sa.imsi
                    WHERE si.sim_id = $1::uuid AND sa.apn IS NOT NULL
                )
                """,
                sim_id,
            )
            if not has_apn:
                _val_err("ip_resolution", "switching to imsi_apn requires existing APN-specific apn_ips entries")
        updates.append(f"ip_resolution = ${idx}")
        params.append(body.ip_resolution)
        idx += 1

    if body.metadata is not None:
        updates.append(f"metadata = ${idx}::jsonb")
        params.append(json.dumps(body.metadata))
        idx += 1

    if updates:
        updates.append("updated_at = now()")
        params.append(sim_id)
        await conn.execute(
            f"UPDATE sim_profiles SET {', '.join(updates)} WHERE sim_id = ${idx}::uuid",
            *params,
        )

    # Handle iccid_ips update
    if body.iccid_ips is not None:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM sim_apn_ips WHERE sim_id = $1::uuid", sim_id
            )
            for iip in body.iccid_ips:
                await conn.execute(
                    """
                    INSERT INTO sim_apn_ips (sim_id, apn, static_ip, pool_id, pool_name)
                    VALUES ($1::uuid, $2, $3::inet, $4::uuid, $5)
                    """,
                    sim_id, iip.apn, iip.static_ip, iip.pool_id, iip.pool_name,
                )

    return await _build_profile_response(sim_id, conn)


@router.post("/profiles/{sim_id}/release-ips", dependencies=[Depends(require_auth)])
async def release_ips(sim_id: str, conn=Depends(get_conn)):
    existing = await conn.fetchrow(
        "SELECT sim_id FROM sim_profiles WHERE sim_id = $1::uuid AND status != 'terminated'",
        sim_id,
    )
    if not existing:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "subscriber_profile", "sim_id": sim_id},
        )

    async with conn.transaction():
        imsi_rows = await conn.fetch(
            """
            SELECT pool_id::text, host(static_ip) AS ip, imsi, apn
            FROM imsi_apn_ips
            WHERE imsi IN (SELECT imsi FROM imsi2sim WHERE sim_id = $1::uuid)
              AND pool_id IS NOT NULL
            """,
            sim_id,
        )
        sim_rows = await conn.fetch(
            """
            SELECT pool_id::text, host(static_ip) AS ip, apn
            FROM sim_apn_ips
            WHERE sim_id = $1::uuid AND pool_id IS NOT NULL
            """,
            sim_id,
        )

        if imsi_rows:
            await conn.execute(
                "DELETE FROM imsi_apn_ips "
                "WHERE imsi IN (SELECT imsi FROM imsi2sim WHERE sim_id = $1::uuid) "
                "AND pool_id IS NOT NULL",
                sim_id,
            )
            await conn.executemany(
                "INSERT INTO ip_pool_available (pool_id, ip) VALUES ($1::uuid, $2::inet) ON CONFLICT DO NOTHING",
                [(r["pool_id"], r["ip"]) for r in imsi_rows],
            )

        if sim_rows:
            await conn.execute(
                "DELETE FROM sim_apn_ips WHERE sim_id = $1::uuid AND pool_id IS NOT NULL",
                sim_id,
            )
            await conn.executemany(
                "INSERT INTO ip_pool_available (pool_id, ip) VALUES ($1::uuid, $2::inet) ON CONFLICT DO NOTHING",
                [(r["pool_id"], r["ip"]) for r in sim_rows],
            )

    released = (
        [{"imsi": r["imsi"], "apn": r["apn"], "ip": r["ip"], "pool_id": r["pool_id"]} for r in imsi_rows]
        + [{"imsi": None, "apn": r["apn"], "ip": r["ip"], "pool_id": r["pool_id"]} for r in sim_rows]
    )
    return {"released_count": len(released), "ips_released": released}


@router.delete("/profiles/{sim_id}", status_code=204, dependencies=[Depends(require_auth)])
async def delete_profile(sim_id: str, conn=Depends(get_conn)):
    existing = await conn.fetchrow(
        "SELECT sim_id FROM sim_profiles WHERE sim_id = $1::uuid AND status != 'terminated'",
        sim_id,
    )
    if not existing:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "subscriber_profile", "sim_id": sim_id},
        )
    async with conn.transaction():
        # Hard-delete child rows so IMSI and IPs are freed for reuse.
        # imsi_apn_ips cascades automatically via FK ON DELETE CASCADE on imsi2sim.imsi.
        await conn.execute("DELETE FROM imsi2sim WHERE sim_id = $1::uuid", sim_id)
        await conn.execute("DELETE FROM sim_apn_ips WHERE sim_id = $1::uuid", sim_id)
        # Soft-delete: keep the sim_id row for audit trail.
        # Clear iccid so the same ICCID can be assigned to a new profile (NULL is non-unique).
        await conn.execute(
            "UPDATE sim_profiles SET status='terminated', iccid=NULL, updated_at=now() "
            "WHERE sim_id=$1::uuid",
            sim_id,
        )
