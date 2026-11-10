import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, get_db, require_roles
from app.models.auth import AuditLog, User
from app.models.business import Business, LeadScoringRule
from app.modules.businesses.services.lead_scorer import LeadScoringEngine
from app.schemas.business import (
    BusinessDrawerDetail,
    BusinessRead,
    LeadRuleUpdate,
    LeadScoringRuleRead,
)

router = APIRouter(prefix="/businesses", tags=["BusinessRadar"])


@router.get("", response_model=List[BusinessRead])
async def list_businesses(
    country: Optional[str] = Query("Nigeria"),
    state: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    website_status: Optional[str] = Query(None),
    min_lead_score: Optional[int] = Query(None, ge=0, le=100),
    has_email: Optional[bool] = Query(None),
    has_phone: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Search and filter businesses discovered by BusinessRadar.
    Supports multi-facet filtering by geographic region, category, website status,
    contact availability, and lead score threshold.
    """
    stmt = select(Business).order_by(desc(Business.lead_score), desc(Business.discovered_at))

    if country:
        stmt = stmt.where(func.lower(Business.country) == country.lower())
    if state:
        stmt = stmt.where(func.lower(Business.state) == state.lower())
    if city:
        stmt = stmt.where(func.lower(Business.city) == city.lower())
    if category:
        stmt = stmt.where(func.lower(Business.category) == category.lower())
    if website_status:
        stmt = stmt.where(Business.website_status == website_status.upper())
    if min_lead_score is not None:
        stmt = stmt.where(Business.lead_score >= min_lead_score)
    if has_email is True:
        stmt = stmt.where(Business.public_email.isnot(None))
    elif has_email is False:
        stmt = stmt.where(Business.public_email.is_(None))
    if has_phone is True:
        stmt = stmt.where(Business.phone_number.isnot(None))
    elif has_phone is False:
        stmt = stmt.where(Business.phone_number.is_(None))
    if search:
        search_term = f"%{search.lower()}%"
        stmt = stmt.where(
            func.lower(Business.name).like(search_term)
            | func.lower(Business.physical_address).like(search_term)
            | func.lower(Business.category).like(search_term)
        )

    stmt = stmt.limit(limit).offset(offset)
    results = await db.scalars(stmt)
    return list(results.all())


@router.get("/categories", response_model=List[str])
async def list_categories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lists distinct business categories present in the database."""
    stmt = (
        select(Business.category)
        .where(Business.category.isnot(None))
        .distinct()
        .order_by(Business.category)
    )
    categories = await db.scalars(stmt)
    return [c for c in categories.all() if c]


@router.get("/scoring-rules", response_model=List[LeadScoringRuleRead])
async def list_scoring_rules(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lists configurable lead scoring rules and points."""
    stmt = select(LeadScoringRule).order_by(desc(LeadScoringRule.points))
    rules = await db.scalars(stmt)
    return list(rules.all())


@router.patch("/scoring-rules/{rule_key}", response_model=LeadScoringRuleRead)
async def update_scoring_rule(
    rule_key: str,
    payload: LeadRuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["super_admin", "admin"])),
):
    """Allows administrators to customize lead scoring weights and toggles."""
    rule = await db.scalar(select(LeadScoringRule).where(LeadScoringRule.rule_key == rule_key))
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scoring rule not found.")

    if payload.points is not None:
        rule.points = payload.points
    if payload.is_enabled is not None:
        rule.is_enabled = payload.is_enabled
    if payload.label is not None:
        rule.label = payload.label

    audit = AuditLog(
        actor_user_id=current_user.id,
        action="scoring_rule:updated",
        resource_type="lead_scoring_rule",
        resource_id=rule.rule_key,
        metadata_json=payload.model_dump(exclude_unset=True),
    )
    db.add(audit)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.get("/{business_id}", response_model=BusinessDrawerDetail)
async def get_business_detail(
    business_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns full business details, contacts, social profiles, and score breakdown."""
    stmt = (
        select(Business)
        .where(Business.id == business_id)
        .options(
            selectinload(Business.contacts),
            selectinload(Business.social_profiles),
        )
    )
    business = await db.scalar(stmt)
    if not business:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found.")
    return business


@router.post("/{business_id}/rescore", response_model=BusinessRead)
async def rescore_business(
    business_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["super_admin", "admin", "researcher"])),
):
    """Recalculates the lead score for a business based on current scoring weights."""
    stmt = (
        select(Business)
        .where(Business.id == business_id)
        .options(
            selectinload(Business.contacts),
            selectinload(Business.social_profiles),
        )
    )
    business = await db.scalar(stmt)
    if not business:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found.")

    scorer = LeadScoringEngine()
    result = await scorer.calculate_score(business, db=db)
    business.lead_score = result.score
    business.lead_score_explanation = result.breakdown

    await db.commit()
    await db.refresh(business)
    return business
