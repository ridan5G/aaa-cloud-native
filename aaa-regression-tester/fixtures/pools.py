"""
fixtures/pools.py — helpers for creating and tearing down ip_pools.

Each test module that needs a pool calls create_pool() in setup and
delete_pool() in teardown (inside a finally block to guarantee cleanup).
"""
import asyncio
import os

import asyncpg
import httpx

_DB_URL = os.environ.get("DB_URL", "")


def _force_clear_pool_ips(pool_id: str) -> None:
    """Delete all allocated IPs for a pool directly via DB.

    Used when DELETE /pools returns 409 pool_in_use (stale data from an
    interrupted prior run that the API-level flush missed).
    """
    if not _DB_URL:
        return

    async def _run():
        conn = await asyncpg.connect(_DB_URL)
        try:
            # Clear allocated IP rows first (FK dependents of ip_pools)
            await conn.execute(
                "DELETE FROM imsi_apn_ips WHERE pool_id = $1::uuid", pool_id
            )
            await conn.execute(
                "DELETE FROM sim_apn_ips WHERE pool_id = $1::uuid", pool_id
            )
            # Clear APN-pool catalog entries that reference this pool.
            # These may exist when a slot uses pool_id=NULL (APN-only routing) but
            # its per-APN entries still point to this pool — teardown skips them.
            await conn.execute(
                "DELETE FROM range_config_apn_pools WHERE pool_id = $1::uuid", pool_id
            )
            # Clear range configs that reference this pool so DELETE /pools succeeds.
            # iccid_range_configs.pool_id is nullable — only delete rows that match.
            # Deleting iccid_range_configs cascades to imsi slots (imsi_range_configs).
            await conn.execute(
                "DELETE FROM iccid_range_configs WHERE pool_id = $1::uuid", pool_id
            )
            # Standalone imsi_range_configs (pool_id nullable after Gen-5 migration)
            await conn.execute(
                "DELETE FROM imsi_range_configs WHERE pool_id = $1::uuid", pool_id
            )
        finally:
            await conn.close()

    asyncio.run(_run())


def _force_clear_range_profiles(f_imsi: str, t_imsi: str) -> None:
    """Delete sim_profiles for all IMSIs in [f_imsi, t_imsi] directly via DB.

    Cascades: sim_profiles → imsi2sim → imsi_apn_ips
              sim_profiles → sim_apn_ips
    Used before pool fixture yield to ensure no stale profiles from prior runs.
    """
    if not _DB_URL:
        return

    async def _run():
        conn = await asyncpg.connect(_DB_URL)
        try:
            await conn.execute(
                """
                DELETE FROM sim_profiles
                WHERE sim_id IN (
                    SELECT DISTINCT sim_id FROM imsi2sim
                    WHERE imsi >= $1 AND imsi <= $2
                )
                """,
                f_imsi,
                t_imsi,
            )
        finally:
            await conn.close()

    asyncio.run(_run())


def create_pool(
    http: httpx.Client,
    *,
    subnet: str = "100.65.120.0/24",
    pool_name: str = "test-pool",
    account_name: str = "TestAccount",
    routing_domain: str | None = None,
    start_ip: str | None = None,
    end_ip: str | None = None,
    replace_on_conflict: bool = False,
) -> dict:
    """POST /pools and return the full response body including pool_id.

    If replace_on_conflict=True and a 409 pool_overlap is returned, stale
    data referencing the conflicting pool is cleared directly via DB
    (allocated IPs, APN-pool catalog entries, stale range configs), then
    the conflicting pool is deleted and the request is retried once.
    """
    body: dict = {
        "name":         pool_name,
        "account_name": account_name,
        "subnet":       subnet,
    }
    if routing_domain is not None:
        body["routing_domain"] = routing_domain
    if start_ip:
        body["start_ip"] = start_ip
    if end_ip:
        body["end_ip"] = end_ip

    resp = http.post("/pools", json=body)
    if resp.status_code == 409 and replace_on_conflict:
        conflict_id = resp.json().get("conflicting_pool_id")
        if conflict_id:
            # Always proactively clear stale data before attempting delete.
            # This handles both 409 pool_in_use (allocated IPs) and 500 FK-
            # violation (range_config_apn_pools entries left by a teardown that
            # never ran because a prior setup_class raised before completing).
            _force_clear_pool_ips(conflict_id)
            http.delete(f"/pools/{conflict_id}")
            resp = http.post("/pools", json=body)
    assert resp.status_code == 201, f"create_pool failed: {resp.status_code} {resp.text}"
    return resp.json()


def delete_pool(http: httpx.Client, pool_id: str) -> None:
    """DELETE /pools/{pool_id} — best-effort teardown (ignores 404)."""
    resp = http.delete(f"/pools/{pool_id}")
    if resp.status_code not in (204, 404, 409):
        raise AssertionError(
            f"delete_pool({pool_id}) returned unexpected {resp.status_code}: {resp.text}"
        )


def get_pool_stats(http: httpx.Client, pool_id: str) -> dict:
    """GET /pools/{pool_id}/stats and return the body."""
    resp = http.get(f"/pools/{pool_id}/stats")
    assert resp.status_code == 200, f"get_pool_stats failed: {resp.status_code}"
    return resp.json()


def add_pool_subnet(
    http: httpx.Client,
    pool_id: str,
    *,
    subnet: str,
    start_ip: str | None = None,
    end_ip: str | None = None,
) -> httpx.Response:
    """POST /pools/{pool_id}/subnets — add a secondary subnet to an existing pool.

    Returns the raw response so callers can assert on 201 / 409 / 400.
    """
    body: dict = {"subnet": subnet}
    if start_ip:
        body["start_ip"] = start_ip
    if end_ip:
        body["end_ip"] = end_ip
    return http.post(f"/pools/{pool_id}/subnets", json=body)
