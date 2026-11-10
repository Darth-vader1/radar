import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import CSRF_HEADER, get_current_user, get_db
from app.core.config import settings
from app.core.rate_limit import client_ip, enforce_rate_limit
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_api_key,
    get_password_hash,
    verify_password,
)
from app.models.auth import ApiKey, AuditLog, RefreshToken, Role, User
from app.schemas.auth import (
    ApiKeyCreate,
    ApiKeyCreatedResponse,
    ApiKeyRead,
    RefreshRequest,
    Token,
    UserCreate,
    UserLogin,
    UserRead,
)

router = APIRouter(prefix="/auth", tags=["Authentication & Users"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, request: Request, db: AsyncSession = Depends(get_db)):
    await enforce_rate_limit(
        f"register:{client_ip(request)}", settings.REGISTER_RATE_LIMIT_PER_HOUR, 3600,
        detail="Too many registration attempts.",
    )
    if not settings.public_registration_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public registration is disabled. Ask an administrator for an account.",
        )

    # Check if user already exists
    existing = await db.scalar(select(User).where(User.email == payload.email.lower()))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email address already exists."
        )

    # Self-registered accounts always get the least-privileged role. Administrators are
    # created out-of-band with `python -m app.cli create-admin` (never "first user wins").
    target_role_name = "standard_user"
    role_obj = await db.scalar(select(Role).where(Role.name == target_role_name))
    if not role_obj:
        # Fallback create role if not seeded
        role_obj = Role(name=target_role_name, description=f"Default {target_role_name}")
        db.add(role_obj)
        await db.flush()

    new_user = User(
        email=payload.email.lower(),
        password_hash=get_password_hash(payload.password),
        full_name=payload.full_name,
        is_active=True,
        is_verified=False,
    )
    new_user.roles.append(role_obj)

    db.add(new_user)
    await db.flush()

    # Log audit event
    audit = AuditLog(
        actor_user_id=new_user.id,
        action="user:registered",
        resource_type="user",
        resource_id=str(new_user.id),
        metadata_json={"email": new_user.email, "role": target_role_name}
    )
    db.add(audit)
    await db.commit()

    # Re-query with roles loaded
    stmt = select(User).where(User.id == new_user.id).options(selectinload(User.roles))
    created = await db.scalar(stmt)
    return created


# --- Session helpers ---

def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    secure = settings.cookie_secure
    samesite = cast(Literal["lax", "strict", "none"], settings.COOKIE_SAMESITE.lower())
    response.set_cookie(
        settings.ACCESS_COOKIE_NAME, access_token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60, path="/", httponly=True, secure=secure, samesite=samesite,
    )
    # Scoped to the auth routes so it is never sent with ordinary API calls.
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME, refresh_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400, path=f"{settings.API_V1_PREFIX}/auth", httponly=True, secure=secure, samesite=samesite,
    )
    response.set_cookie(
        settings.SESSION_HINT_COOKIE_NAME, "1",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400, path="/", httponly=True, secure=secure, samesite=samesite,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(settings.ACCESS_COOKIE_NAME, path="/")
    response.delete_cookie(settings.REFRESH_COOKIE_NAME, path=f"{settings.API_V1_PREFIX}/auth")
    response.delete_cookie(settings.SESSION_HINT_COOKIE_NAME, path="/")


async def _issue_session(
    db: AsyncSession,
    user: User,
    request: Request,
    response: Response,
    family_id: Optional[uuid.UUID] = None,
) -> tuple[Token, RefreshToken]:
    now = datetime.now(timezone.utc)
    record = RefreshToken(
        id=uuid.uuid4(),
        user_id=user.id,
        family_id=family_id or uuid.uuid4(),
        expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        ip_address=client_ip(request)[:45],
        user_agent=(request.headers.get("user-agent") or "")[:255] or None,
    )
    db.add(record)
    await db.flush()

    access_token = create_access_token(subject=str(user.id), token_version=user.token_version or 0)
    refresh_token = create_refresh_token(
        subject=str(user.id), jti=str(record.id), family_id=str(record.family_id)
    )
    _set_auth_cookies(response, access_token, refresh_token)
    token = Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in_seconds=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    return token, record


def _refresh_token_from(request: Request, payload: Optional[RefreshRequest]) -> tuple[Optional[str], bool]:
    """Returns (token, came_from_cookie)."""
    if payload and payload.refresh_token:
        return payload.refresh_token, False
    return request.cookies.get(settings.REFRESH_COOKIE_NAME), True


async def _revoke_family(db: AsyncSession, family_id: uuid.UUID) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )


def _invalid_refresh() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token.")


@router.post("/login", response_model=Token)
async def login(payload: UserLogin, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    email = payload.email.lower().strip()
    ip = client_ip(request)
    # Per account+IP (slows password guessing) and per IP (slows credential stuffing).
    await enforce_rate_limit(
        f"login:{ip}:{email}", settings.LOGIN_RATE_LIMIT_PER_MINUTE, 60, detail="Too many login attempts."
    )
    await enforce_rate_limit(
        f"login-ip:{ip}", settings.LOGIN_RATE_LIMIT_PER_MINUTE * 6, 60, detail="Too many login attempts."
    )

    stmt = select(User).where(User.email == email).options(selectinload(User.roles))
    user = await db.scalar(stmt)

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been deactivated. Contact an administrator."
        )

    user.last_login_at = datetime.now(timezone.utc)
    token, _ = await _issue_session(db, user, request, response)
    await db.commit()
    return token


@router.post("/refresh", response_model=Token)
async def refresh_token(
    request: Request,
    response: Response,
    payload: Optional[RefreshRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Exchanges a refresh token (JSON body, or the httpOnly cookie for browsers) for a new
    access + refresh pair. The presented refresh token is single-use; replaying it revokes
    every token in its family.
    """
    raw, from_cookie = _refresh_token_from(request, payload)
    if not raw:
        raise _invalid_refresh()
    if from_cookie and not request.headers.get(CSRF_HEADER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing {CSRF_HEADER} header.")

    claims = decode_token(raw)
    if not claims or claims.get("type") != "refresh":
        raise _invalid_refresh()
    try:
        jti = uuid.UUID(claims.get("jti"))
        user_id = uuid.UUID(claims.get("sub"))
    except (ValueError, TypeError):
        raise _invalid_refresh()

    record = await db.scalar(select(RefreshToken).where(RefreshToken.id == jti, RefreshToken.user_id == user_id))
    if record is None:
        raise _invalid_refresh()

    now = datetime.now(timezone.utc)
    if record.used_at is not None or record.revoked_at is not None:
        # Reuse of a rotated/revoked token: assume theft and kill the whole session family.
        await _revoke_family(db, record.family_id)
        db.add(AuditLog(
            actor_user_id=user_id,
            action="auth:refresh_reuse_detected",
            resource_type="refresh_token",
            resource_id=str(record.id),
            ip_address=client_ip(request)[:45],
        ))
        await db.commit()
        raise _invalid_refresh()
    if record.expires_at <= now:
        raise _invalid_refresh()

    user = await db.scalar(select(User).where(User.id == user_id, User.is_active.is_(True)))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User account not found or inactive.")

    record.used_at = now
    token, new_record = await _issue_session(db, user, request, response, family_id=record.family_id)
    record.replaced_by_id = new_record.id
    await db.commit()
    return token


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    payload: Optional[RefreshRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """Ends this session (its refresh token family) and clears auth cookies. Idempotent."""
    raw, _ = _refresh_token_from(request, payload)
    claims = decode_token(raw) if raw else {}
    if claims.get("type") == "refresh":
        try:
            await _revoke_family(db, uuid.UUID(claims.get("fam")))
            await db.commit()
        except (ValueError, TypeError):
            pass
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_auth_cookies(response)
    return response


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Signs the user out everywhere: revokes all refresh tokens and invalidates access tokens."""
    current_user.token_version = (current_user.token_version or 0) + 1
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == current_user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    db.add(AuditLog(actor_user_id=current_user.id, action="auth:logout_all", resource_type="user", resource_id=str(current_user.id)))
    await db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_auth_cookies(response)
    return response


@router.get("/me", response_model=UserRead)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


# --- API Key Management ---

@router.post("/api-keys", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_new_api_key(
    payload: ApiKeyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    raw_key, prefix, key_hash = generate_api_key()

    new_key = ApiKey(
        user_id=current_user.id,
        name=payload.name,
        key_prefix=prefix,
        key_hash=key_hash,
        scopes=payload.scopes,
        rate_limit_per_minute=payload.rate_limit_per_minute,
    )
    db.add(new_key)
    await db.flush()

    audit = AuditLog(
        actor_user_id=current_user.id,
        action="api_key:created",
        resource_type="api_key",
        resource_id=str(new_key.id),
        metadata_json={"name": payload.name, "prefix": prefix}
    )
    db.add(audit)
    await db.commit()

    return ApiKeyCreatedResponse(
        id=new_key.id,
        name=new_key.name,
        key_prefix=new_key.key_prefix,
        scopes=new_key.scopes,
        rate_limit_per_minute=new_key.rate_limit_per_minute,
        created_at=new_key.created_at,
        raw_api_key=raw_key,
    )


@router.get("/api-keys", response_model=List[ApiKeyRead])
async def list_api_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(ApiKey)
        .where(ApiKey.user_id == current_user.id, ApiKey.revoked_at.is_(None))
        .order_by(ApiKey.created_at.desc())
    )
    results = await db.scalars(stmt)
    return list(results.all())


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == current_user.id)
    key_obj = await db.scalar(stmt)
    if not key_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found.")

    key_obj.revoked_at = datetime.now(timezone.utc)
    audit = AuditLog(
        actor_user_id=current_user.id,
        action="api_key:revoked",
        resource_type="api_key",
        resource_id=str(key_obj.id)
    )
    db.add(audit)
    await db.commit()
    return None
