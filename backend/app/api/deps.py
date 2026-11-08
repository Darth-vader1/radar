import hashlib
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Callable, List, Optional
from fastapi import Depends, Header, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.rate_limit import enforce_rate_limit
from app.core.security import decode_token
from app.database.session import AsyncSessionLocal
from app.models.auth import ApiKey, Role, User

security_bearer = HTTPBearer(auto_error=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_HEADER = "X-Requested-With"


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    bearer_creds: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> User:
    """
    Authenticates requests via, in order: Bearer token (JWT or API key), X-API-Key header,
    or the web app's httpOnly access cookie.
    """
    token_str: Optional[str] = bearer_creds.credentials if bearer_creds else None

    # Case 1: Check Bearer token (JWT or raw API key passed in auth header)
    if token_str:
        if token_str.startswith("radar_live_"):
            return await _authenticate_api_key(db, token_str, request)
        return await _authenticate_access_token(db, token_str)

    # Case 2: Check X-API-Key header
    if x_api_key:
        return await _authenticate_api_key(db, x_api_key, request)

    # Case 3: Browser session cookie. Cookies are sent automatically by the browser, so
    # state-changing requests must also carry a custom header, which cross-site forms
    # cannot set and cross-origin scripts cannot send without passing CORS preflight.
    cookie_token = request.cookies.get(settings.ACCESS_COOKIE_NAME)
    if cookie_token:
        if request.method not in SAFE_METHODS and not request.headers.get(CSRF_HEADER):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing {CSRF_HEADER} header for cookie-authenticated request.",
            )
        return await _authenticate_access_token(db, cookie_token)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide Bearer token or X-API-Key header.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _authenticate_access_token(db: AsyncSession, token_str: str) -> User:
    payload = decode_token(token_str)
    if not payload or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, expired, or non-access authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = uuid.UUID(payload.get("sub"))
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject.")

    stmt = (
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.roles).selectinload(Role.permissions))
    )
    user = (await db.execute(stmt)).scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User account not found.")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive.")
    if payload.get("ver", 0) != (user.token_version or 0):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been revoked. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def _authenticate_api_key(db: AsyncSession, raw_key: str, request: Request) -> User:
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    stmt = (
        select(ApiKey)
        .where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
        .options(selectinload(ApiKey.user).selectinload(User.roles).selectinload(Role.permissions))
    )
    api_key_obj = (await db.execute(stmt)).scalar_one_or_none()

    if not api_key_obj or not api_key_obj.user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API key.")

    now = datetime.now(timezone.utc)
    if api_key_obj.expires_at is not None and api_key_obj.expires_at <= now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key has expired.")

    if not api_key_obj.user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account associated with API key is inactive.")

    # Scopes: "read" allows safe methods only; "write" (or "admin") is needed to change anything.
    scopes = {s.lower() for s in (api_key_obj.scopes or [])}
    needed = "read" if request.method in SAFE_METHODS else "write"
    if not (needed in scopes or "admin" in scopes or (needed == "read" and "write" in scopes)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"API key lacks the '{needed}' scope required for {request.method} requests.",
        )

    await enforce_rate_limit(
        f"apikey:{api_key_obj.id}",
        api_key_obj.rate_limit_per_minute,
        60,
        detail="API key rate limit exceeded.",
    )

    api_key_obj.last_used_at = now
    return api_key_obj.user


def require_roles(allowed_roles: List[str]) -> Callable:
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        user_role_names = [r.name.lower() for r in current_user.roles]
        if "super_admin" in user_role_names:
            return current_user

        for allowed in allowed_roles:
            if allowed.lower() in user_role_names:
                return current_user

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Operation requires one of roles: {allowed_roles}",
        )
    return role_checker


def require_permission(permission_code: str) -> Callable:
    async def permission_checker(current_user: User = Depends(get_current_user)) -> User:
        user_role_names = [r.name.lower() for r in current_user.roles]
        if "super_admin" in user_role_names:
            return current_user

        all_permissions = set()
        for role in current_user.roles:
            for perm in role.permissions:
                all_permissions.add(perm.code)

        if permission_code in all_permissions:
            return current_user

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Operation requires permission: '{permission_code}'",
        )
    return permission_checker
