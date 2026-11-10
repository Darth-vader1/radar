"""
Auth & session security tests through the real FastAPI app against PostgreSQL.
Covers: no first-user-admin, registration gating, cookie sessions + CSRF header,
refresh rotation and reuse detection, logout / logout-all, login rate limiting,
and API key scopes.
"""
import uuid

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.auth import RefreshToken, Role, User

pytestmark = pytest.mark.integration

API = settings.API_V1_PREFIX
CSRF = {"X-Requested-With": "test"}
PASSWORD = "correct-horse-battery"


def new_email() -> str:
    return f"user-{uuid.uuid4().hex[:10]}@example.com"


async def register_and_login(client, email=None):
    email = email or new_email()
    r = await client.post(f"{API}/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    r = await client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return email, r.json()


async def make_admin(db_sessionmaker, email):
    async with db_sessionmaker() as s:
        user = await s.scalar(select(User).where(User.email == email))
        role = await s.scalar(select(Role).where(Role.name == "super_admin"))
        if role is None:
            role = Role(name="super_admin")
            s.add(role)
        user.roles.append(role)
        await s.commit()


# --- Registration ---

async def test_first_registered_user_is_not_admin(client):
    r = await client.post(f"{API}/auth/register", json={"email": new_email(), "password": PASSWORD})
    assert r.status_code == 201
    assert [role["name"] for role in r.json()["roles"]] == ["standard_user"]


async def test_role_in_register_payload_is_ignored(client):
    r = await client.post(
        f"{API}/auth/register",
        json={"email": new_email(), "password": PASSWORD, "role": "super_admin"},
    )
    assert [role["name"] for role in r.json()["roles"]] == ["standard_user"]


async def test_registration_can_be_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_PUBLIC_REGISTRATION", False)
    r = await client.post(f"{API}/auth/register", json={"email": new_email(), "password": PASSWORD})
    assert r.status_code == 403


async def test_short_password_rejected(client):
    r = await client.post(f"{API}/auth/register", json={"email": new_email(), "password": "short"})
    assert r.status_code == 422


# --- Cookie sessions & CSRF ---

async def test_login_sets_httponly_cookies_and_cookie_auth_works(client):
    await register_and_login(client)

    set_cookies = client.cookies
    assert settings.ACCESS_COOKIE_NAME in set_cookies
    assert settings.SESSION_HINT_COOKIE_NAME in set_cookies

    r = await client.get(f"{API}/auth/me")  # no Authorization header: cookie only
    assert r.status_code == 200


async def test_login_cookie_flags(client):
    email = new_email()
    await client.post(f"{API}/auth/register", json={"email": email, "password": PASSWORD})
    r = await client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
    raw = r.headers.get_list("set-cookie")
    access = next(c for c in raw if c.startswith(settings.ACCESS_COOKIE_NAME))
    refresh = next(c for c in raw if c.startswith(settings.REFRESH_COOKIE_NAME))
    assert "HttpOnly" in access and "SameSite=lax" in access
    assert "HttpOnly" in refresh and f"Path={API}/auth" in refresh


async def test_cookie_auth_requires_csrf_header_for_writes(client):
    await register_and_login(client)

    blocked = await client.post(f"{API}/auth/api-keys", json={"name": "k1"})
    assert blocked.status_code == 403
    assert "X-Requested-With" in blocked.json()["detail"]

    allowed = await client.post(f"{API}/auth/api-keys", json={"name": "k1"}, headers=CSRF)
    assert allowed.status_code == 201


async def test_bearer_auth_does_not_need_csrf_header(client):
    _, tokens = await register_and_login(client)
    client.cookies.clear()
    r = await client.post(
        f"{API}/auth/api-keys", json={"name": "k1"},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert r.status_code == 201


# --- Refresh rotation & reuse detection ---

async def test_refresh_rotates_and_old_token_is_single_use(client):
    _, tokens = await register_and_login(client)
    client.cookies.clear()
    first = tokens["refresh_token"]

    r = await client.post(f"{API}/auth/refresh", json={"refresh_token": first})
    assert r.status_code == 200
    second = r.json()["refresh_token"]
    assert second != first

    # Replaying the first token is treated as theft...
    replay = await client.post(f"{API}/auth/refresh", json={"refresh_token": first})
    assert replay.status_code == 401
    # ...and revokes the whole family, including the legitimately rotated token.
    after = await client.post(f"{API}/auth/refresh", json={"refresh_token": second})
    assert after.status_code == 401


async def test_refresh_via_cookie_requires_csrf_header(client):
    await register_and_login(client)
    assert (await client.post(f"{API}/auth/refresh")).status_code == 403
    assert (await client.post(f"{API}/auth/refresh", headers=CSRF)).status_code == 200


async def test_refresh_token_not_accepted_as_query_param(client):
    _, tokens = await register_and_login(client)
    client.cookies.clear()
    r = await client.post(f"{API}/auth/refresh?refresh_token={tokens['refresh_token']}")
    assert r.status_code == 401


async def test_logout_revokes_refresh_and_clears_cookies(client, db_sessionmaker):
    _, tokens = await register_and_login(client)

    r = await client.post(f"{API}/auth/logout", headers=CSRF)
    assert r.status_code == 204
    assert settings.ACCESS_COOKIE_NAME not in client.cookies

    r = await client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401
    async with db_sessionmaker() as s:
        rows = (await s.scalars(select(RefreshToken))).all()
        assert rows and all(row.revoked_at is not None for row in rows)


async def test_logout_all_invalidates_existing_access_tokens(client):
    _, tokens = await register_and_login(client)
    client.cookies.clear()
    bearer = {"Authorization": f"Bearer {tokens['access_token']}"}

    assert (await client.get(f"{API}/auth/me", headers=bearer)).status_code == 200
    assert (await client.post(f"{API}/auth/logout-all", headers=bearer)).status_code == 204
    assert (await client.get(f"{API}/auth/me", headers=bearer)).status_code == 401


# --- Rate limiting ---

async def test_login_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_RATE_LIMIT_PER_MINUTE", 3)
    email = new_email()
    codes = [
        (await client.post(f"{API}/auth/login", json={"email": email, "password": "wrong-password"})).status_code
        for _ in range(5)
    ]
    assert codes[:3] == [401, 401, 401]
    assert codes[3] == 429
    blocked = await client.post(f"{API}/auth/login", json={"email": email, "password": "wrong-password"})
    assert "Retry-After" in blocked.headers


# --- API keys ---

async def _api_key(client, scopes, rate=60):
    r = await client.post(
        f"{API}/auth/api-keys",
        json={"name": "test", "scopes": scopes, "rate_limit_per_minute": rate},
        headers=CSRF,
    )
    assert r.status_code == 201, r.text
    return r.json()["raw_api_key"]


async def test_read_scope_key_cannot_write(client, db_sessionmaker):
    email, _ = await register_and_login(client)
    await make_admin(db_sessionmaker, email)
    key = await _api_key(client, ["read"])
    client.cookies.clear()

    assert (await client.get(f"{API}/sources", headers={"X-API-Key": key})).status_code == 200
    r = await client.post(
        f"{API}/sources/{uuid.uuid4()}/toggle", headers={"X-API-Key": key}
    )
    assert r.status_code == 403
    assert "write" in r.json()["detail"]


async def test_api_key_rate_limit_enforced(client):
    await register_and_login(client)
    key = await _api_key(client, ["read"], rate=2)
    client.cookies.clear()

    codes = [(await client.get(f"{API}/auth/me", headers={"X-API-Key": key})).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


# --- Response hardening ---

async def test_security_headers_present(client):
    r = await client.get(f"{API}/health/live")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
