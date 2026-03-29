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

-- Ensure routing_domains exists.
-- For fresh clusters this is a no-op (CNPG initdb already created it).
-- For pre-existing clusters that pre-date the routing_domains table, this
-- creates it so the API can start; the full schema + migration is applied
-- by 'make db-init' (scripts/db-init.sh) which runs as the postgres superuser.
CREATE TABLE IF NOT EXISTS routing_domains (
    id               UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    name             TEXT        NOT NULL,
    description      TEXT,
    allowed_prefixes TEXT[]      NOT NULL DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_routing_domain_name UNIQUE (name)
);

INSERT INTO routing_domains (name, description)
VALUES ('default', 'Default routing domain')
ON CONFLICT (name) DO NOTHING;

-- NOTE: provisioning_mode columns for imsi_range_configs / iccid_range_configs are
-- added by scripts/db-init.sh (Gen-4 migration block) which runs as the postgres
-- superuser.  aaa_app is not the table owner and cannot ALTER those tables here.

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
