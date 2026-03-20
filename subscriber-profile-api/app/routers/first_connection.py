"""
POST /first-connection — aaa-radius-server fallback allocation.

Called when aaa-lookup-service returns 404 for an unknown IMSI.
Allocates IPs from the matching range config's pool(s) and permanently
creates a subscriber profile. Returns 201 on new allocation, 200 if the
IMSI was already provisioned (idempotent).

Multi-IMSI SIM support
──────────────────────
When the matched range config belongs to an ICCID range group ALL sibling
IMSIs are pre-provisioned in the same transaction, each drawing its own IP(s)
from its own slot pool(s). This prevents a thundering herd when all SIMs fail
over simultaneously — subsequent IMSI connections are served by the
idempotency path (single indexed read, no allocation, no write).

APN catalog provisioning
────────────────────────
For ip_resolution='imsi_apn' or 'iccid_apn', range_config_apn_pools defines
ALL APNs to provision for the range. On first-connection, IPs are allocated
for every defined APN in a single transaction:
  apn1 → pool-A IP, apn2 → pool-B IP
enabling full multi-APN auto-allocation (e.g. 2 IMSIs × 2 APNs = 4 IPs).

If the connecting APN is absent from the table it is added using the default
pool. If no entries exist, only the connecting APN is provisioned (backward-
compatible fallback for single-APN ranges).
"""
import re
import json
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from app.db import get_conn
from app.auth import require_auth
from app.metrics import (
    first_connection_total,
    pool_exhausted_total,
    multi_imsi_siblings_provisioned_total,
)

router = APIRouter()
logger = logging.getLogger(__name__)

IMSI_RE = re.compile(r"^\d{15}$")


class FirstConnectionRequest(BaseModel):
    imsi: str
    apn: str
    imei: str = ""
    use_case_id: Optional[str] = None


async def _allocate_ip(conn, pool_id: str) -> Optional[str]:
    """Claim one IP from ip_pool_available. Returns None if pool is exhausted."""
    return await conn.fetchval(
        """
        DELETE FROM ip_pool_available
        WHERE ip = (
            SELECT ip FROM ip_pool_available
            WHERE pool_id = $1::uuid
            ORDER BY ip LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING host(ip)
        """,
        pool_id,
    )


async def _load_apn_pools(
    conn, range_config_id: int, default_pool: str, ip_resolution: str, request_apn: str
) -> list[tuple[Optional[str], str]]:
    """Return (apn, pool_id) pairs to allocate in a single transaction.

    - imsi / iccid modes:   [(None, default_pool)]  — single IP, APN-agnostic.
    - imsi_apn / iccid_apn: all APNs from range_config_apn_pools, ensuring
      request_apn is included (using default_pool if not explicitly mapped).
      Falls back to [(request_apn, default_pool)] when no entries are defined.
    """
    if ip_resolution not in ("imsi_apn", "iccid_apn"):
        return [(None, default_pool)]

    rows = await conn.fetch(
        "SELECT apn, COALESCE(pool_id, $2::uuid)::text AS pool_id "
        "FROM range_config_apn_pools WHERE range_config_id = $1",
        range_config_id, default_pool,
    )

    if not rows:
        return [(request_apn, default_pool)]

    pairs: dict[str, str] = {row["apn"]: row["pool_id"] for row in rows}
    if request_apn not in pairs:
        pairs[request_apn] = default_pool
    return list(pairs.items())


@router.post("/first-connection", dependencies=[Depends(require_auth)])
@router.post("/profiles/first-connection", dependencies=[Depends(require_auth)])
async def first_connection(body: FirstConnectionRequest, conn=Depends(get_conn)):
    if not IMSI_RE.match(body.imsi):
        raise HTTPException(
            status_code=400,
            detail={"error": "validation_failed", "details": [{"field": "imsi", "message": "must be 15 digits"}]},
        )
    if not body.apn:
        raise HTTPException(
            status_code=400,
            detail={"error": "validation_failed", "details": [{"field": "apn", "message": "required field missing"}]},
        )

    # ── Idempotency: return existing allocation if IMSI already provisioned ────
    existing_imsi = await conn.fetchrow(
        "SELECT sim_id::text FROM imsi2sim WHERE imsi = $1",
        body.imsi,
    )
    if existing_imsi:
        sim_id = existing_imsi["sim_id"]
        # Prefer exact APN match; fall back to apn=NULL (imsi/iccid modes store NULL).
        static_ip = await conn.fetchval(
            "SELECT host(static_ip) FROM imsi_apn_ips WHERE imsi = $1 AND (apn = $2 OR apn IS NULL) ORDER BY apn NULLS LAST LIMIT 1",
            body.imsi, body.apn,
        )
        if not static_ip:
            static_ip = await conn.fetchval(
                "SELECT host(static_ip) FROM sim_apn_ips WHERE sim_id = $1::uuid AND (apn = $2 OR apn IS NULL) ORDER BY apn NULLS LAST LIMIT 1",
                sim_id, body.apn,
            )
        first_connection_total.labels(result="reused").inc()
        logger.info(
            '{"path":"/first-connection","imsi":"%s","result":"reused","idempotent":true,"use_case_id":"%s"}',
            body.imsi,
            body.use_case_id or "",
        )
        return JSONResponse(
            status_code=200,
            content={"sim_id": sim_id, "static_ip": static_ip},
        )

    # Step 1: Find matching range config.
    # COALESCE prefers the slot's own pool_id; parent ICCID range pool is fallback.
    range_row = await conn.fetchrow(
        """
        SELECT irc.id, irc.f_imsi, irc.iccid_range_id, irc.imsi_slot,
               COALESCE(irc.pool_id, ir.pool_id)::text AS pool_id,
               COALESCE(ir.ip_resolution, irc.ip_resolution) AS ip_resolution,
               COALESCE(ir.account_name, irc.account_name) AS account_name,
               ir.f_iccid, ir.id AS iccid_range_id_val
        FROM imsi_range_configs irc
        LEFT JOIN iccid_range_configs ir ON ir.id = irc.iccid_range_id
        WHERE irc.f_imsi <= $1 AND irc.t_imsi >= $1 AND irc.status = 'active'
        ORDER BY irc.f_imsi
        LIMIT 1
        """,
        body.imsi,
    )

    if not range_row:
        first_connection_total.labels(result="not_found").inc()
        logger.info(
            '{"path":"/first-connection","imsi":"%s","result":"not_found","use_case_id":"%s"}',
            body.imsi,
            body.use_case_id or "",
        )
        raise HTTPException(status_code=404, detail={"error": "not_found"})

    pool_id = range_row["pool_id"]
    ip_resolution = range_row["ip_resolution"]
    account_name = range_row["account_name"]
    iccid_range_id = range_row["iccid_range_id"]
    range_config_id = range_row["id"]

    # ── Single-IMSI path ──────────────────────────────────────────────────────
    if iccid_range_id is None:
        async with conn.transaction():
            apn_pools = await _load_apn_pools(conn, range_config_id, pool_id, ip_resolution, body.apn)
            allocated_ip = None

            metadata = json.dumps({"tags": ["auto-allocated"], "imei": body.imei})
            sim_id = await conn.fetchval(
                """
                INSERT INTO sim_profiles (account_name, status, ip_resolution, metadata)
                VALUES ($1, 'active', $2, $3::jsonb)
                RETURNING sim_id::text
                """,
                account_name, ip_resolution, metadata,
            )

            await conn.execute(
                "INSERT INTO imsi2sim (imsi, sim_id, status, priority) VALUES ($1, $2::uuid, 'active', 1)",
                body.imsi, sim_id,
            )

            request_apn_val = body.apn if ip_resolution in ("imsi_apn", "iccid_apn") else None
            for apn_val, apn_pool in apn_pools:
                ip = await _allocate_ip(conn, apn_pool)
                if not ip:
                    first_connection_total.labels(result="pool_exhausted").inc()
                    pool_exhausted_total.labels(pool_id=apn_pool).inc()
                    raise HTTPException(
                        status_code=503,
                        detail={"error": "pool_exhausted", "pool_id": apn_pool},
                    )
                if ip_resolution in ("imsi", "imsi_apn"):
                    await conn.execute(
                        "INSERT INTO imsi_apn_ips (imsi, apn, static_ip, pool_id) VALUES ($1, $2, $3::inet, $4::uuid)",
                        body.imsi, apn_val, ip, apn_pool,
                    )
                else:  # iccid / iccid_apn
                    await conn.execute(
                        "INSERT INTO sim_apn_ips (sim_id, apn, static_ip, pool_id) VALUES ($1::uuid, $2, $3::inet, $4::uuid)",
                        sim_id, apn_val, ip, apn_pool,
                    )
                if apn_val == request_apn_val:
                    allocated_ip = ip

        first_connection_total.labels(result="allocated").inc()
        logger.info(
            '{"path":"/first-connection","imsi":"%s","result":"allocated","multi_imsi":false,"pool_id":"%s","apns_provisioned":%d,"use_case_id":"%s"}',
            body.imsi,
            pool_id,
            len(apn_pools),
            body.use_case_id or "",
        )
        return JSONResponse(
            status_code=201,
            content={"sim_id": sim_id, "static_ip": allocated_ip},
        )

    # ── Multi-IMSI SIM path ───────────────────────────────────────────────────
    f_imsi = range_row["f_imsi"]
    f_iccid = range_row["f_iccid"]
    offset = int(body.imsi) - int(f_imsi)
    iccid_len = len(f_iccid)
    derived_iccid = str(int(f_iccid) + offset).zfill(iccid_len)

    async with conn.transaction():
        existing = await conn.fetchrow(
            "SELECT sim_id::text FROM sim_profiles WHERE iccid = $1 FOR UPDATE",
            derived_iccid,
        )

        if existing:
            # Card already exists — sibling slot connected first and pre-provisioned
            # all siblings including this one. This branch is the safety net for edge
            # cases (crash mid-transaction, manual imsi2sim removal, etc.).
            sim_id = existing["sim_id"]
            await conn.execute(
                "INSERT INTO imsi2sim (imsi, sim_id, status, priority) VALUES ($1, $2::uuid, 'active', $3) ON CONFLICT DO NOTHING",
                body.imsi, sim_id, range_row["imsi_slot"],
            )

            if ip_resolution in ("imsi", "imsi_apn"):
                request_apn_val = None if ip_resolution == "imsi" else body.apn
                # Check if this IMSI+APN was already pre-provisioned.
                allocated_ip = await conn.fetchval(
                    "SELECT host(static_ip) FROM imsi_apn_ips WHERE imsi = $1 AND apn IS NOT DISTINCT FROM $2",
                    body.imsi, request_apn_val,
                )
                if not allocated_ip:
                    # Not pre-provisioned (crash recovery) — allocate all APNs now.
                    apn_pools = await _load_apn_pools(conn, range_config_id, pool_id, ip_resolution, body.apn)
                    for apn_val, apn_pool in apn_pools:
                        ip = await _allocate_ip(conn, apn_pool)
                        if not ip:
                            first_connection_total.labels(result="pool_exhausted").inc()
                            pool_exhausted_total.labels(pool_id=apn_pool).inc()
                            raise HTTPException(
                                status_code=503,
                                detail={"error": "pool_exhausted", "pool_id": apn_pool},
                            )
                        await conn.execute(
                            "INSERT INTO imsi_apn_ips (imsi, apn, static_ip, pool_id) VALUES ($1, $2, $3::inet, $4::uuid) ON CONFLICT DO NOTHING",
                            body.imsi, apn_val, ip, apn_pool,
                        )
                        if apn_val == request_apn_val:
                            allocated_ip = ip
            else:
                apn_val = None if ip_resolution == "iccid" else body.apn
                allocated_ip = await conn.fetchval(
                    "SELECT host(static_ip) FROM sim_apn_ips WHERE sim_id = $1::uuid AND apn IS NOT DISTINCT FROM $2 LIMIT 1",
                    sim_id, apn_val,
                )

            first_connection_total.labels(result="reused").inc()
            logger.info(
                '{"path":"/first-connection","imsi":"%s","result":"reused","multi_imsi":true,"pool_id":"%s","use_case_id":"%s"}',
                body.imsi,
                pool_id,
                body.use_case_id or "",
            )
            return JSONResponse(
                status_code=200,
                content={"sim_id": sim_id, "static_ip": allocated_ip},
            )

        # ── First slot to connect for this card ───────────────────────────────
        # Load all APNs to provision for this slot.
        apn_pools = await _load_apn_pools(conn, range_config_id, pool_id, ip_resolution, body.apn)
        allocated_ip = None

        metadata = json.dumps({"tags": ["auto-allocated", "multi-imsi"], "imei": body.imei})
        sim_id = await conn.fetchval(
            """
            INSERT INTO sim_profiles (account_name, status, ip_resolution, iccid, metadata)
            VALUES ($1, 'active', $2, $3, $4::jsonb)
            RETURNING sim_id::text
            """,
            account_name, ip_resolution, derived_iccid, metadata,
        )

        await conn.execute(
            "INSERT INTO imsi2sim (imsi, sim_id, status, priority) VALUES ($1, $2::uuid, 'active', $3)",
            body.imsi, sim_id, range_row["imsi_slot"],
        )

        request_apn_val = body.apn if ip_resolution in ("imsi_apn", "iccid_apn") else None
        for apn_val, apn_pool in apn_pools:
            ip = await _allocate_ip(conn, apn_pool)
            if not ip:
                first_connection_total.labels(result="pool_exhausted").inc()
                pool_exhausted_total.labels(pool_id=apn_pool).inc()
                raise HTTPException(
                    status_code=503,
                    detail={"error": "pool_exhausted", "pool_id": apn_pool},
                )
            if ip_resolution in ("imsi", "imsi_apn"):
                await conn.execute(
                    "INSERT INTO imsi_apn_ips (imsi, apn, static_ip, pool_id) VALUES ($1, $2, $3::inet, $4::uuid)",
                    body.imsi, apn_val, ip, apn_pool,
                )
            else:  # iccid / iccid_apn
                await conn.execute(
                    "INSERT INTO sim_apn_ips (sim_id, apn, static_ip, pool_id) VALUES ($1::uuid, $2, $3::inet, $4::uuid)",
                    sim_id, apn_val, ip, apn_pool,
                )
            if apn_val == request_apn_val:
                allocated_ip = ip

        # Pre-provision all OTHER sibling slots for this card in the same transaction.
        # Each sibling gets IPs for all its defined APNs, preventing a thundering herd.
        sibling_rows = await conn.fetch(
            """
            SELECT id, f_imsi, imsi_slot, pool_id::text AS pool_id
            FROM imsi_range_configs
            WHERE iccid_range_id = $1 AND status = 'active' AND id != $2
            """,
            iccid_range_id, range_config_id,
        )

        siblings_provisioned = 0
        for sibling in sibling_rows:
            sibling_imsi = str(int(sibling["f_imsi"]) + offset).zfill(15)
            sibling_base_pool = sibling["pool_id"] or pool_id

            await conn.execute(
                "INSERT INTO imsi2sim (imsi, sim_id, status, priority) VALUES ($1, $2::uuid, 'active', $3) ON CONFLICT DO NOTHING",
                sibling_imsi, sim_id, sibling["imsi_slot"],
            )

            if ip_resolution in ("imsi", "imsi_apn"):
                # Load all APNs for this sibling's slot (each slot may have its own overrides).
                sibling_apn_pools = await _load_apn_pools(
                    conn, sibling["id"], sibling_base_pool, ip_resolution, body.apn
                )
                for apn_val, apn_pool in sibling_apn_pools:
                    sibling_ip = await _allocate_ip(conn, apn_pool)
                    if not sibling_ip:
                        pool_exhausted_total.labels(pool_id=apn_pool).inc()
                        raise HTTPException(
                            status_code=503,
                            detail={"error": "pool_exhausted", "pool_id": apn_pool},
                        )
                    await conn.execute(
                        "INSERT INTO imsi_apn_ips (imsi, apn, static_ip, pool_id) VALUES ($1, $2, $3::inet, $4::uuid) ON CONFLICT DO NOTHING",
                        sibling_imsi, apn_val, sibling_ip, apn_pool,
                    )
            # iccid/iccid_apn: card-level sim_apn_ips rows already inserted above.

            siblings_provisioned += 1

        multi_imsi_siblings_provisioned_total.inc(siblings_provisioned)

    first_connection_total.labels(result="allocated").inc()
    logger.info(
        '{"path":"/first-connection","imsi":"%s","result":"allocated","multi_imsi":true,"siblings_provisioned":%d,"pool_id":"%s","apns_provisioned":%d,"use_case_id":"%s"}',
        body.imsi,
        siblings_provisioned,
        pool_id,
        len(apn_pools),
        body.use_case_id or "",
    )
    return JSONResponse(
        status_code=201,
        content={"sim_id": sim_id, "static_ip": allocated_ip},
    )
