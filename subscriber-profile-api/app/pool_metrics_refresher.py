"""Background task that refreshes per-pool IP utilization gauges.

Runs on a fixed interval (POOL_METRICS_REFRESH_SECONDS, default 30 s) and
recomputes total / allocated / available for every pool with subnets in a
single watermark-only query — never touches imsi_apn_ips or sim_apn_ips,
which have no pool_id index.

Stale-label hygiene: when a pool is deleted, its label set is removed from
the gauges so /metrics no longer emits that series.
"""
import asyncio
import logging
import time
import asyncpg

from app.metrics import (
    aaa_pool_total_ips,
    aaa_pool_allocated_ips,
    aaa_pool_available_ips,
    aaa_pool_metrics_refresh_timestamp_seconds,
)

logger = logging.getLogger(__name__)

# Watermark-only — see plan: avoids seq-scan of imsi_apn_ips / sim_apn_ips.
_REFRESH_QUERY = """
SELECT
    p.pool_id::text       AS pool_id,
    COALESCE(p.pool_name, '')    AS pool_name,
    COALESCE(p.account_name, '') AS account_name,
    COALESCE(s.subnet_total, 0)        AS total,
    COALESCE(s.subnet_unclaimed, 0)
        + COALESCE(a.claimed_unallocated, 0) AS available
FROM ip_pools p
LEFT JOIN (
    SELECT pool_id,
           SUM(end_ip - start_ip + 1)                     AS subnet_total,
           SUM((end_ip - start_ip + 1) - next_ip_offset)  AS subnet_unclaimed
    FROM ip_pool_subnets
    GROUP BY pool_id
) s ON s.pool_id = p.pool_id
LEFT JOIN (
    SELECT pool_id, COUNT(*) AS claimed_unallocated
    FROM ip_pool_available
    GROUP BY pool_id
) a ON a.pool_id = p.pool_id
WHERE COALESCE(s.subnet_total, 0) > 0;
"""


async def refresh_once(pool: asyncpg.Pool, previous_labels: set[tuple[str, str, str]]) -> set[tuple[str, str, str]]:
    """Run one refresh cycle. Returns the label set observed this cycle."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(_REFRESH_QUERY)

    current_labels: set[tuple[str, str, str]] = set()
    for r in rows:
        total = int(r["total"])
        available = int(r["available"])
        if available < 0:
            available = 0
        if available > total:
            available = total
        allocated = total - available
        labels = (r["pool_id"], r["pool_name"], r["account_name"])
        current_labels.add(labels)
        aaa_pool_total_ips.labels(*labels).set(total)
        aaa_pool_allocated_ips.labels(*labels).set(allocated)
        aaa_pool_available_ips.labels(*labels).set(available)

    for stale in previous_labels - current_labels:
        aaa_pool_total_ips.remove(*stale)
        aaa_pool_allocated_ips.remove(*stale)
        aaa_pool_available_ips.remove(*stale)

    aaa_pool_metrics_refresh_timestamp_seconds.set(time.time())
    return current_labels


async def run(pool: asyncpg.Pool, interval_seconds: int):
    """Loop forever, refreshing pool gauges every `interval_seconds`.

    interval_seconds <= 0 disables the task entirely.
    Exceptions in a single cycle are logged but never propagate — a transient
    DB blip must not crash the API.
    """
    if interval_seconds <= 0:
        logger.info('"pool metrics refresher disabled (interval=%d)"', interval_seconds)
        return

    previous_labels: set[tuple[str, str, str]] = set()
    logger.info('"pool metrics refresher started, interval=%ds"', interval_seconds)
    while True:
        try:
            previous_labels = await refresh_once(pool, previous_labels)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("pool metrics refresh failed")
        await asyncio.sleep(interval_seconds)
