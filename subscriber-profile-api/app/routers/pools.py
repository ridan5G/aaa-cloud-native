import ipaddress
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from app.db import get_conn
from app.auth import require_auth

router = APIRouter()


class PoolCreate(BaseModel):
    name: str
    account_name: Optional[str] = None
    # Accept routing domain by name (backward-compat) or by UUID (preferred).
    # routing_domain_id takes priority if both are supplied.
    routing_domain: str = "default"
    routing_domain_id: Optional[str] = None
    subnet: str
    start_ip: Optional[str] = None
    end_ip: Optional[str] = None


class PoolPatch(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None


class PoolSubnetCreate(BaseModel):
    subnet: str
    start_ip: Optional[str] = None
    end_ip: Optional[str] = None


def _validation_error(field: str, message: str):
    raise HTTPException(
        status_code=400,
        detail={"error": "validation_failed", "details": [{"field": field, "message": message}]},
    )


def _compute_pool_bounds(subnet: str, start_ip: Optional[str], end_ip: Optional[str]):
    """O(1) bounds calculation — does NOT enumerate hosts."""
    try:
        network = ipaddress.ip_network(subnet, strict=False)
    except ValueError:
        _validation_error("subnet", "invalid CIDR notation")

    hosts_iter = network.hosts()
    first_host = next(hosts_iter, None)
    if first_host is None:
        _validation_error("subnet", "subnet has no usable host addresses")

    if start_ip and end_ip:
        try:
            ipaddress.ip_address(start_ip)
            ipaddress.ip_address(end_ip)
        except ValueError:
            _validation_error("start_ip", "invalid IP address")
        return start_ip, end_ip

    # Default: full hosts() range minus the last IP (reserved as gateway).
    # For /24 → .1..253; for /12 → .0.1 .. .15.255.253. Preserves prior behaviour.
    if network.num_addresses < 4:
        # /31, /32 — no gateway reservation possible
        return str(network.network_address + 1), str(network.broadcast_address - 1)
    return str(network.network_address + 1), str(network.broadcast_address - 2)


async def _resolve_routing_domain(body: PoolCreate, conn) -> tuple[str, str]:
    """
    Resolve the routing domain to (routing_domain_id, routing_domain_name).

    Priority:
      1. routing_domain_id (UUID) — look up directly; 404 if not found.
      2. routing_domain (name) — look up by name; auto-create if absent
         (backward-compatible behaviour for callers that only supply a name).
    """
    if body.routing_domain_id:
        row = await conn.fetchrow(
            "SELECT id::text, name FROM routing_domains WHERE id = $1::uuid",
            body.routing_domain_id,
        )
        if not row:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "not_found",
                    "resource": "routing_domain",
                    "id": body.routing_domain_id,
                },
            )
        return row["id"], row["name"]

    # Lookup / auto-create by name
    name = body.routing_domain.strip() if body.routing_domain else "default"
    if not name:
        _validation_error("routing_domain", "must not be empty")

    row = await conn.fetchrow(
        "SELECT id::text, name FROM routing_domains WHERE name = $1", name
    )
    if row:
        return row["id"], row["name"]

    # Auto-create (backward compat: existing callers pass only the domain name)
    new_id = await conn.fetchval(
        "INSERT INTO routing_domains (name) VALUES ($1) ON CONFLICT (name) DO UPDATE SET name=EXCLUDED.name RETURNING id::text",
        name,
    )
    return new_id, name


async def _validate_subnet_in_prefixes(subnet: str, allowed_prefixes: list, conn=None):
    """Validate that subnet is contained within at least one allowed_prefix."""
    if not allowed_prefixes:
        return  # unrestricted domain — all subnets allowed
    net = ipaddress.ip_network(subnet, strict=False)
    for prefix_str in allowed_prefixes:
        try:
            prefix = ipaddress.ip_network(prefix_str, strict=False)
            if net.subnet_of(prefix):
                return
        except ValueError:
            pass
    raise HTTPException(
        status_code=409,
        detail={
            "error": "subnet_outside_allowed_prefixes",
            "detail": (
                f"Subnet {subnet} is not within the allowed prefixes "
                f"for this routing domain: {allowed_prefixes}"
            ),
            "allowed_prefixes": allowed_prefixes,
        },
    )


_OVERLAP_QUERY = """
    WITH all_subnets AS (
        SELECT p.pool_id, p.pool_name, p.subnet
        FROM ip_pools p
        WHERE p.routing_domain_id = $1::uuid
        UNION ALL
        SELECT p.pool_id, p.pool_name, s.subnet
        FROM ip_pool_subnets s
        JOIN ip_pools p ON p.pool_id = s.pool_id
        WHERE p.routing_domain_id = $1::uuid
    )
    SELECT pool_id::text, pool_name, subnet::text
    FROM all_subnets
    WHERE subnet && $2::cidr
    LIMIT 1
"""


@router.post("/pools", status_code=201, dependencies=[Depends(require_auth)])
async def create_pool(body: PoolCreate, conn=Depends(get_conn)):
    stored_start, stored_end = _compute_pool_bounds(body.subnet, body.start_ip, body.end_ip)

    routing_domain_id, routing_domain_name = await _resolve_routing_domain(body, conn)

    # Validate subnet against routing domain's allowed_prefixes
    domain_row = await conn.fetchrow(
        "SELECT allowed_prefixes FROM routing_domains WHERE id = $1::uuid",
        routing_domain_id,
    )
    allowed_prefixes = list(domain_row["allowed_prefixes"] or [])
    await _validate_subnet_in_prefixes(body.subnet, allowed_prefixes)

    # Overlap check across BOTH ip_pools.subnet (primary) and ip_pool_subnets.subnet
    # (secondary subnets added via POST /pools/{id}/subnets).
    overlap = await conn.fetchrow(_OVERLAP_QUERY, routing_domain_id, body.subnet)
    if overlap:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "pool_overlap",
                "detail": (
                    f"Subnet {body.subnet} overlaps with pool '{overlap['pool_name']}' "
                    f"({overlap['subnet']}) in routing domain '{routing_domain_name}'"
                ),
                "conflicting_pool_id": overlap["pool_id"],
            },
        )

    async with conn.transaction():
        pool_id = await conn.fetchval(
            """
            INSERT INTO ip_pools (account_name, pool_name, routing_domain_id, subnet, start_ip, end_ip)
            VALUES ($1, $2, $3::uuid, $4::cidr, $5::inet, $6::inet)
            RETURNING pool_id::text
            """,
            body.account_name,
            body.name,
            routing_domain_id,
            body.subnet,
            stored_start,
            stored_end,
        )

        # Register the primary subnet for lazy claiming. priority=0 → claimed first.
        await conn.execute(
            """
            INSERT INTO ip_pool_subnets (pool_id, subnet, start_ip, end_ip, priority)
            VALUES ($1::uuid, $2::cidr, $3::inet, $4::inet, 0)
            """,
            pool_id,
            body.subnet,
            stored_start,
            stored_end,
        )

    return {"pool_id": pool_id}


@router.post(
    "/pools/{pool_id}/subnets",
    status_code=201,
    dependencies=[Depends(require_auth)],
)
async def add_pool_subnet(
    pool_id: uuid.UUID, body: PoolSubnetCreate, conn=Depends(get_conn)
):
    pool = await conn.fetchrow(
        "SELECT pool_id::text, routing_domain_id::text FROM ip_pools WHERE pool_id = $1::uuid",
        pool_id,
    )
    if not pool:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "ip_pool", "pool_id": str(pool_id)},
        )

    stored_start, stored_end = _compute_pool_bounds(body.subnet, body.start_ip, body.end_ip)

    domain_row = await conn.fetchrow(
        "SELECT name, allowed_prefixes FROM routing_domains WHERE id = $1::uuid",
        pool["routing_domain_id"],
    )
    allowed_prefixes = list(domain_row["allowed_prefixes"] or [])
    await _validate_subnet_in_prefixes(body.subnet, allowed_prefixes)

    overlap = await conn.fetchrow(_OVERLAP_QUERY, pool["routing_domain_id"], body.subnet)
    if overlap:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "pool_overlap",
                "detail": (
                    f"Subnet {body.subnet} overlaps with pool '{overlap['pool_name']}' "
                    f"({overlap['subnet']}) in routing domain '{domain_row['name']}'"
                ),
                "conflicting_pool_id": overlap["pool_id"],
            },
        )

    async with conn.transaction():
        next_priority = await conn.fetchval(
            "SELECT COALESCE(MAX(priority) + 1, 1) FROM ip_pool_subnets WHERE pool_id = $1::uuid",
            pool_id,
        )
        subnet_id = await conn.fetchval(
            """
            INSERT INTO ip_pool_subnets (pool_id, subnet, start_ip, end_ip, priority)
            VALUES ($1::uuid, $2::cidr, $3::inet, $4::inet, $5)
            RETURNING id
            """,
            pool_id,
            body.subnet,
            stored_start,
            stored_end,
            next_priority,
        )

    return {"subnet_id": int(subnet_id), "priority": int(next_priority)}


@router.get("/pools/{pool_id}", dependencies=[Depends(require_auth)])
async def get_pool(pool_id: uuid.UUID, conn=Depends(get_conn)):
    row = await conn.fetchrow(
        """
        SELECT p.pool_id::text, p.account_name, p.pool_name AS name,
               rd.id::text AS routing_domain_id, rd.name AS routing_domain,
               p.subnet::text, p.start_ip::text, p.end_ip::text,
               p.status, p.created_at, p.updated_at
        FROM ip_pools p
        JOIN routing_domains rd ON rd.id = p.routing_domain_id
        WHERE p.pool_id = $1::uuid
        """,
        pool_id,
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "ip_pool", "pool_id": str(pool_id)},
        )
    return dict(row)


@router.get("/pools", dependencies=[Depends(require_auth)])
async def list_pools(
    account_name: Optional[str] = None,
    routing_domain: Optional[str] = None,
    routing_domain_id: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=100, ge=1, le=1000),
    conn=Depends(get_conn),
):
    filters = []
    params = []
    idx = 1

    if account_name:
        filters.append(f"p.account_name = ${idx}")
        params.append(account_name)
        idx += 1
    if routing_domain_id:
        filters.append(f"p.routing_domain_id = ${idx}::uuid")
        params.append(routing_domain_id)
        idx += 1
    elif routing_domain:
        filters.append(f"rd.name = ${idx}")
        params.append(routing_domain)
        idx += 1
    if status:
        if status not in ("active", "suspended"):
            _validation_error("status", "must be active or suspended")
        filters.append(f"p.status = ${idx}")
        params.append(status)
        idx += 1

    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    offset = (page - 1) * limit

    total = await conn.fetchval(
        f"""
        SELECT COUNT(*) FROM ip_pools p
        JOIN routing_domains rd ON rd.id = p.routing_domain_id
        {where}
        """,
        *params,
    )
    rows = await conn.fetch(
        f"""
        SELECT p.pool_id::text, p.account_name, p.pool_name AS name,
               rd.id::text AS routing_domain_id, rd.name AS routing_domain,
               p.subnet::text, p.start_ip::text, p.end_ip::text, p.status,
               (
                   COALESCE(subtot.unclaimed, 0)
                   + COALESCE(avail.cnt, 0)
               )::bigint AS available,
               (
                   CASE WHEN subtot.total IS NOT NULL
                        THEN subtot.total - (COALESCE(subtot.unclaimed, 0) + COALESCE(avail.cnt, 0))
                        ELSE COALESCE(alloc.cnt, 0)
                   END
               )::bigint AS allocated,
               (
                   CASE WHEN subtot.total IS NOT NULL
                        THEN subtot.total
                        ELSE COALESCE(avail.cnt, 0) + COALESCE(alloc.cnt, 0)
                   END
               )::bigint AS total
        FROM ip_pools p
        JOIN routing_domains rd ON rd.id = p.routing_domain_id
        LEFT JOIN (
            SELECT pool_id,
                   SUM((end_ip - start_ip + 1))::bigint AS total,
                   SUM((end_ip - start_ip + 1) - next_ip_offset)::bigint AS unclaimed
            FROM ip_pool_subnets
            GROUP BY pool_id
        ) subtot ON p.pool_id = subtot.pool_id
        LEFT JOIN (
            SELECT pool_id, COUNT(*) AS cnt FROM ip_pool_available GROUP BY pool_id
        ) avail ON p.pool_id = avail.pool_id
        LEFT JOIN (
            SELECT pool_id, COUNT(*) AS cnt FROM sim_apn_ips GROUP BY pool_id
        ) alloc ON p.pool_id = alloc.pool_id
        {where}
        ORDER BY p.created_at DESC
        LIMIT ${idx} OFFSET ${idx + 1}
        """,
        *params,
        limit,
        offset,
    )
    return {"items": [dict(r) for r in rows], "total": int(total), "page": page}


@router.get("/pools/{pool_id}/stats", dependencies=[Depends(require_auth)])
async def get_pool_stats(pool_id: uuid.UUID, conn=Depends(get_conn)):
    pool = await conn.fetchrow(
        "SELECT pool_id FROM ip_pools WHERE pool_id = $1::uuid", pool_id
    )
    if not pool:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "ip_pool", "pool_id": str(pool_id)},
        )

    stats = await conn.fetchrow(
        """
        SELECT
            COALESCE((
                SELECT SUM((end_ip - start_ip + 1))
                FROM ip_pool_subnets WHERE pool_id = $1::uuid
            ), 0) AS subnet_total,
            COALESCE((
                SELECT SUM((end_ip - start_ip + 1) - next_ip_offset)
                FROM ip_pool_subnets WHERE pool_id = $1::uuid
            ), 0) AS subnet_unclaimed,
            (SELECT COUNT(*) FROM ip_pool_available WHERE pool_id = $1::uuid) AS claimed_unallocated,
            (
                SELECT COUNT(*) FROM imsi_apn_ips sai
                JOIN imsi2sim si ON si.imsi = sai.imsi
                JOIN sim_profiles sp ON sp.sim_id = si.sim_id
                WHERE sai.pool_id = $1::uuid
            ) +
            (
                SELECT COUNT(*) FROM sim_apn_ips
                WHERE pool_id = $1::uuid
            ) AS allocated
        """,
        pool_id,
    )

    subnet_total = int(stats["subnet_total"])
    subnet_unclaimed = int(stats["subnet_unclaimed"])
    claimed_unallocated = int(stats["claimed_unallocated"])
    available = subnet_unclaimed + claimed_unallocated
    allocated = subnet_total - available if subnet_total else int(stats["allocated"])
    total = subnet_total if subnet_total else (available + allocated)
    return {
        "pool_id": str(pool_id),
        "total": total,
        "allocated": allocated,
        "available": available,
    }


@router.patch("/pools/{pool_id}", dependencies=[Depends(require_auth)])
async def patch_pool(pool_id: uuid.UUID, body: PoolPatch, conn=Depends(get_conn)):
    row = await conn.fetchrow(
        "SELECT pool_id FROM ip_pools WHERE pool_id = $1::uuid", pool_id
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "ip_pool", "pool_id": str(pool_id)},
        )

    if body.name is not None:
        await conn.execute(
            "UPDATE ip_pools SET pool_name=$1, updated_at=now() WHERE pool_id=$2::uuid",
            body.name,
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

    return {"pool_id": str(pool_id)}


@router.delete("/pools/{pool_id}", status_code=204, dependencies=[Depends(require_auth)])
async def delete_pool(pool_id: uuid.UUID, conn=Depends(get_conn)):
    row = await conn.fetchrow(
        "SELECT pool_id FROM ip_pools WHERE pool_id = $1::uuid", pool_id
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "ip_pool", "pool_id": str(pool_id)},
        )

    in_use = await conn.fetchval(
        """
        SELECT COUNT(*) FROM (
            SELECT 1 FROM imsi_apn_ips           WHERE pool_id = $1::uuid
            UNION ALL
            SELECT 1 FROM sim_apn_ips             WHERE pool_id = $1::uuid
            UNION ALL
            SELECT 1 FROM range_config_apn_pools  WHERE pool_id = $1::uuid
            UNION ALL
            SELECT 1 FROM iccid_range_configs     WHERE pool_id = $1::uuid
            UNION ALL
            SELECT 1 FROM imsi_range_configs      WHERE pool_id = $1::uuid
        ) AS combined
        """,
        pool_id,
    )

    if in_use > 0:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "pool_in_use",
                "pool_id": str(pool_id),
                "in_use": int(in_use),
            },
        )

    await conn.execute("DELETE FROM ip_pools WHERE pool_id = $1::uuid", pool_id)
