import json
import asyncpg
from app.config import PRIMARY_URL

_pool: asyncpg.Pool | None = None

INIT_SQL = """
CREATE TABLE IF NOT EXISTS bulk_jobs (
    job_id      UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    status      TEXT        NOT NULL DEFAULT 'queued',
    submitted   INT         NOT NULL DEFAULT 0,
    processed   INT         NOT NULL DEFAULT 0,
    failed      INT         NOT NULL DEFAULT 0,
    errors      JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Routing domain: safe to run on every startup (idempotent).
ALTER TABLE ip_pools ADD COLUMN IF NOT EXISTS
    routing_domain TEXT NOT NULL DEFAULT 'default';

CREATE INDEX IF NOT EXISTS idx_pools_routing_domain ON ip_pools (routing_domain);
"""


async def _init_conn(conn):
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )
    await conn.set_type_codec(
        "json",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def init_db():
    global _pool
    _pool = await asyncpg.create_pool(
        PRIMARY_URL,
        min_size=2,
        max_size=20,
        init=_init_conn,
    )
    async with _pool.acquire() as conn:
        await conn.execute(INIT_SQL)


async def close_db():
    global _pool
    if _pool:
        await _pool.close()


def get_pool() -> asyncpg.Pool:
    return _pool


async def get_conn():
    async with _pool.acquire() as conn:
        yield conn
