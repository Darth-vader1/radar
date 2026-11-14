"""
Saved records: each user's personal bookmarks of businesses, jobs and events, with notes
and tags. Every query is scoped to the signed-in user; nobody can see or change another
user's saved records (other users' ids simply return 404).
"""
import csv
import io
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.auth import User
from app.models.business import Business
from app.models.event import Event
from app.models.job import Job
from app.models.saved import SavedRecord
from app.schemas.saved import (
    EntitySummary,
    EntityType,
    SavedRecordCreate,
    SavedRecordRead,
    SavedRecordUpdate,
)

router = APIRouter(prefix="/saved", tags=["Saved Records"])

MODELS: dict[str, Any] = {"BUSINESS": Business, "JOB": Job, "EVENT": Event}
MAX_SAVED_PER_USER = 5000


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _summary(entity_type: str, e: Any) -> EntitySummary:
    if entity_type == "BUSINESS":
        place = ", ".join(p for p in (e.city, e.country) if p)
        return EntitySummary(
            title=e.name,
            subtitle=" · ".join(p for p in (e.category, place) if p) or None,
            url=e.website_url or e.original_source_url,
            source=e.original_source_url,
            facts={"lead_score": e.lead_score, "phone": e.phone_number, "email": e.public_email,
                   "website_status": e.website_status},
        )
    if entity_type == "JOB":
        return EntitySummary(
            title=e.title,
            subtitle=" · ".join(p for p in (e.company_name, e.location_text) if p) or None,
            url=e.application_url,
            source=e.source_platform,
            facts={"remote_status": e.remote_status, "category": e.category,
                   "experience_level": e.experience_level, "published_at": _iso(e.published_at)},
        )
    return EntitySummary(
        title=e.name,
        subtitle=" · ".join(p for p in (e.organizer, e.location_text) if p) or None,
        url=e.registration_url,
        source=e.source_platform,
        facts={"status": e.status, "registration_deadline": _iso(e.registration_deadline),
               "prize_summary": e.prize_summary, "delivery_mode": e.delivery_mode},
    )


async def _load_entities(db: AsyncSession, records: Iterable[SavedRecord]) -> dict[tuple[str, uuid.UUID], Any]:
    """Fetches the saved entities with one query per entity type."""
    wanted: dict[str, set[uuid.UUID]] = {}
    for r in records:
        wanted.setdefault(r.entity_type, set()).add(r.entity_id)
    found: dict[tuple[str, uuid.UUID], Any] = {}
    for entity_type, ids in wanted.items():
        model = MODELS[entity_type]
        for e in (await db.scalars(select(model).where(model.id.in_(ids)))).all():
            found[(entity_type, e.id)] = e
    return found


def _read(record: SavedRecord, entities: dict[tuple[str, uuid.UUID], Any]) -> SavedRecordRead:
    out = SavedRecordRead.model_validate(record)
    entity = entities.get((record.entity_type, record.entity_id))
    out.entity = _summary(record.entity_type, entity) if entity is not None else None
    return out


async def _own_record(db: AsyncSession, user: User, record_id: uuid.UUID) -> SavedRecord:
    record = await db.scalar(
        select(SavedRecord).where(SavedRecord.id == record_id, SavedRecord.user_id == user.id)
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved record not found.")
    return record


def _filtered(user: User, entity_type: Optional[str], tag: Optional[str], q: Optional[str]):
    stmt = select(SavedRecord).where(SavedRecord.user_id == user.id)
    if entity_type:
        stmt = stmt.where(SavedRecord.entity_type == entity_type)
    if tag:
        stmt = stmt.where(SavedRecord.tags.contains([tag.strip().lower()]))
    if q:
        term = f"%{q.strip().lower()}%"
        title_matches = or_(
            SavedRecord.id.in_(select(SavedRecord.id).join(Business, Business.id == SavedRecord.entity_id)
                               .where(SavedRecord.entity_type == "BUSINESS", func.lower(Business.name).like(term))),
            SavedRecord.id.in_(select(SavedRecord.id).join(Job, Job.id == SavedRecord.entity_id)
                               .where(SavedRecord.entity_type == "JOB",
                                      or_(func.lower(Job.title).like(term), func.lower(Job.company_name).like(term)))),
            SavedRecord.id.in_(select(SavedRecord.id).join(Event, Event.id == SavedRecord.entity_id)
                               .where(SavedRecord.entity_type == "EVENT", func.lower(Event.name).like(term))),
        )
        stmt = stmt.where(or_(func.lower(func.coalesce(SavedRecord.note, "")).like(term), title_matches))
    return stmt


@router.get("", response_model=List[SavedRecordRead])
async def list_saved(
    entity_type: Optional[EntityType] = Query(None),
    tag: Optional[str] = Query(None, max_length=32),
    q: Optional[str] = Query(None, max_length=200, description="Search titles, companies and notes"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = _filtered(current_user, entity_type, tag, q).order_by(SavedRecord.created_at.desc()).limit(limit).offset(offset)
    records = (await db.scalars(stmt)).all()
    entities = await _load_entities(db, records)
    return [_read(r, entities) for r in records]


@router.get("/tags", response_model=List[dict])
async def list_tags(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """The user's tags with usage counts, most used first."""
    tag = func.unnest(SavedRecord.tags).label("tag")
    sub = select(tag).where(SavedRecord.user_id == current_user.id).subquery()
    rows = await db.execute(select(sub.c.tag, func.count()).group_by(sub.c.tag).order_by(func.count().desc(), sub.c.tag))
    return [{"tag": t, "count": c} for t, c in rows.all()]


@router.get("/by-entity/{entity_type}/{entity_id}", response_model=SavedRecordRead)
async def get_saved_for_entity(
    entity_type: EntityType,
    entity_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Whether the current user saved this entity (404 if not). Used by the save buttons."""
    record = await db.scalar(select(SavedRecord).where(
        SavedRecord.user_id == current_user.id,
        SavedRecord.entity_type == entity_type,
        SavedRecord.entity_id == entity_id,
    ))
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not saved.")
    return _read(record, await _load_entities(db, [record]))


@router.post("", response_model=SavedRecordRead, status_code=status.HTTP_201_CREATED)
async def save_record(
    payload: SavedRecordCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Saves an entity. Saving something already saved returns the existing record (200)."""
    model = MODELS[payload.entity_type]
    if await db.scalar(select(model.id).where(model.id == payload.entity_id)) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{payload.entity_type.title()} not found.")

    existing = await db.scalar(select(SavedRecord).where(
        SavedRecord.user_id == current_user.id,
        SavedRecord.entity_type == payload.entity_type,
        SavedRecord.entity_id == payload.entity_id,
    ))
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return _read(existing, await _load_entities(db, [existing]))

    count = await db.scalar(select(func.count()).select_from(SavedRecord).where(SavedRecord.user_id == current_user.id))
    if (count or 0) >= MAX_SAVED_PER_USER:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"You can save at most {MAX_SAVED_PER_USER} records. Remove some first.")

    record = SavedRecord(
        id=uuid.uuid4(), user_id=current_user.id, entity_type=payload.entity_type,
        entity_id=payload.entity_id, note=payload.note, tags=payload.tags or [],
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return _read(record, await _load_entities(db, [record]))


@router.patch("/{record_id}", response_model=SavedRecordRead)
async def update_saved(
    record_id: uuid.UUID,
    payload: SavedRecordUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = await _own_record(db, current_user, record_id)
    changes = payload.model_dump(exclude_unset=True)
    if "note" in changes:
        record.note = payload.note
    if "tags" in changes:
        record.tags = payload.tags or []
    record.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(record)
    return _read(record, await _load_entities(db, [record]))


@router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = await _own_record(db, current_user, record_id)
    await db.delete(record)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _csv_safe(value: Any) -> str:
    """Neutralises spreadsheet formula injection (cells starting with = + - @ or tab/CR)."""
    text = "" if value is None else str(value)
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@router.get("/export.csv")
async def export_saved_csv(
    entity_type: Optional[EntityType] = Query(None),
    tag: Optional[str] = Query(None, max_length=32),
    q: Optional[str] = Query(None, max_length=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """CSV of the user's saved records (same filters as the list)."""
    stmt = _filtered(current_user, entity_type, tag, q).order_by(SavedRecord.entity_type, SavedRecord.created_at.desc())
    records = (await db.scalars(stmt.limit(MAX_SAVED_PER_USER))).all()
    entities = await _load_entities(db, records)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["type", "title", "details", "url", "source", "tags", "note", "saved_at", "key_facts"])
    for r in records:
        item = _read(r, entities)
        e = item.entity
        facts = "; ".join(f"{k}={v}" for k, v in (e.facts.items() if e else []) if v not in (None, ""))
        writer.writerow([_csv_safe(v) for v in (
            r.entity_type, e.title if e else "(no longer available)", e.subtitle if e else "",
            e.url if e else "", e.source if e else "", ", ".join(r.tags), r.note or "",
            r.created_at.isoformat(), facts,
        )])

    filename = f"radar-saved-{datetime.now(timezone.utc):%Y%m%d}.csv"
    return Response(
        content="﻿" + buf.getvalue(),  # BOM so Excel opens UTF-8 correctly
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
