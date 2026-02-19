"""Shared database module for Houston's Tracker (Postgres via asyncpg)."""

import os
import logging
import asyncpg

log = logging.getLogger("houstons.db")

_pool: asyncpg.Pool | None = None

DATABASE_URL = os.environ.get("DATABASE_URL", "")


async def get_pool() -> asyncpg.Pool:
    """Return (and lazily create) the asyncpg connection pool."""
    global _pool
    if _pool is None:
        dsn = DATABASE_URL
        # Render gives postgres:// but asyncpg needs postgresql://
        if dsn.startswith("postgres://"):
            dsn = dsn.replace("postgres://", "postgresql://", 1)
        _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
        log.info("asyncpg pool created (min=2, max=10)")
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        log.info("asyncpg pool closed")


async def fetch(query: str, *args):
    """Fetch rows as list of dicts."""
    pool = await get_pool()
    rows = await pool.fetch(query, *args)
    return [dict(r) for r in rows]


async def fetchrow(query: str, *args):
    """Fetch single row as dict or None."""
    pool = await get_pool()
    row = await pool.fetchrow(query, *args)
    return dict(row) if row else None


async def fetchval(query: str, *args):
    """Fetch single value."""
    pool = await get_pool()
    return await pool.fetchval(query, *args)


async def execute(query: str, *args):
    """Execute a statement."""
    pool = await get_pool()
    return await pool.execute(query, *args)
