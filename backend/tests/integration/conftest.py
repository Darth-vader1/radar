"""
Fixtures for integration tests that run against a real PostgreSQL server.

A dedicated database (default: `<dev db name>_test` on the server from DATABASE_SYNC_URL,
or RADAR_TEST_DATABASE_URL if set) is dropped, recreated and migrated with Alembic once
per test session. Your development database is never touched.

Tests are skipped automatically when the server is unreachable.
"""
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.rate_limit import RateLimiter

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _test_sync_url():
    override = os.environ.get("RADAR_TEST_DATABASE_URL")
    if override:
        return make_url(override).set(drivername="postgresql")
    base = make_url(settings.DATABASE_SYNC_URL)
    return base.set(database=f"{base.database}_test")


def _recreate_database(sync_url) -> None:
    admin_url = sync_url.set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3})
    try:
        with admin_engine.connect() as conn:
            conn.execute(text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :db AND pid <> pg_backend_pid()"
            ), {"db": sync_url.database})
            conn.execute(text(f'DROP DATABASE IF EXISTS "{sync_url.database}"'))
            conn.execute(text(f'CREATE DATABASE "{sync_url.database}"'))
    finally:
        admin_engine.dispose()


def _run_migrations(sync_url) -> None:
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    original = settings.DATABASE_SYNC_URL
    # alembic/env.py reads the URL from settings
    settings.DATABASE_SYNC_URL = sync_url.render_as_string(hide_password=False)
    try:
        command.upgrade(cfg, "head")
    finally:
        settings.DATABASE_SYNC_URL = original


@pytest.fixture(scope="session")
def migrated_test_db_url():
    if os.environ.get("RADAR_SKIP_INTEGRATION"):
        pytest.skip("RADAR_SKIP_INTEGRATION is set")
    sync_url = _test_sync_url()
    try:
        _recreate_database(sync_url)
    except Exception as exc:
        pytest.skip(f"PostgreSQL not reachable for integration tests ({type(exc).__name__}: {exc})")
    _run_migrations(sync_url)
    return sync_url.set(drivername="postgresql+asyncpg")


@pytest.fixture
async def db_sessionmaker(migrated_test_db_url):
    """Async sessionmaker bound to a clean test database (all tables truncated)."""
    engine = create_async_engine(migrated_test_db_url, pool_pre_ping=True)
    async with engine.begin() as conn:
        tables = (await conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
        ))).scalars().all()
        if tables:
            quoted = ", ".join(f'"{t}"' for t in tables)
            await conn.execute(text(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE"))
    try:
        yield async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    finally:
        await engine.dispose()


class LocalOnlyRateLimiter(RateLimiter):
    """Rate limiter that never touches Redis, so tests are isolated from each other and dev data."""

    def _client(self):
        raise ConnectionError("redis disabled in tests")


@pytest.fixture
async def client(db_sessionmaker, monkeypatch):
    """httpx client for the real FastAPI app, bound to the clean test database."""
    import httpx

    from app.api import deps
    from app.core import rate_limit as rate_limit_module
    from app.main import app

    async def override_get_db():
        async with db_sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    monkeypatch.setattr(rate_limit_module, "rate_limiter", LocalOnlyRateLimiter())
    monkeypatch.setattr(settings, "ALLOW_PUBLIC_REGISTRATION", True)
    app.dependency_overrides[deps.get_db] = override_get_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def db(db_sessionmaker, monkeypatch):
    """Clean test database with adapters registered and the pipeline bound to it."""
    from app.modules.adapters_loader import load_adapters
    from app.modules.scraping import pipeline as pipeline_module

    load_adapters()
    monkeypatch.setattr(pipeline_module, "AsyncSessionLocal", db_sessionmaker)
    return db_sessionmaker
