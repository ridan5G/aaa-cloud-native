import json
import asyncpg
from app.config import PRIMARY_URL

_pool: asyncpg.Pool | None = None


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


async def close_db():
    global _pool
    if _pool:
        await _pool.close()


def get_pool() -> asyncpg.Pool:
    return _pool


async def get_conn():
    async with _pool.acquire() as conn:
        yield conn
