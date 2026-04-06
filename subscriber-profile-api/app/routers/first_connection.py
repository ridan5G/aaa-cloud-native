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

IMSI-only support (no ICCID range)
──────────────────────────────────
When f_iccid is absent (NULL), the group has no ICCID bounds. The card is
identified by slot-1's IMSI at the same card offset instead of by a derived
ICCID. sim_profiles are created with iccid=NULL. All other provisioning
semantics (sibling pre-provisioning, idempotency, IP allocation) are identical
to ICCID-range configs.

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
    db_rollbacks_total,
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
    conn, range_config_id: int, default_pool: str, ip_resolution: str,
    request_apn: Optional[str] = None,
) -> list[tuple[Optional[str], str]]:
    """Return (apn, pool_id) pairs to allocate in a single transaction.

    - imsi / iccid modes:   [(None, default_pool)]  — single IP, APN-agnostic.
    - imsi_apn / iccid_apn: all APNs from range_config_apn_pools.
      APN pool entries are MANDATORY for these modes; returns [] when none are
      configured so callers can raise a hard error (missing_apn_config).
      request_apn is added with default_pool if it is not already mapped.
    """
    if ip_resolution not in ("imsi_apn", "iccid_apn"):
        return [(None, default_pool)]

    rows = await conn.fetch(
        "SELECT apn, COALESCE(pool_id, $2::uuid)::text AS pool_id "
        "FROM range_config_apn_pools WHERE range_config_id = $1",
        range_config_id, default_pool,
    )

    if not rows:
        # APN config is mandatory for imsi_apn / iccid_apn — return [] so the
        # caller can surface a clear missing_apn_config error.
        return []

    pairs: dict[str, str] = {row["apn"]: row["pool_id"] for row in rows}
    if request_apn is not None and request_apn not in pairs:
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
        """
        SELECT i.sim_id::text, sp.ip_resolution
        FROM imsi2sim i
        JOIN sim_profiles sp ON sp.sim_id = i.sim_id
        WHERE i.imsi = $1
        """,
        body.imsi,
    )
    # _realloc_sim_id is set when an IMSI exists in imsi2sim but has no IP (IPs were
    # released). The allocation path below reuses the existing profile instead of
    # creating a new one.
    _realloc_sim_id: Optional[str] = None
    if existing_imsi:
        sim_id = existing_imsi["sim_id"]
        existing_ip_resolution = existing_imsi["ip_resolution"]
        # Query the table that matches the profile's current ip_resolution mode.
        # This avoids stale imsi_apn_ips rows that remain after a mode switch to iccid.
        if existing_ip_resolution in ("imsi", "imsi_apn"):
            static_ip = await conn.fetchval(
                "SELECT host(static_ip) FROM imsi_apn_ips WHERE imsi = $1 AND (apn = $2 OR apn IS NULL) ORDER BY apn NULLS LAST LIMIT 1",
                body.imsi, body.apn,
            )
        else:  # iccid, iccid_apn
            static_ip = await conn.fetchval(
                "SELECT host(static_ip) FROM sim_apn_ips WHERE sim_id = $1::uuid AND (apn = $2 OR apn IS NULL) ORDER BY apn NULLS LAST LIMIT 1",
                sim_id, body.apn,
            )
        if static_ip is not None:
            # Normal idempotent path: IP already allocated, return it.
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
        # IPs were released — fall through to range config lookup and re-allocate.
        # The existing profile and imsi2sim row are reused (not recreated).
        _realloc_sim_id = sim_id

    # Step 1: Find matching range config.
    # COALESCE prefers the slot's own pool_id; parent ICCID range pool is fallback.
    range_row = await conn.fetchrow(
        """
        SELECT irc.id, irc.f_imsi, irc.iccid_range_id, irc.imsi_slot,
               COALESCE(irc.pool_id, ir.pool_id)::text AS pool_id,
               COALESCE(ir.ip_resolution, irc.ip_resolution) AS ip_resolution,
               COALESCE(ir.account_name, irc.account_name) AS account_name,
               ir.f_iccid, ir.id AS iccid_range_id_val,
               ir.provisioning_mode AS parent_provisioning_mode
        FROM imsi_range_configs irc
        LEFT JOIN iccid_range_configs ir ON ir.id = irc.iccid_range_id
        WHERE irc.f_imsi <= $1 AND irc.t_imsi >= $1 AND irc.status IN ('active', 'provisioned')
        ORDER BY irc.f_imsi
        LIMIT 1
        """,
        body.imsi,
    )

    if not range_row:
        if _realloc_sim_id:
            # IMSI is provisioned but has no range config — nothing to re-allocate from.
            # Return 200 + null IP (same graceful response as before the re-alloc change).
            first_connection_total.labels(result="reused").inc()
            logger.info(
                '{"path":"/first-connection","imsi":"%s","result":"reused_no_range","use_case_id":"%s"}',
                body.imsi,
                body.use_case_id or "",
            )
            return JSONResponse(
                status_code=200,
                content={"sim_id": _realloc_sim_id, "static_ip": None},
            )
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
            if not apn_pools:
                raise HTTPException(
                    status_code=422,
                    detail={"error": "missing_apn_config",
                            "message": "range config has no APN pool entries for imsi_apn/iccid_apn mode"},
                )
            allocated_ip = None

            if _realloc_sim_id:
                # Re-allocation: profile and imsi2sim already exist; reuse them.
                sim_id = _realloc_sim_id
            else:
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
                    db_rollbacks_total.labels(reason="pool_exhausted").inc()
                    logger.warning(
                        '{"path":"/first-connection","imsi":"%s","result":"pool_exhausted","pool_id":"%s","use_case_id":"%s"}',
                        body.imsi, apn_pool, body.use_case_id or "",
                    )
                    raise HTTPException(
                        status_code=503,
                        detail={"error": "pool_exhausted", "pool_id": apn_pool},
                    )
                if ip_resolution in ("imsi", "imsi_apn"):
                    await conn.execute(
                        "INSERT INTO imsi_apn_ips (imsi, apn, static_ip, pool_id) VALUES ($1, $2, $3::inet, $4::uuid) ON CONFLICT DO NOTHING",
                        body.imsi, apn_val, ip, apn_pool,
                    )
                else:  # iccid / iccid_apn
                    await conn.execute(
                        "INSERT INTO sim_apn_ips (sim_id, apn, static_ip, pool_id) VALUES ($1::uuid, $2, $3::inet, $4::uuid) ON CONFLICT DO NOTHING",
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
    f_iccid = range_row["f_iccid"] or None   # normalize '' → None (IMSI-only configs)
    offset = int(body.imsi) - int(f_imsi)
    have_iccid = bool(f_iccid)

    if have_iccid:
        iccid_len = len(f_iccid)
        derived_iccid = str(int(f_iccid) + offset).zfill(iccid_len)
    else:
        derived_iccid = None
        # IMSI-only: identify the card by slot-1's primary IMSI at this offset.
        # Slot-1 is the canonical card identity when no ICCID range is configured.
        slot1_f_imsi = await conn.fetchval(
            "SELECT f_imsi FROM imsi_range_configs "
            "WHERE iccid_range_id = $1 AND imsi_slot = 1 AND status IN ('active', 'provisioned')",
            iccid_range_id,
        )
        if not slot1_f_imsi:
            first_connection_total.labels(result="not_found").inc()
            raise HTTPException(
                status_code=422,
                detail={"error": "missing_slot1",
                        "message": "IMSI-only range config has no active slot 1 defined"},
            )
        slot1_primary_imsi = str(int(slot1_f_imsi) + offset).zfill(15)

    async with conn.transaction():
        if have_iccid:
            existing = await conn.fetchrow(
                "SELECT sim_id::text FROM sim_profiles WHERE iccid = $1 FOR UPDATE",
                derived_iccid,
            )
        else:
            # IMSI-only: look up the card's sim_profile via slot-1's IMSI in imsi2sim.
            # FOR UPDATE on imsi2sim serialises concurrent first-connections for the same card.
            existing = await conn.fetchrow(
                "SELECT sim_id::text FROM imsi2sim WHERE imsi = $1 FOR UPDATE",
                slot1_primary_imsi,
            )

        if not existing and range_row["parent_provisioning_mode"] == "immediate":
            # Immediate mode: provisioning is driven by the background job (fired when
            # all IMSI slots are registered). If the profile doesn't exist yet the job
            # hasn't run (or not all slots are added). Return 404 to signal "not yet
            # provisioned" rather than creating the profile here.
            first_connection_total.labels(result="not_found").inc()
            raise HTTPException(status_code=404, detail={"error": "not_found"})

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
                    if not apn_pools:
                        raise HTTPException(
                            status_code=422,
                            detail={"error": "missing_apn_config",
                                    "message": "slot has no APN pool entries for imsi_apn/iccid_apn mode"},
                        )
                    for apn_val, apn_pool in apn_pools:
                        ip = await _allocate_ip(conn, apn_pool)
                        if not ip:
                            first_connection_total.labels(result="pool_exhausted").inc()
                            pool_exhausted_total.labels(pool_id=apn_pool).inc()
                            db_rollbacks_total.labels(reason="pool_exhausted").inc()
                            logger.warning(
                                '{"path":"/first-connection","imsi":"%s","result":"pool_exhausted","pool_id":"%s","use_case_id":"%s","multi_imsi":true,"recovery":true}',
                                body.imsi, apn_pool, body.use_case_id or "",
                            )
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
                if not allocated_ip:
                    # IPs were released — re-allocate for this card-level profile.
                    apn_pools = await _load_apn_pools(conn, range_config_id, pool_id, ip_resolution, body.apn)
                    if not apn_pools:
                        raise HTTPException(
                            status_code=422,
                            detail={"error": "missing_apn_config",
                                    "message": "slot has no APN pool entries for iccid_apn mode"},
                        )
                    for pv, pp in apn_pools:
                        ip = await _allocate_ip(conn, pp)
                        if not ip:
                            first_connection_total.labels(result="pool_exhausted").inc()
                            pool_exhausted_total.labels(pool_id=pp).inc()
                            db_rollbacks_total.labels(reason="pool_exhausted").inc()
                            logger.warning(
                                '{"path":"/first-connection","imsi":"%s","result":"pool_exhausted","pool_id":"%s","use_case_id":"%s","multi_imsi":true,"realloc":true}',
                                body.imsi, pp, body.use_case_id or "",
                            )
                            raise HTTPException(
                                status_code=503,
                                detail={"error": "pool_exhausted", "pool_id": pp},
                            )
                        await conn.execute(
                            "INSERT INTO sim_apn_ips (sim_id, apn, static_ip, pool_id) "
                            "VALUES ($1::uuid, $2, $3::inet, $4::uuid) ON CONFLICT DO NOTHING",
                            sim_id, pv, ip, pp,
                        )
                        if pv == apn_val:
                            allocated_ip = ip

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
        if not apn_pools:
            raise HTTPException(
                status_code=422,
                detail={"error": "missing_apn_config",
                        "message": "slot has no APN pool entries for imsi_apn/iccid_apn mode"},
            )
        allocated_ip = None

        metadata = json.dumps({"tags": ["auto-allocated", "multi-imsi"], "imei": body.imei})
        if have_iccid:
            sim_id = await conn.fetchval(
                """
                INSERT INTO sim_profiles (account_name, status, ip_resolution, iccid, metadata)
                VALUES ($1, 'active', $2, $3, $4::jsonb)
                RETURNING sim_id::text
                """,
                account_name, ip_resolution, derived_iccid, metadata,
            )
        else:
            # IMSI-only: create the sim_profile without an ICCID (iccid stays NULL).
            # PostgreSQL UNIQUE constraint on sim_profiles.iccid allows multiple NULLs.
            sim_id = await conn.fetchval(
                """
                INSERT INTO sim_profiles (account_name, status, ip_resolution, metadata)
                VALUES ($1, 'active', $2, $3::jsonb)
                RETURNING sim_id::text
                """,
                account_name, ip_resolution, metadata,
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
                db_rollbacks_total.labels(reason="pool_exhausted").inc()
                logger.warning(
                    '{"path":"/first-connection","imsi":"%s","result":"pool_exhausted","pool_id":"%s","use_case_id":"%s","multi_imsi":true}',
                    body.imsi, apn_pool, body.use_case_id or "",
                )
                raise HTTPException(
                    status_code=503,
                    detail={"error": "pool_exhausted", "pool_id": apn_pool},
                )
            if ip_resolution in ("imsi", "imsi_apn"):
                await conn.execute(
                    "INSERT INTO imsi_apn_ips (imsi, apn, static_ip, pool_id) VALUES ($1, $2, $3::inet, $4::uuid) ON CONFLICT DO NOTHING",
                    body.imsi, apn_val, ip, apn_pool,
                )
            else:  # iccid / iccid_apn
                await conn.execute(
                    "INSERT INTO sim_apn_ips (sim_id, apn, static_ip, pool_id) VALUES ($1::uuid, $2, $3::inet, $4::uuid) ON CONFLICT DO NOTHING",
                    sim_id, apn_val, ip, apn_pool,
                )
            if apn_val == request_apn_val:
                allocated_ip = ip

        # Pre-provision all OTHER sibling slots for this card in the same transaction.
        # Each sibling gets IPs for all its defined APNs, preventing a thundering herd.
        sibling_rows = await conn.fetch(
            """
            SELECT irc.id, irc.f_imsi, irc.imsi_slot,
                   COALESCE(irc.pool_id, ir.pool_id)::text AS pool_id
            FROM imsi_range_configs irc
            JOIN iccid_range_configs ir ON ir.id = irc.iccid_range_id
            WHERE irc.iccid_range_id = $1 AND irc.status IN ('active', 'provisioned') AND irc.id != $2
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
                    conn, sibling["id"], sibling_base_pool, ip_resolution, body.apn,
                )
                if ip_resolution == "imsi_apn" and not sibling_apn_pools:
                    raise HTTPException(
                        status_code=422,
                        detail={"error": "missing_apn_config",
                                "message": f"sibling slot {sibling['imsi_slot']} has no APN pool entries for imsi_apn mode"},
                    )
                for apn_val, apn_pool in sibling_apn_pools:
                    sibling_ip = await _allocate_ip(conn, apn_pool)
                    if not sibling_ip:
                        pool_exhausted_total.labels(pool_id=apn_pool).inc()
                        db_rollbacks_total.labels(reason="pool_exhausted").inc()
                        logger.warning(
                            '{"path":"/first-connection","imsi":"%s","sibling_imsi":"%s","result":"pool_exhausted","pool_id":"%s","use_case_id":"%s","multi_imsi":true,"sibling":true}',
                            body.imsi, sibling_imsi, apn_pool, body.use_case_id or "",
                        )
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
