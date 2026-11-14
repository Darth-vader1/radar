import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_roles
from app.core.config import missing_credentials
from app.models.auth import AuditLog, User
from app.models.source import ConfigStatus, Source
from app.schemas.source import (
    SourceConfigCheckResult,
    SourceCreate,
    SourceRead,
    SourceUpdate,
)

router = APIRouter(prefix="/sources", tags=["Source Registry"])


@router.get("", response_model=List[SourceRead])
async def list_sources(
    module_type: Optional[str] = Query(None, description="Filter by BUSINESS, JOB, or EVENT"),
    is_enabled: Optional[bool] = Query(None, description="Filter by enabled status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Source).order_by(Source.module_type, Source.name)
    if module_type:
        stmt = stmt.where(Source.module_type == module_type.upper())
    if is_enabled is not None:
        stmt = stmt.where(Source.is_enabled == is_enabled)

    sources = list((await db.scalars(stmt)).all())
    # Keep the credentials badge current: keys can be added to .env at any time.
    changed = False
    for source in sources:
        status_now = (
            ConfigStatus.AWAITING_CONFIGURATION.value
            if missing_credentials(source.required_env_vars)
            else ConfigStatus.READY.value
        )
        if source.required_env_vars and source.config_status != status_now:
            source.config_status = status_now
            changed = True
    if changed:
        await db.commit()
    return sources


@router.post("", response_model=SourceRead, status_code=status.HTTP_201_CREATED)
async def create_source(
    payload: SourceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["super_admin", "admin"])),
):
    # Check slug uniqueness
    existing = await db.scalar(select(Source).where(Source.slug == payload.slug.lower()))
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Source with slug '{payload.slug}' already exists.")

    # Determine configuration status based on required env vars
    missing_vars = missing_credentials(payload.required_env_vars)
    status_val = ConfigStatus.AWAITING_CONFIGURATION.value if missing_vars else ConfigStatus.READY.value

    new_source = Source(
        slug=payload.slug.lower(),
        name=payload.name,
        module_type=payload.module_type.upper(),
        source_category=payload.source_category,
        base_url=payload.base_url,
        collection_method=payload.collection_method,
        adapter_key=payload.adapter_key,
        requires_credentials=payload.requires_credentials,
        required_env_vars=payload.required_env_vars,
        config_status=status_val,
        adapter_config=payload.adapter_config,
        rate_limit_rpm=payload.rate_limit_rpm,
        max_concurrency=payload.max_concurrency,
        crawl_budget_pages=payload.crawl_budget_pages,
        schedule_cron=payload.schedule_cron,
        is_enabled=payload.is_enabled,
        respect_robots_txt=payload.respect_robots_txt,
    )
    db.add(new_source)
    await db.flush()

    audit = AuditLog(
        actor_user_id=current_user.id,
        action="source:created",
        resource_type="source",
        resource_id=str(new_source.id),
        metadata_json={"slug": new_source.slug, "module": new_source.module_type}
    )
    db.add(audit)
    await db.commit()
    return new_source


@router.get("/{source_id}", response_model=SourceRead)
async def get_source(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    source = await db.scalar(select(Source).where(Source.id == source_id))
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found.")
    return source


@router.patch("/{source_id}", response_model=SourceRead)
async def update_source(
    source_id: uuid.UUID,
    payload: SourceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["super_admin", "admin"])),
):
    source = await db.scalar(select(Source).where(Source.id == source_id))
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found.")

    update_dict = payload.model_dump(exclude_unset=True)
    for field, val in update_dict.items():
        setattr(source, field, val)

    audit = AuditLog(
        actor_user_id=current_user.id,
        action="source:updated",
        resource_type="source",
        resource_id=str(source.id),
        metadata_json=update_dict
    )
    db.add(audit)
    await db.commit()
    await db.refresh(source)
    return source


@router.post("/{source_id}/toggle", response_model=SourceRead)
async def toggle_source(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["super_admin", "admin"])),
):
    source = await db.scalar(select(Source).where(Source.id == source_id))
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found.")

    source.is_enabled = not source.is_enabled
    action_str = "source:enabled" if source.is_enabled else "source:disabled"

    audit = AuditLog(
        actor_user_id=current_user.id,
        action=action_str,
        resource_type="source",
        resource_id=str(source.id),
    )
    db.add(audit)
    await db.commit()
    await db.refresh(source)
    return source


@router.post("/{source_id}/check-config", response_model=SourceConfigCheckResult)
async def check_source_config(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    source = await db.scalar(select(Source).where(Source.id == source_id))
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found.")

    missing = missing_credentials(source.required_env_vars)
    is_ready = len(missing) == 0

    new_status = ConfigStatus.READY.value if is_ready else ConfigStatus.AWAITING_CONFIGURATION.value
    if source.config_status != new_status:
        source.config_status = new_status
        await db.commit()

    message = (
        "All required credentials and parameters are configured."
        if is_ready
        else f"Awaiting configuration for required environment variables: {', '.join(missing)}"
    )

    return SourceConfigCheckResult(
        source_id=source.id,
        slug=source.slug,
        is_configured=is_ready,
        status=new_status,
        missing_env_vars=missing,
        message=message,
    )
