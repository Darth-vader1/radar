"""
Administration: user accounts and integration (credential) status.

Role rules:
- admins and super admins can list users and change researcher / standard user accounts;
- only a super admin can grant or remove the admin and super admin roles, or change an admin;
- nobody can change their own role or deactivate themselves (use another admin account);
- the last active super admin can never be demoted or deactivated.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, get_db, require_roles
from app.core.config import get_credential, settings
from app.models.auth import AuditLog, RefreshToken, Role, User
from app.models.source import Source
from app.schemas.auth import AdminUserRead, AdminUserUpdate

router = APIRouter(prefix="/admin", tags=["Administration"])

PRIVILEGED = {"super_admin", "admin"}
require_admin = require_roles(["admin"])  # super_admin always passes


def _role_names(user: User) -> set[str]:
    return {r.name.lower() for r in user.roles}


async def _load_user(db: AsyncSession, user_id: uuid.UUID) -> Optional[User]:
    return await db.scalar(select(User).where(User.id == user_id).options(selectinload(User.roles)))


async def _active_super_admins(db: AsyncSession) -> int:
    return await db.scalar(
        select(func.count(func.distinct(User.id)))
        .select_from(User)
        .join(User.roles)
        .where(Role.name == "super_admin", User.is_active.is_(True))
    ) or 0


@router.get("/users", response_model=List[AdminUserRead])
async def list_users(
    search: Optional[str] = Query(None, max_length=200),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    stmt = select(User).options(selectinload(User.roles)).order_by(User.created_at.desc())
    if search:
        term = f"%{search.lower()}%"
        stmt = stmt.where(or_(func.lower(User.email).like(term), func.lower(func.coalesce(User.full_name, "")).like(term)))
    return list((await db.scalars(stmt.limit(limit).offset(offset))).all())


@router.patch("/users/{user_id}", response_model=AdminUserRead)
async def update_user(
    user_id: uuid.UUID,
    payload: AdminUserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    target = await _load_user(db, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if target.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="You can't change your own role or status. Ask another administrator.")

    actor_is_super = "super_admin" in _role_names(current_user)
    target_roles = _role_names(target)
    if not actor_is_super and (target_roles & PRIVILEGED or (payload.role or "") in PRIVILEGED):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only a super admin can manage administrator accounts.")

    losing_super = "super_admin" in target_roles and target.is_active and (
        (payload.role is not None and payload.role != "super_admin") or payload.is_active is False
    )
    if losing_super and await _active_super_admins(db) <= 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="This is the last active super admin; promote someone else first.")

    changes: dict[str, Any] = {}
    if payload.role is not None and target_roles != {payload.role}:
        role = await db.scalar(select(Role).where(Role.name == payload.role))
        if role is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"Role '{payload.role}' is not set up. Run `python -m app.cli seed`.")
        target.roles = [role]
        changes["role"] = {"from": sorted(target_roles), "to": payload.role}

    if payload.is_active is not None and payload.is_active != target.is_active:
        target.is_active = payload.is_active
        changes["is_active"] = payload.is_active
        if not payload.is_active:
            # Sign the account out everywhere straight away.
            target.token_version = (target.token_version or 0) + 1
            await db.execute(
                update(RefreshToken)
                .where(RefreshToken.user_id == target.id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=datetime.now(timezone.utc))
            )

    if changes:
        db.add(AuditLog(actor_user_id=current_user.id, action="user:updated", resource_type="user",
                        resource_id=str(target.id), metadata_json={"email": target.email, **changes}))
        await db.commit()
    return await _load_user(db, user_id)


# --- Integrations -------------------------------------------------------------

class CredentialStatus(BaseModel):
    name: str
    configured: bool


class IntegrationStatus(BaseModel):
    key: str
    name: str
    kind: str  # SOURCE | AI | MONITORING
    configured: bool
    credentials: List[CredentialStatus]
    note: Optional[str] = None


@router.get("/integrations", response_model=List[IntegrationStatus])
async def list_integrations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Which external keys are set. Never returns a key's value, only whether it exists."""
    out: List[IntegrationStatus] = []
    sources = (await db.scalars(select(Source).order_by(Source.module_type, Source.name))).all()
    for src in sources:
        if not src.required_env_vars:
            continue
        creds = [CredentialStatus(name=v, configured=bool(get_credential(v))) for v in src.required_env_vars]
        out.append(IntegrationStatus(
            key=src.slug, name=src.name, kind="SOURCE", configured=all(c.configured for c in creds), credentials=creds,
            note=None if all(c.configured for c in creds) else "Add the missing keys to .env, then restart the API and worker.",
        ))

    ai_creds = [CredentialStatus(name=n, configured=bool(get_credential(n))) for n in ("GEMINI_API_KEY", "OPENAI_API_KEY")]
    out.append(IntegrationStatus(
        key="ai", name="AI classification", kind="AI",
        configured=settings.AI_ENABLED and any(c.configured for c in ai_creds), credentials=ai_creds,
        note="Off: RADAR runs entirely on rules." if not settings.AI_ENABLED else None,
    ))
    sentry = CredentialStatus(name="SENTRY_DSN", configured=bool(settings.SENTRY_DSN))
    out.append(IntegrationStatus(
        key="sentry", name="Error monitoring (Sentry)", kind="MONITORING", configured=sentry.configured,
        credentials=[sentry], note=None if sentry.configured else "Optional. Errors are still written to the logs.",
    ))
    return out
