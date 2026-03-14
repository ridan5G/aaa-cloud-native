import ipaddress
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.db import get_conn
from app.auth import require_auth

router = APIRouter()


class PoolCreate(BaseModel):
    pool_name: str
    account_name: Optional[str] = None
    subnet: str
    start_ip: Optional[str] = None
    end_ip: Optional[str] = None


class PoolPatch(BaseModel):
    pool_name: Optional[str] = None
    status: Optional[str] = None


def _validation_error(field: str, message: str):
    raise HTTPException(
        status_code=400,
        detail={"error": "validation_failed", "details": [{"field": field, "message": message}]},
    )


def _compute_pool_ips(subnet: str, start_ip: Optional[str], end_ip: Optional[str]):
    try:
        network = ipaddress.ip_network(subnet, strict=False)
    except ValueError:
        _validation_error("subnet", "invalid CIDR notation")

    hosts = list(network.hosts())
    if not hosts:
        _validation_error("subnet", "subnet has no usable host addresses")

    if start_ip and end_ip:
        try:
            s = ipaddress.ip_address(start_ip)
            e = ipaddress.ip_address(end_ip)
        except ValueError:
            _validation_error("start_ip", "invalid IP address")
        ips = [str(h) for h in hosts if s <= h <= e]
        stored_start = start_ip
        stored_end = end_ip
    else:
        # Default: all hosts except the last one (reserved as gateway)
        ips = [str(h) for h in hosts[:-1]]
        stored_start = str(hosts[0])
        stored_end = str(hosts[-1])

    return ips, stored_start, stored_end


@router.post("/pools", status_code=201, dependencies=[Depends(require_auth)])
async def create_pool(body: PoolCreate, conn=Depends(get_conn)):
    ips, stored_start, stored_end = _compute_pool_ips(body.subnet, body.start_ip, body.end_ip)

    pool_id = await conn.fetchval(
        """
        INSERT INTO ip_pools (account_name, pool_name, subnet, start_ip, end_ip)
        VALUES ($1, $2, $3::cidr, $4::inet, $5::inet)
        RETURNING pool_id::text
        """,
        body.account_name,
        body.pool_name,
        body.subnet,
        stored_start,
        stored_end,
    )

    # Pre-populate ip_pool_available in batches
    batch_size = 1000
    for i in range(0, len(ips), batch_size):
        batch = ips[i : i + batch_size]
        await conn.executemany(
            "INSERT INTO ip_pool_available (pool_id, ip) VALUES ($1::uuid, $2::inet)",
            [(pool_id, ip) for ip in batch],
        )

    return {"pool_id": pool_id}


@router.get("/pools/{pool_id}", dependencies=[Depends(require_auth)])
async def get_pool(pool_id: str, conn=Depends(get_conn)):
    row = await conn.fetchrow(
        """
        SELECT pool_id::text, account_name, pool_name,
               subnet::text, start_ip::text, end_ip::text,
               status, created_at, updated_at
        FROM ip_pools WHERE pool_id = $1::uuid
        """,
        pool_id,
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "ip_pool", "pool_id": pool_id},
        )
    return dict(row)


@router.get("/pools", dependencies=[Depends(require_auth)])
async def list_pools(account_name: Optional[str] = None, conn=Depends(get_conn)):
    if account_name:
        rows = await conn.fetch(
            """
            SELECT pool_id::text, account_name, pool_name,
                   subnet::text, start_ip::text, end_ip::text, status
            FROM ip_pools WHERE account_name = $1
            ORDER BY created_at DESC
            """,
            account_name,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT pool_id::text, account_name, pool_name,
                   subnet::text, start_ip::text, end_ip::text, status
            FROM ip_pools ORDER BY created_at DESC
            """
        )
    return {"items": [dict(r) for r in rows]}


@router.get("/pools/{pool_id}/stats", dependencies=[Depends(require_auth)])
async def get_pool_stats(pool_id: str, conn=Depends(get_conn)):
    pool = await conn.fetchrow(
        "SELECT pool_id FROM ip_pools WHERE pool_id = $1::uuid", pool_id
    )
    if not pool:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "ip_pool", "pool_id": pool_id},
        )

    stats = await conn.fetchrow(
        """
        SELECT
            (SELECT COUNT(*) FROM ip_pool_available WHERE pool_id = $1::uuid) AS available,
            (
                SELECT COUNT(*) FROM subscriber_apn_ips sai
                JOIN subscriber_imsis si ON si.imsi = sai.imsi
                JOIN subscriber_profiles sp ON sp.device_id = si.device_id
                WHERE sai.pool_id = $1::uuid
            ) +
            (
                SELECT COUNT(*) FROM subscriber_iccid_ips
                WHERE pool_id = $1::uuid
            ) AS allocated
        """,
        pool_id,
    )

    available = int(stats["available"])
    allocated = int(stats["allocated"])
    return {
        "pool_id": pool_id,
        "total": available + allocated,
        "allocated": allocated,
        "available": available,
    }


@router.patch("/pools/{pool_id}", dependencies=[Depends(require_auth)])
async def patch_pool(pool_id: str, body: PoolPatch, conn=Depends(get_conn)):
    row = await conn.fetchrow(
        "SELECT pool_id FROM ip_pools WHERE pool_id = $1::uuid", pool_id
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "ip_pool", "pool_id": pool_id},
        )

    if body.pool_name is not None:
        await conn.execute(
            "UPDATE ip_pools SET pool_name=$1, updated_at=now() WHERE pool_id=$2::uuid",
            body.pool_name,
            pool_id,
        )
    if body.status is not None:
        if body.status not in ("active", "suspended"):
            _validation_error("status", "must be active or suspended")
        await conn.execute(
            "UPDATE ip_pools SET status=$1, updated_at=now() WHERE pool_id=$2::uuid",
            body.status,
            pool_id,
        )

    return {"pool_id": pool_id}


@router.delete("/pools/{pool_id}", status_code=204, dependencies=[Depends(require_auth)])
async def delete_pool(pool_id: str, conn=Depends(get_conn)):
    row = await conn.fetchrow(
        "SELECT pool_id FROM ip_pools WHERE pool_id = $1::uuid", pool_id
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "ip_pool", "pool_id": pool_id},
        )

    # Check if any IPs are allocated from this pool
    allocated = await conn.fetchval(
        """
        SELECT COUNT(*) FROM (
            SELECT 1 FROM subscriber_apn_ips WHERE pool_id = $1::uuid
            UNION ALL
            SELECT 1 FROM subscriber_iccid_ips WHERE pool_id = $1::uuid
        ) AS combined
        """,
        pool_id,
    )

    if allocated > 0:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "pool_in_use",
                "pool_id": pool_id,
                "allocated": int(allocated),
            },
        )

    await conn.execute("DELETE FROM ip_pools WHERE pool_id = $1::uuid", pool_id)
