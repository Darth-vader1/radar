import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, get_db, require_roles
from app.models.auth import AuditLog, User
from app.models.source import (
    DeadLetterTask,
    RunStatus,
    ScrapingTask,
    Source,
    SourceRun,
    TaskStatus,
)
from app.modules.scraping.pipeline import RETRY_SEEDS_KEY
from app.modules.scraping.runs import (
    QueueUnavailableError,
    RunAlreadyActiveError,
    create_and_dispatch_run,
)
from app.schemas.source import (
    ScrapingTaskRead,
    SourceRunCreate,
    SourceRunRead,
)

logger = logging.getLogger("radar.api.tasks")
router = APIRouter(prefix="/tasks", tags=["Discovery Tasks & Pipeline"])


class DeadLetterTaskRead(BaseModel):
    id: uuid.UUID
    scraping_task_id: uuid.UUID
    source_id: Optional[uuid.UUID]
    stage: str
    input_snapshot: Dict[str, Any]
    error_type: str
    error_message: str
    resolved_at: Optional[datetime]
    resolution_note: Optional[str]
    created_at: datetime


@router.post("/trigger", response_model=SourceRunRead, status_code=status.HTTP_202_ACCEPTED)
async def trigger_source_run(
    payload: SourceRunCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["super_admin", "admin", "researcher"])),
):
    source = await db.scalar(select(Source).where(Source.id == payload.source_id))
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found.")

    if not source.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Source '{source.name}' is currently disabled. Enable it before triggering a run."
        )
    if RETRY_SEEDS_KEY in (payload.search_params or {}):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"'{RETRY_SEEDS_KEY}' is reserved.")

    db.add(AuditLog(
        actor_user_id=current_user.id,
        action="task:triggered",
        resource_type="source",
        resource_id=str(source.id),
        metadata_json={"source": source.slug, "trigger": payload.trigger_type},
    ))
    return await _create_run_or_http_error(
        db, source, payload.trigger_type, payload.search_params, current_user.id
    )


async def _create_run_or_http_error(db, source, trigger_type, search_params, user_id):
    try:
        return await create_and_dispatch_run(
            db, source, trigger_type=trigger_type, search_params=search_params, triggered_by_user_id=user_id
        )
    except RunAlreadyActiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Source '{source.slug}' already has a queued or running run"
                   + (f" ({exc.active_run_id})." if exc.active_run_id else "."),
        )
    except QueueUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The task queue is unavailable, so the run was not started. Check that Redis and a worker are running.",
        )


@router.get("/runs", response_model=List[SourceRunRead])
async def list_runs(
    source_id: Optional[uuid.UUID] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(SourceRun).order_by(desc(SourceRun.created_at)).limit(limit)
    if source_id:
        stmt = stmt.where(SourceRun.source_id == source_id)
    if status_filter:
        stmt = stmt.where(SourceRun.status == status_filter.upper())

    results = await db.scalars(stmt)
    return list(results.all())


@router.get("/runs/{run_id}", response_model=SourceRunRead)
async def get_run_details(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(SourceRun)
        .where(SourceRun.id == run_id)
        .options(selectinload(SourceRun.tasks))
    )
    run = await db.scalar(stmt)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    return run


@router.get("/runs/{run_id}/tasks", response_model=List[ScrapingTaskRead])
async def get_run_tasks(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(ScrapingTask)
        .where(ScrapingTask.source_run_id == run_id)
        .order_by(ScrapingTask.created_at.asc())
    )
    tasks = await db.scalars(stmt)
    return list(tasks.all())


@router.post("/runs/{run_id}/cancel", response_model=SourceRunRead)
async def cancel_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["super_admin", "admin"])),
):
    run = await db.scalar(select(SourceRun).where(SourceRun.id == run_id))
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")

    # Conditional update: if the run finished between the read above and now, it stays finished.
    # A RUNNING pipeline notices the CANCELLED status before its next page and stops.
    result = await db.execute(
        update(SourceRun)
        .where(
            SourceRun.id == run_id,
            SourceRun.status.in_((RunStatus.QUEUED.value, RunStatus.RUNNING.value, RunStatus.PAUSED.value)),
        )
        .values(
            status=RunStatus.CANCELLED.value,
            finished_at=datetime.now(timezone.utc),
            error_summary=f"Cancelled by user {current_user.email}",
        )
    )
    if result.rowcount == 0:
        await db.refresh(run)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot cancel run in status: {run.status}")

    audit = AuditLog(
        actor_user_id=current_user.id,
        action="task:cancelled",
        resource_type="source_run",
        resource_id=str(run.id),
    )
    db.add(audit)
    await db.commit()
    await db.refresh(run)
    return run


# --- DEAD-LETTER QUEUE (DLQ) MANAGEMENT ---

@router.get("/dead-letter", response_model=List[DeadLetterTaskRead])
async def list_dead_letter_tasks(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["super_admin", "admin"])),
):
    stmt = (
        select(DeadLetterTask)
        .where(DeadLetterTask.resolved_at.is_(None))
        .order_by(desc(DeadLetterTask.created_at))
        .limit(limit)
    )
    results = await db.scalars(stmt)
    return list(results.all())


@router.post("/dead-letter/{dlq_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_dead_letter_task(
    dlq_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["super_admin", "admin"])),
):
    """
    Re-runs the failed work in a new SourceRun (trigger_type DLQ_RETRY): the failed page
    for FETCH/EXTRACT failures, or a fresh discovery for DISCOVER failures. The item is
    marked resolved only once the retry run has been queued.
    """
    dlq_item = await db.scalar(select(DeadLetterTask).where(DeadLetterTask.id == dlq_id))
    if not dlq_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dead-letter item not found.")
    if dlq_item.resolved_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Dead-letter item is already resolved.")

    source = await db.scalar(select(Source).where(Source.id == dlq_item.source_id)) if dlq_item.source_id else None
    if source is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The source for this item no longer exists.")
    if not source.is_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Source '{source.slug}' is disabled.")

    snapshot = dlq_item.input_snapshot or {}
    if dlq_item.stage == "DISCOVER":
        # Older rows stored the search params directly as the snapshot.
        search_params = snapshot.get("search_params", snapshot)
    else:
        seed = snapshot.get("seed") or {"url": snapshot.get("url"), "method": "GET"}
        if not seed.get("url"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dead-letter item has no URL to retry.")
        search_params = {**snapshot.get("search_params", {}), RETRY_SEEDS_KEY: [seed]}

    run = await _create_run_or_http_error(db, source, "DLQ_RETRY", search_params, current_user.id)

    dlq_item.resolved_at = datetime.now(timezone.utc)
    dlq_item.resolution_note = f"Retried in run {run.id} by {current_user.email}"
    db.add(AuditLog(
        actor_user_id=current_user.id,
        action="dead_letter:retried",
        resource_type="dead_letter_task",
        resource_id=str(dlq_item.id),
        metadata_json={"source_run_id": str(run.id)},
    ))
    await db.commit()

    return {"status": "RETRY_QUEUED", "dlq_id": str(dlq_id), "source_run_id": str(run.id)}
