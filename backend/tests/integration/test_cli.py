import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import cli
from app.core.security import verify_password
from app.models.auth import User

pytestmark = pytest.mark.integration


class _NoDispose:
    async def dispose(self):
        pass


@pytest.fixture
def cli_db(db_sessionmaker, monkeypatch):
    monkeypatch.setattr(cli, "AsyncSessionLocal", db_sessionmaker)
    monkeypatch.setattr(cli, "async_engine", _NoDispose())
    return db_sessionmaker


async def _load(sessionmaker, email):
    async with sessionmaker() as s:
        return await s.scalar(select(User).where(User.email == email).options(selectinload(User.roles)))


async def test_create_admin_creates_verified_super_admin(cli_db, monkeypatch):
    monkeypatch.setenv("RADAR_ADMIN_PASSWORD", "a-very-long-admin-pass")

    outcome = await cli.create_admin("Admin@Example.com", "Ada", reset_password=False)

    user = await _load(cli_db, "admin@example.com")
    assert outcome == "created"
    assert [r.name for r in user.roles] == ["super_admin"]
    assert user.is_verified and user.is_active
    assert verify_password("a-very-long-admin-pass", user.password_hash)


async def test_create_admin_promotes_existing_user_and_can_reset_password(cli_db, monkeypatch):
    monkeypatch.setenv("RADAR_ADMIN_PASSWORD", "first-long-password")
    await cli.create_admin("ops@example.com", None, reset_password=False)
    before = await _load(cli_db, "ops@example.com")

    monkeypatch.setenv("RADAR_ADMIN_PASSWORD", "second-long-password")
    await cli.create_admin("ops@example.com", None, reset_password=True)

    after = await _load(cli_db, "ops@example.com")
    assert verify_password("second-long-password", after.password_hash)
    assert after.token_version == before.token_version + 1  # old sessions revoked
    assert [r.name for r in after.roles] == ["super_admin"]


async def test_create_admin_rejects_short_password(cli_db, monkeypatch):
    monkeypatch.setenv("RADAR_ADMIN_PASSWORD", "short")
    with pytest.raises(SystemExit):
        await cli.create_admin("weak@example.com", None, reset_password=False)
