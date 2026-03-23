"""
routing_domains.py — CRUD for routing domains and free-CIDR suggestion.

A routing domain is a named uniqueness scope for IP address assignment.
Within one domain, no two pools may have overlapping subnets.
allowed_prefixes (optional CIDR list) restricts which subnets may be created
in the domain and enables the suggest-cidr endpoint.
"""
import ipaddress
import math
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.auth import require_auth
from app.db import get_conn

router = APIRouter()


# ─── Pydantic models ──────────────────────────────────────────────────────────

class RoutingDomainCreate(BaseModel):
    name: str
    description: Optional[str] = None
    allowed_prefixes: List[str] = []


class RoutingDomainPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    allowed_prefixes: Optional[List[str]] = None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _validation_error(field: str, message: str):
    raise HTTPException(
        status_code=400,
        detail={"error": "validation_failed", "details": [{"field": field, "message": message}]},
    )


def _validate_prefixes(prefixes: List[str]):
    for p in prefixes:
        try:
            ipaddress.ip_network(p, strict=False)
        except ValueError:
            _validation_error("allowed_prefixes", f"invalid CIDR notation: {p}")


def _row_to_dict(row) -> dict:
    d = dict(row)
    d["allowed_prefixes"] = list(d.get("allowed_prefixes") or [])
    return d


def _find_free_cidr(
    allowed_prefixes: List[str],
    existing_subnets: List[str],
    size: int,
) -> Optional[str]:
    """
    Find the smallest CIDR block with >= `size` usable host IPs that does not
    overlap any existing subnet and falls within one of the allowed_prefixes.

    Usable hosts for a /P = 2^(32-P) - 2.
    Returns the CIDR string or None if no free block is found within 10,000 candidates.
    """
    # Smallest prefix_len (largest block) where usable hosts >= size
    prefix_len = math.floor(32 - math.log2(size + 2))
    prefix_len = max(0, min(30, prefix_len))  # clamp: /30 is the smallest useful

    existing_networks = [
        ipaddress.ip_network(s, strict=False) for s in existing_subnets
    ]

    for prefix_str in allowed_prefixes:
        allowed_net = ipaddress.ip_network(prefix_str, strict=False)
        if prefix_len < allowed_net.prefixlen:
            # Requested block would be larger than the allowed prefix — skip
            continue

        count = 0
        for candidate in allowed_net.subnets(new_prefix=prefix_len):
            count += 1
            if count > 10_000:
                break  # safety cap — avoids timeout on huge address spaces
            if not any(candidate.overlaps(en) for en in existing_networks):
                return str(candidate)

    return None


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/routing-domains", status_code=201, dependencies=[Depends(require_auth)])
async def create_routing_domain(body: RoutingDomainCreate, conn=Depends(get_conn)):
    if not body.name or not body.name.strip():
        _validation_error("name", "must not be empty")
    _validate_prefixes(body.allowed_prefixes)

    try:
        row = await conn.fetchrow(
            """
            INSERT INTO routing_domains (name, description, allowed_prefixes)
            VALUES ($1, $2, $3::text[])
            RETURNING id::text, name
            """,
            body.name,
            body.description,
            body.allowed_prefixes,
        )
    except Exception as e:
        if "unique" in str(e).lower() or "uq_routing_domain_name" in str(e).lower():
            raise HTTPException(
                status_code=409,
                detail={"error": "domain_name_conflict", "name": body.name},
            )
        raise
    return {"id": row["id"], "name": row["name"]}


@router.get("/routing-domains", dependencies=[Depends(require_auth)])
async def list_routing_domains(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=100, ge=1, le=1000),
    conn=Depends(get_conn),
):
    offset = (page - 1) * limit
    total = await conn.fetchval("SELECT COUNT(*) FROM routing_domains")
    rows = await conn.fetch(
        """
        SELECT rd.id::text, rd.name, rd.description, rd.allowed_prefixes,
               rd.created_at, rd.updated_at,
               COUNT(p.pool_id)::int AS pool_count
        FROM routing_domains rd
        LEFT JOIN ip_pools p ON p.routing_domain_id = rd.id
        GROUP BY rd.id
        ORDER BY rd.name
        LIMIT $1 OFFSET $2
        """,
        limit,
        offset,
    )
    return {"items": [_row_to_dict(r) for r in rows], "total": int(total), "page": page}


@router.get("/routing-domains/{domain_id}", dependencies=[Depends(require_auth)])
async def get_routing_domain(domain_id: str, conn=Depends(get_conn)):
    row = await conn.fetchrow(
        """
        SELECT rd.id::text, rd.name, rd.description, rd.allowed_prefixes,
               rd.created_at, rd.updated_at,
               COUNT(p.pool_id)::int AS pool_count
        FROM routing_domains rd
        LEFT JOIN ip_pools p ON p.routing_domain_id = rd.id
        WHERE rd.id = $1::uuid
        GROUP BY rd.id
        """,
        domain_id,
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "routing_domain", "id": domain_id},
        )
    return _row_to_dict(row)


@router.patch("/routing-domains/{domain_id}", dependencies=[Depends(require_auth)])
async def patch_routing_domain(
    domain_id: str, body: RoutingDomainPatch, conn=Depends(get_conn)
):
    row = await conn.fetchrow(
        "SELECT id FROM routing_domains WHERE id = $1::uuid", domain_id
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "routing_domain", "id": domain_id},
        )

    if body.name is not None:
        if not body.name.strip():
            _validation_error("name", "must not be empty")
        try:
            await conn.execute(
                "UPDATE routing_domains SET name=$1, updated_at=now() WHERE id=$2::uuid",
                body.name,
                domain_id,
            )
        except Exception as e:
            if "unique" in str(e).lower():
                raise HTTPException(
                    status_code=409,
                    detail={"error": "domain_name_conflict", "name": body.name},
                )
            raise

    if body.description is not None:
        await conn.execute(
            "UPDATE routing_domains SET description=$1, updated_at=now() WHERE id=$2::uuid",
            body.description,
            domain_id,
        )

    if body.allowed_prefixes is not None:
        _validate_prefixes(body.allowed_prefixes)
        await conn.execute(
            "UPDATE routing_domains SET allowed_prefixes=$1::text[], updated_at=now() WHERE id=$2::uuid",
            body.allowed_prefixes,
            domain_id,
        )

    return {"id": domain_id}


@router.delete(
    "/routing-domains/{domain_id}", status_code=204, dependencies=[Depends(require_auth)]
)
async def delete_routing_domain(domain_id: str, conn=Depends(get_conn)):
    row = await conn.fetchrow(
        "SELECT id FROM routing_domains WHERE id = $1::uuid", domain_id
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "routing_domain", "id": domain_id},
        )

    pool_count = await conn.fetchval(
        "SELECT COUNT(*) FROM ip_pools WHERE routing_domain_id = $1::uuid", domain_id
    )
    if pool_count > 0:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "domain_in_use",
                "id": domain_id,
                "pool_count": int(pool_count),
                "detail": f"Routing domain has {pool_count} pool(s) — delete all pools first",
            },
        )

    await conn.execute("DELETE FROM routing_domains WHERE id = $1::uuid", domain_id)


@router.get("/routing-domains/{domain_id}/suggest-cidr", dependencies=[Depends(require_auth)])
async def suggest_cidr(
    domain_id: str,
    size: int = Query(..., ge=1, description="Minimum number of usable host IPs required"),
    conn=Depends(get_conn),
):
    """
    Find the smallest available CIDR block in this routing domain that provides
    at least `size` usable host IPs and does not overlap any existing pool.

    Requires at least one entry in the domain's `allowed_prefixes` to define
    the search space (returns 422 if allowed_prefixes is empty).
    """
    domain = await conn.fetchrow(
        "SELECT id::text, name, allowed_prefixes FROM routing_domains WHERE id = $1::uuid",
        domain_id,
    )
    if not domain:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "routing_domain", "id": domain_id},
        )

    allowed_prefixes = list(domain["allowed_prefixes"] or [])
    if not allowed_prefixes:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "no_allowed_prefixes",
                "detail": (
                    "Configure allowed_prefixes on this routing domain before using "
                    "suggest-cidr (e.g. PATCH /routing-domains/{id} with "
                    '{"allowed_prefixes": ["10.0.0.0/8"]})'
                ),
            },
        )

    existing = await conn.fetch(
        "SELECT subnet::text FROM ip_pools WHERE routing_domain_id = $1::uuid", domain_id
    )
    existing_subnets = [r["subnet"] for r in existing]

    suggested = _find_free_cidr(allowed_prefixes, existing_subnets, size)
    if suggested is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "no_free_cidr",
                "detail": (
                    f"No free CIDR with {size} usable hosts found in routing domain "
                    f"'{domain['name']}' within the configured allowed_prefixes"
                ),
            },
        )

    prefix_len = ipaddress.ip_network(suggested, strict=False).prefixlen
    usable_hosts = (2 ** (32 - prefix_len)) - 2

    return {
        "suggested_cidr": suggested,
        "prefix_len": prefix_len,
        "usable_hosts": usable_hosts,
        "routing_domain_id": domain["id"],
        "routing_domain_name": domain["name"],
    }
