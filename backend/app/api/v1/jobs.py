import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, get_db
from app.models.auth import User
from app.models.job import Job, JobSkill
from app.schemas.job import (
    JobDrawerDetail,
    JobRead,
    SkillCountItem,
)

router = APIRouter(prefix="/jobs", tags=["JobRadar"])


@router.get("", response_model=List[JobRead])
async def list_jobs(
    category: Optional[str] = Query(None),
    employment_type: Optional[str] = Query(None),
    remote_status: Optional[str] = Query(None),
    experience_level: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    skill: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Search and filter tech vacancies discovered by JobRadar.
    Supports filtering by role category, remote status, employment type, seniority, and required skills.
    """
    stmt = (
        select(Job)
        .options(selectinload(Job.skills))
        .order_by(desc(Job.published_at), desc(Job.discovered_at))
    )

    if category:
        stmt = stmt.where(Job.category == category.upper())
    if employment_type:
        stmt = stmt.where(Job.employment_type == employment_type.upper())
    if remote_status:
        stmt = stmt.where(Job.remote_status == remote_status.upper())
    if experience_level:
        stmt = stmt.where(Job.experience_level == experience_level.upper())
    if city:
        stmt = stmt.where(func.lower(Job.city) == city.lower())
    if country:
        stmt = stmt.where(func.lower(Job.country) == country.lower())
    if skill:
        # Join with skills
        stmt = stmt.join(Job.skills).where(func.lower(JobSkill.skill_name) == skill.lower())
    if search:
        search_term = f"%{search.lower()}%"
        stmt = stmt.where(
            func.lower(Job.title).like(search_term)
            | func.lower(Job.company_name).like(search_term)
            | func.lower(Job.description).like(search_term)
        )

    stmt = stmt.limit(limit).offset(offset)
    results = await db.scalars(stmt)
    return list(results.all())


@router.get("/skills/top", response_model=List[SkillCountItem])
async def get_top_skills(
    limit: int = Query(20, ge=5, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns top in-demand skills ranked by frequency across active vacancies."""
    stmt = (
        select(JobSkill.skill_name, func.count(JobSkill.id).label("count"))
        .group_by(JobSkill.skill_name)
        .order_by(desc("count"))
        .limit(limit)
    )
    rows = await db.execute(stmt)
    return [SkillCountItem(skill_name=r[0], count=r[1]) for r in rows.all()]


@router.get("/companies", response_model=List[str])
async def list_hiring_companies(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lists distinct hiring companies currently in the database."""
    stmt = select(Job.company_name).distinct().order_by(Job.company_name)
    companies = await db.scalars(stmt)
    return list(companies.all())


@router.get("/{job_id}", response_model=JobDrawerDetail)
async def get_job_detail(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns full job detail with requirements, HTML description, and skill tags."""
    stmt = (
        select(Job)
        .where(Job.id == job_id)
        .options(selectinload(Job.skills))
    )
    job = await db.scalar(stmt)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job vacancy not found.")
    return job
