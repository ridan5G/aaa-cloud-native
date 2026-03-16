"""
POST /profiles/bulk  — async bulk upsert (JSON body list or CSV multipart upload)
GET  /jobs/{job_id} — poll bulk job status
"""
import csv
import io
import json
import logging
import re
import time
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from app.db import get_conn, get_pool
from app.auth import require_auth
from app.config import BULK_BATCH_SIZE
from app.metrics import bulk_job_profiles_total, bulk_job_duration

router = APIRouter()
logger = logging.getLogger(__name__)

IMSI_RE = re.compile(r"^\d{15}$")


class BulkValidationError(ValueError):
    """Raised for per-row validation failures; carries a field name for error reporting."""
    def __init__(self, field: str, message: str):
        self.field = field
        super().__init__(message)


async def _process_bulk_job(job_id: str, profiles: list[dict]):
    start = time.monotonic()
    processed = 0
    failed = 0
    errors = []

    async with get_pool().acquire() as conn:
        for i in range(0, len(profiles), BULK_BATCH_SIZE):
            batch = profiles[i : i + BULK_BATCH_SIZE]
            for row_idx, profile in enumerate(batch, start=i):
                try:
                    await _upsert_profile(conn, profile)
                    processed += 1
                    bulk_job_profiles_total.labels(outcome="processed").inc()
                except BulkValidationError as exc:
                    failed += 1
                    bulk_job_profiles_total.labels(outcome="failed").inc()
                    errors.append({
                        "row": row_idx,
                        "field": exc.field,
                        "message": str(exc),
                    })
                    if len(errors) > 1000:
                        break
                except Exception as exc:
                    failed += 1
                    bulk_job_profiles_total.labels(outcome="failed").inc()
                    errors.append({
                        "row": row_idx,
                        "message": str(exc),
                    })
                    if len(errors) > 1000:
                        break

        elapsed = time.monotonic() - start
        bulk_job_duration.observe(elapsed)

        status = "completed"
        await conn.execute(
            """
            UPDATE bulk_jobs
            SET status=$1, processed=$2, failed=$3, errors=$4::jsonb, updated_at=now()
            WHERE job_id=$5::uuid
            """,
            status,
            processed,
            failed,
            errors,  # asyncpg's jsonb codec handles json.dumps; pre-encoding causes double-encoding
            job_id,
        )

    logger.info(
        '{"job_id":"%s","status":"completed","processed":%d,"failed":%d,"elapsed_s":%.1f}',
        job_id, processed, failed, elapsed,
    )


async def _upsert_profile(conn, profile: dict):
    device_id = profile.get("device_id")
    iccid = profile.get("iccid")
    account_name = profile.get("account_name")
    status = profile.get("status", "active")
    ip_resolution = profile.get("ip_resolution", "imsi")
    metadata = profile.get("metadata")

    # Validate all IMSIs first
    for imsi_entry in profile.get("imsis", []):
        imsi = imsi_entry.get("imsi")
        if imsi and not IMSI_RE.match(imsi):
            raise BulkValidationError("imsi", f"IMSI '{imsi}' must be exactly 15 digits")

    if device_id:
        await conn.execute(
            """
            INSERT INTO device_profiles (device_id, iccid, account_name, status, ip_resolution, metadata)
            VALUES ($1::uuid, $2, $3, $4, $5, $6::jsonb)
            ON CONFLICT (device_id) DO UPDATE
            SET status=EXCLUDED.status, ip_resolution=EXCLUDED.ip_resolution,
                metadata=EXCLUDED.metadata, updated_at=now()
            """,
            device_id,
            iccid,
            account_name,
            status,
            ip_resolution,
            json.dumps(metadata) if metadata else None,
        )
    elif iccid:
        device_id = await conn.fetchval(
            """
            INSERT INTO device_profiles (iccid, account_name, status, ip_resolution, metadata)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            ON CONFLICT (iccid) DO UPDATE
            SET status=EXCLUDED.status, ip_resolution=EXCLUDED.ip_resolution,
                metadata=EXCLUDED.metadata, updated_at=now()
            RETURNING device_id::text
            """,
            iccid,
            account_name,
            status,
            ip_resolution,
            json.dumps(metadata) if metadata else None,
        )
    else:
        device_id = await conn.fetchval(
            """
            INSERT INTO device_profiles (account_name, status, ip_resolution, metadata)
            VALUES ($1, $2, $3, $4::jsonb)
            RETURNING device_id::text
            """,
            account_name,
            status,
            ip_resolution,
            json.dumps(metadata) if metadata else None,
        )

    # Upsert IMSIs and their apn_ips
    for imsi_entry in profile.get("imsis", []):
        imsi = imsi_entry.get("imsi")
        if not imsi:
            continue
        priority = imsi_entry.get("priority", 1)
        await conn.execute(
            """
            INSERT INTO imsi2device (imsi, device_id, priority)
            VALUES ($1, $2::uuid, $3)
            ON CONFLICT (imsi) DO NOTHING
            """,
            imsi, device_id, priority,
        )
        for aip in imsi_entry.get("apn_ips", []):
            static_ip = aip.get("static_ip")
            if not static_ip:
                continue
            await conn.execute(
                """
                INSERT INTO imsi_apn_ips (imsi, apn, static_ip, pool_id, pool_name)
                VALUES ($1, $2, $3::inet, $4::uuid, $5)
                ON CONFLICT ON CONSTRAINT uq_apn_ips_imsi_apn DO UPDATE
                SET static_ip=EXCLUDED.static_ip, pool_id=EXCLUDED.pool_id,
                    pool_name=EXCLUDED.pool_name, updated_at=now()
                """,
                imsi,
                aip.get("apn"),
                static_ip,
                aip.get("pool_id"),
                aip.get("pool_name"),
            )

    # Upsert iccid_ips (card-level IPs)
    for iip in profile.get("iccid_ips", []):
        static_ip = iip.get("static_ip")
        if not static_ip:
            continue
        await conn.execute(
            """
            INSERT INTO device_apn_ips (device_id, apn, static_ip, pool_id, pool_name)
            VALUES ($1::uuid, $2, $3::inet, $4::uuid, $5)
            ON CONFLICT ON CONSTRAINT uq_iccid_ips_device_apn DO UPDATE
            SET static_ip=EXCLUDED.static_ip, pool_id=EXCLUDED.pool_id,
                pool_name=EXCLUDED.pool_name, updated_at=now()
            """,
            device_id,
            iip.get("apn"),
            static_ip,
            iip.get("pool_id"),
            iip.get("pool_name"),
        )


def _parse_csv(text: str) -> list[dict]:
    """Parse flat CSV format into profile dicts.

    Expected columns: iccid, account_name, ip_resolution, imsi, apn, static_ip, pool_id
    One row = one profile with one IMSI. IP is placed in iccid_ips or apn_ips based
    on ip_resolution.
    """
    reader = csv.DictReader(io.StringIO(text))
    profiles = []
    for row in reader:
        iccid = row.get("iccid") or None
        ip_resolution = row.get("ip_resolution", "imsi")
        imsi = row.get("imsi") or None
        apn = row.get("apn") or None
        static_ip = row.get("static_ip") or None
        pool_id = row.get("pool_id") or None

        profile: dict = {
            "iccid": iccid,
            "account_name": row.get("account_name") or None,
            "status": row.get("status", "active"),
            "ip_resolution": ip_resolution,
            "imsis": [],
            "iccid_ips": [],
        }

        if imsi:
            if ip_resolution in ("iccid", "iccid_apn"):
                # IP stored at card level; IMSI has no apn_ips
                profile["imsis"].append({"imsi": imsi, "apn_ips": []})
                if static_ip:
                    profile["iccid_ips"].append({
                        "apn": apn if ip_resolution == "iccid_apn" else None,
                        "static_ip": static_ip,
                        "pool_id": pool_id,
                    })
            else:
                # ip_resolution in (imsi, imsi_apn, ...): IP in apn_ips
                apn_ips = []
                if static_ip:
                    apn_ips.append({
                        "apn": apn if apn else None,
                        "static_ip": static_ip,
                        "pool_id": pool_id,
                    })
                profile["imsis"].append({"imsi": imsi, "apn_ips": apn_ips})

        profiles.append(profile)
    return profiles


@router.post("/profiles/bulk", status_code=202, dependencies=[Depends(require_auth)])
async def bulk_upsert(
    request: Request,
    background_tasks: BackgroundTasks,
    conn=Depends(get_conn),
):
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        file = form.get("file")
        if not file:
            raise HTTPException(
                status_code=400,
                detail={"error": "validation_failed", "details": [{"field": "file", "message": "required"}]},
            )
        content = await file.read()
        text = content.decode("utf-8-sig")
        profiles = _parse_csv(text)
    else:
        body = await request.json()
        if isinstance(body, list):
            profiles = body
        elif isinstance(body, dict):
            profiles = body.get("profiles", [])
        else:
            profiles = []

    if not profiles:
        raise HTTPException(
            status_code=400,
            detail={"error": "validation_failed", "details": [{"field": "profiles", "message": "required"}]},
        )

    submitted = len(profiles)
    job_id = await conn.fetchval(
        "INSERT INTO bulk_jobs (status, submitted) VALUES ('queued', $1) RETURNING job_id::text",
        submitted,
    )

    background_tasks.add_task(_process_bulk_job, job_id, profiles)

    return {
        "job_id": job_id,
        "submitted": submitted,
        "status_url": f"/v1/jobs/{job_id}",
    }


@router.get("/jobs/{job_id}", dependencies=[Depends(require_auth)])
async def get_job(job_id: str, conn=Depends(get_conn)):
    row = await conn.fetchrow(
        """
        SELECT job_id::text, status, submitted, processed, failed, errors
        FROM bulk_jobs WHERE job_id = $1::uuid
        """,
        job_id,
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "resource": "bulk_job", "job_id": job_id},
        )
    result = dict(row)
    if result["errors"] is None:
        result["errors"] = []
    return result
