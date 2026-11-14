"""Settings page APIs: profile, password change, active sessions, user administration, integrations."""
import pytest
from sqlalchemy import select
from test_auth_api import CSRF, PASSWORD, make_admin, register_and_login

from app.core.config import settings
from app.models.auth import Role, User

pytestmark = pytest.mark.integration
API = settings.API_V1_PREFIX
NEW_PASSWORD = "a-brand-new-passphrase"


async def two_devices(client):
    """Signs in twice: device A keeps only its tokens (bearer/refresh), device B is the cookie session."""
    email, tokens_a = await register_and_login(client)
    client.cookies.clear()
    r = await client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200
    return email, tokens_a


async def test_profile_name_update(client, db):
    await register_and_login(client)
    r = await client.patch(f"{API}/auth/me", json={"full_name": "  Ada Lovelace  "}, headers=CSRF)
    assert r.status_code == 200 and r.json()["full_name"] == "Ada Lovelace"
    r = await client.patch(f"{API}/auth/me", json={"full_name": ""}, headers=CSRF)
    assert r.json()["full_name"] is None


async def test_change_password_signs_out_other_devices_but_keeps_this_one(client, db):
    email, tokens_a = await two_devices(client)
    bearer_a = {"Authorization": f"Bearer {tokens_a['access_token']}"}
    assert (await client.get(f"{API}/auth/me", headers=bearer_a)).status_code == 200

    wrong = await client.post(f"{API}/auth/change-password",
                              json={"current_password": "nope", "new_password": NEW_PASSWORD}, headers=CSRF)
    assert wrong.status_code == 400
    same = await client.post(f"{API}/auth/change-password",
                             json={"current_password": PASSWORD, "new_password": PASSWORD}, headers=CSRF)
    assert same.status_code == 400
    short = await client.post(f"{API}/auth/change-password",
                              json={"current_password": PASSWORD, "new_password": "short"}, headers=CSRF)
    assert short.status_code == 422

    r = await client.post(f"{API}/auth/change-password",
                          json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}, headers=CSRF)
    assert r.status_code == 204

    # This browser (cookies) is still signed in and can keep refreshing.
    assert (await client.get(f"{API}/auth/me")).status_code == 200
    assert (await client.post(f"{API}/auth/refresh", headers=CSRF)).status_code == 200
    # Device A is out: its access token and refresh token no longer work.
    assert (await client.get(f"{API}/auth/me", headers=bearer_a)).status_code == 401
    assert (await client.post(f"{API}/auth/refresh", json={"refresh_token": tokens_a["refresh_token"]})).status_code == 401

    # Only the new password works now.
    client.cookies.clear()
    assert (await client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})).status_code == 401
    assert (await client.post(f"{API}/auth/login", json={"email": email, "password": NEW_PASSWORD})).status_code == 200


async def test_sessions_list_revoke_and_logout_others(client, db):
    _, tokens_a = await two_devices(client)
    await client.post(f"{API}/auth/refresh", headers=CSRF)  # rotation keeps one session per device

    sessions = (await client.get(f"{API}/auth/sessions")).json()
    assert len(sessions) == 2
    assert sessions[0]["current"] is True and sessions[1]["current"] is False

    # Can't revoke this browser's own session from the list.
    assert (await client.delete(f"{API}/auth/sessions/{sessions[0]['id']}", headers=CSRF)).status_code == 400
    assert (await client.delete(f"{API}/auth/sessions/{sessions[1]['id']}", headers=CSRF)).status_code == 204
    assert len((await client.get(f"{API}/auth/sessions")).json()) == 1
    assert (await client.post(f"{API}/auth/refresh", json={"refresh_token": tokens_a["refresh_token"]})).status_code == 401

    # Sign in a third device, then sign out all others in one go.
    email = (await client.get(f"{API}/auth/me")).json()["email"]
    cookies = dict(client.cookies)
    client.cookies.clear()
    third = (await client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})).json()
    client.cookies.clear()
    for k, v in cookies.items():
        client.cookies.set(k, v)
    r = await client.post(f"{API}/auth/logout-others", headers=CSRF)
    assert r.status_code == 200 and r.json() == {"sessions_ended": 1}
    assert (await client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {third['access_token']}"})).status_code == 401
    assert (await client.get(f"{API}/auth/me")).status_code == 200  # still signed in here
    assert [s["current"] for s in (await client.get(f"{API}/auth/sessions")).json()] == [True]


async def test_sessions_are_private(client, db):
    await register_and_login(client)
    mine = (await client.get(f"{API}/auth/sessions")).json()[0]["id"]
    client.cookies.clear()
    await register_and_login(client)
    assert (await client.delete(f"{API}/auth/sessions/{mine}", headers=CSRF)).status_code == 404


# --- user administration ---

async def ensure_roles(db):
    async with db() as s:
        for name in ("super_admin", "admin", "researcher", "standard_user"):
            if await s.scalar(select(Role).where(Role.name == name)) is None:
                s.add(Role(name=name))
        await s.commit()


async def set_role(db, email, role_name):
    async with db() as s:
        user = await s.scalar(select(User).where(User.email == email))
        role = await s.scalar(select(Role).where(Role.name == role_name))
        await s.refresh(user, ["roles"])
        user.roles = [role]
        await s.commit()


async def user_id(client, email):
    users = (await client.get(f"{API}/admin/users", params={"search": email})).json()
    return users[0]["id"]


async def test_standard_users_cannot_administer(client, db):
    await register_and_login(client)
    assert (await client.get(f"{API}/admin/users")).status_code == 403


async def test_super_admin_manages_roles_and_deactivation(client, db):
    await ensure_roles(db)
    target_email, target_tokens = await register_and_login(client)
    client.cookies.clear()
    admin_email, _ = await register_and_login(client)
    await make_admin(db, admin_email)
    await set_role(db, admin_email, "super_admin")

    tid = await user_id(client, target_email)
    r = await client.patch(f"{API}/admin/users/{tid}", json={"role": "researcher"}, headers=CSRF)
    assert r.status_code == 200 and [x["name"] for x in r.json()["roles"]] == ["researcher"]

    r = await client.patch(f"{API}/admin/users/{tid}", json={"is_active": False}, headers=CSRF)
    assert r.status_code == 200 and r.json()["is_active"] is False
    bearer = {"Authorization": f"Bearer {target_tokens['access_token']}"}
    assert (await client.get(f"{API}/auth/me", headers=bearer)).status_code in (401, 403)  # locked out at once

    # Can't change yourself, and the last super admin can't be removed by anyone.
    me = await user_id(client, admin_email)
    assert (await client.patch(f"{API}/admin/users/{me}", json={"role": "standard_user"}, headers=CSRF)).status_code == 400


async def test_admin_cannot_touch_administrators(client, db):
    await ensure_roles(db)
    super_email, _ = await register_and_login(client)
    await set_role(db, super_email, "super_admin")
    client.cookies.clear()
    plain_email, _ = await register_and_login(client)
    client.cookies.clear()
    admin_email, _ = await register_and_login(client)
    await set_role(db, admin_email, "admin")

    plain = await user_id(client, plain_email)
    sup = await user_id(client, super_email)
    assert (await client.patch(f"{API}/admin/users/{plain}", json={"role": "researcher"}, headers=CSRF)).status_code == 200
    assert (await client.patch(f"{API}/admin/users/{plain}", json={"role": "admin"}, headers=CSRF)).status_code == 403
    assert (await client.patch(f"{API}/admin/users/{sup}", json={"is_active": False}, headers=CSRF)).status_code == 403


async def test_last_super_admin_is_protected(client, db):
    from app.api.v1.admin import _active_super_admins

    await ensure_roles(db)
    first, _ = await register_and_login(client)
    await set_role(db, first, "super_admin")
    client.cookies.clear()
    second, _ = await register_and_login(client)
    await set_role(db, second, "super_admin")

    first_id = await user_id(client, first)
    second_id = await user_id(client, second)
    # With two super admins, one may demote the other...
    assert (await client.patch(f"{API}/admin/users/{first_id}", json={"role": "admin"}, headers=CSRF)).status_code == 200
    async with db() as s:
        assert await _active_super_admins(s) == 1
    # ...but the remaining one can't demote or deactivate itself, so there is always a super admin.
    for change in ({"role": "admin"}, {"is_active": False}):
        assert (await client.patch(f"{API}/admin/users/{second_id}", json=change, headers=CSRF)).status_code == 400


async def test_integrations_report_status_without_values(client, db, monkeypatch):
    from app.api.v1 import admin as admin_module
    from app.models.source import Source

    async with db() as s:
        s.add(Source(slug="kaggle_competitions", name="Kaggle", module_type="EVENT", source_category="x",
                     base_url="https://x", collection_method="OFFICIAL_API", adapter_key="kaggle_competitions",
                     required_env_vars=["KAGGLE_USERNAME", "KAGGLE_KEY"]))
        await s.commit()
    secrets = {"KAGGLE_KEY": "KGAT_secret_value"}
    monkeypatch.setattr(admin_module, "get_credential", lambda name: secrets.get(name))

    await register_and_login(client)
    r = await client.get(f"{API}/admin/integrations")
    assert r.status_code == 200
    assert "KGAT_secret_value" not in r.text
    kaggle = next(i for i in r.json() if i["key"] == "kaggle_competitions")
    assert kaggle["configured"] is False
    assert kaggle["credentials"] == [
        {"name": "KAGGLE_USERNAME", "configured": False}, {"name": "KAGGLE_KEY", "configured": True},
    ]
    assert {i["key"] for i in r.json()} >= {"ai", "sentry"}
