"""
POST /first-connection — FreeRADIUS fallback allocation.

Called when aaa-lookup-service returns 404 for an unknown IMSI.
Allocates an IP from the matching range config's pool and permanently
creates a subscriber profile. Returns 201 on new allocation, 200 if the
IMSI was already provisioned (idempotent).
"""
import re
import json
import logging
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


@router.post("/first-connection", dependencies=[Depends(require_auth)])
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
        "SELECT device_id::text FROM subscriber_imsis WHERE imsi = $1",
        body.imsi,
    )
    if existing_imsi:
        device_id = existing_imsi["device_id"]
        static_ip = await conn.fetchval(
            "SELECT static_ip::text FROM subscriber_apn_ips WHERE imsi = $1 LIMIT 1",
            body.imsi,
        )
        if not static_ip:
            static_ip = await conn.fetchval(
                "SELECT static_ip::text FROM subscriber_iccid_ips WHERE device_id = $1::uuid LIMIT 1",
                device_id,
            )
        first_connection_total.labels(result="reused").inc()
        logger.info(
            '{"path":"/first-connection","imsi_hash":"%s","result":"reused","idempotent":true}',
            body.imsi[:4] + "***",
        )
        return JSONResponse(
            status_code=200,
            content={"device_id": device_id, "static_ip": static_ip},
        )

    # Step 1: Find matching range config
    range_row = await conn.fetchrow(
        """
        SELECT irc.id, irc.f_imsi, irc.iccid_range_id, irc.imsi_slot,
               COALESCE(ir.pool_id, irc.pool_id)::text AS pool_id,
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
            '{"path":"/first-connection","imsi_hash":"%s","result":"not_found"}',
            body.imsi[:4] + "***",
        )
        raise HTTPException(status_code=404, detail={"error": "not_found"})

    pool_id = range_row["pool_id"]
    ip_resolution = range_row["ip_resolution"]
    account_name = range_row["account_name"]
    iccid_range_id = range_row["iccid_range_id"]

    # ── Single-IMSI path ──────────────────────────────────────────────────────
    if iccid_range_id is None:
        async with conn.transaction():
            allocated_ip = await conn.fetchval(
                """
                DELETE FROM ip_pool_available
                WHERE ip = (
                    SELECT ip FROM ip_pool_available
                    WHERE pool_id = $1::uuid
                    ORDER BY ip LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING ip::text
                """,
                pool_id,
            )
            if not allocated_ip:
                first_connection_total.labels(result="pool_exhausted").inc()
                pool_exhausted_total.labels(pool_id=pool_id).inc()
                raise HTTPException(
                    status_code=503,
                    detail={"error": "pool_exhausted", "pool_id": pool_id},
                )

            metadata = json.dumps({"tags": ["auto-allocated"], "imei": body.imei})
            device_id = await conn.fetchval(
                """
                INSERT INTO subscriber_profiles (account_name, status, ip_resolution, metadata)
                VALUES ($1, 'active', $2, $3::jsonb)
                RETURNING device_id::text
                """,
                account_name, ip_resolution, metadata,
            )

            await conn.execute(
                "INSERT INTO subscriber_imsis (imsi, device_id, status, priority) VALUES ($1, $2::uuid, 'active', 1)",
                body.imsi, device_id,
            )

            if ip_resolution in ("imsi", "imsi_apn"):
                apn_val = None if ip_resolution == "imsi" else body.apn
                await conn.execute(
                    "INSERT INTO subscriber_apn_ips (imsi, apn, static_ip, pool_id) VALUES ($1, $2, $3::inet, $4::uuid)",
                    body.imsi, apn_val, allocated_ip, pool_id,
                )
            elif ip_resolution in ("iccid", "iccid_apn"):
                apn_val = None if ip_resolution == "iccid" else body.apn
                await conn.execute(
                    "INSERT INTO subscriber_iccid_ips (device_id, apn, static_ip, pool_id) VALUES ($1::uuid, $2, $3::inet, $4::uuid)",
                    device_id, apn_val, allocated_ip, pool_id,
                )

        first_connection_total.labels(result="allocated").inc()
        logger.info(
            '{"path":"/first-connection","imsi_hash":"%s","result":"allocated","multi_imsi":false,"pool_id":"%s"}',
            body.imsi[:4] + "***",
            pool_id,
        )
        return JSONResponse(
            status_code=201,
            content={"device_id": device_id, "static_ip": allocated_ip},
        )

    # ── Multi-IMSI SIM path ───────────────────────────────────────────────────
    f_imsi = range_row["f_imsi"]
    f_iccid = range_row["f_iccid"]
    offset = int(body.imsi) - int(f_imsi)
    iccid_len = len(f_iccid)
    derived_iccid = str(int(f_iccid) + offset).zfill(iccid_len)

    async with conn.transaction():
        existing = await conn.fetchrow(
            "SELECT device_id::text FROM subscriber_profiles WHERE iccid = $1 FOR UPDATE",
            derived_iccid,
        )

        if existing:
            # Card already exists — register this IMSI
            device_id = existing["device_id"]
            await conn.execute(
                "INSERT INTO subscriber_imsis (imsi, device_id, status, priority) VALUES ($1, $2::uuid, 'active', $3) ON CONFLICT DO NOTHING",
                body.imsi, device_id, range_row["imsi_slot"],
            )

            if ip_resolution in ("imsi", "imsi_apn"):
                apn_val = None if ip_resolution == "imsi" else body.apn
                existing_ip = await conn.fetchval(
                    """
                    SELECT sa.static_ip::text FROM subscriber_apn_ips sa
                    JOIN subscriber_imsis si ON si.imsi = sa.imsi
                    WHERE si.device_id = $1::uuid LIMIT 1
                    """,
                    device_id,
                )
                if existing_ip:
                    await conn.execute(
                        "INSERT INTO subscriber_apn_ips (imsi, apn, static_ip, pool_id) VALUES ($1, $2, $3::inet, $4::uuid) ON CONFLICT DO NOTHING",
                        body.imsi, apn_val, existing_ip, pool_id,
                    )
                    allocated_ip = existing_ip
                else:
                    allocated_ip = None
            else:
                allocated_ip = await conn.fetchval(
                    "SELECT static_ip::text FROM subscriber_iccid_ips WHERE device_id = $1::uuid LIMIT 1",
                    device_id,
                )

            first_connection_total.labels(result="reused").inc()
            logger.info(
                '{"path":"/first-connection","imsi_hash":"%s","result":"reused","multi_imsi":true,"pool_id":"%s"}',
                body.imsi[:4] + "***",
                pool_id,
            )
            return JSONResponse(
                status_code=200,
                content={"device_id": device_id, "static_ip": allocated_ip},
            )

        # First slot for this card: allocate one IP
        allocated_ip = await conn.fetchval(
            """
            DELETE FROM ip_pool_available
            WHERE ip = (
                SELECT ip FROM ip_pool_available
                WHERE pool_id = $1::uuid
                ORDER BY ip LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING ip::text
            """,
            pool_id,
        )
        if not allocated_ip:
            first_connection_total.labels(result="pool_exhausted").inc()
            pool_exhausted_total.labels(pool_id=pool_id).inc()
            raise HTTPException(
                status_code=503,
                detail={"error": "pool_exhausted", "pool_id": pool_id},
            )

        metadata = json.dumps({"tags": ["auto-allocated", "multi-imsi"], "imei": body.imei})
        device_id = await conn.fetchval(
            """
            INSERT INTO subscriber_profiles (account_name, status, ip_resolution, iccid, metadata)
            VALUES ($1, 'active', $2, $3, $4::jsonb)
            RETURNING device_id::text
            """,
            account_name, ip_resolution, derived_iccid, metadata,
        )

        if ip_resolution in ("iccid", "iccid_apn"):
            apn_val = None if ip_resolution == "iccid" else body.apn
            await conn.execute(
                "INSERT INTO subscriber_iccid_ips (device_id, apn, static_ip, pool_id) VALUES ($1::uuid, $2, $3::inet, $4::uuid)",
                device_id, apn_val, allocated_ip, pool_id,
            )

        # Pre-provision all sibling slots
        sibling_rows = await conn.fetch(
            """
            SELECT f_imsi, imsi_slot FROM imsi_range_configs
            WHERE iccid_range_id = $1 AND status = 'active'
            """,
            iccid_range_id,
        )

        siblings_provisioned = 0
        for sibling in sibling_rows:
            sibling_imsi = str(int(sibling["f_imsi"]) + offset).zfill(15)
            await conn.execute(
                "INSERT INTO subscriber_imsis (imsi, device_id, status, priority) VALUES ($1, $2::uuid, 'active', $3) ON CONFLICT DO NOTHING",
                sibling_imsi, device_id, sibling["imsi_slot"],
            )
            if ip_resolution in ("imsi", "imsi_apn"):
                apn_val = None if ip_resolution == "imsi" else body.apn
                await conn.execute(
                    "INSERT INTO subscriber_apn_ips (imsi, apn, static_ip, pool_id) VALUES ($1, $2, $3::inet, $4::uuid) ON CONFLICT DO NOTHING",
                    sibling_imsi, apn_val, allocated_ip, pool_id,
                )
            siblings_provisioned += 1

        multi_imsi_siblings_provisioned_total.inc(siblings_provisioned)

    first_connection_total.labels(result="allocated").inc()
    logger.info(
        '{"path":"/first-connection","imsi_hash":"%s","result":"allocated","multi_imsi":true,"siblings_provisioned":%d,"pool_id":"%s"}',
        body.imsi[:4] + "***",
        siblings_provisioned,
        pool_id,
    )
    return JSONResponse(
        status_code=201,
        content={"device_id": device_id, "static_ip": allocated_ip},
    )
