from datetime import datetime, timezone
import logging
import re
from typing import List, Optional, Tuple
from urllib.parse import urlparse
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.database.locks import advisory_xact_lock

from app.models.job import Job, JobSkill
from app.modules.jobs.services.skill_extractor import (
    classify_category,
    extract_experience_level,
    extract_remote_status,
    extract_skills_from_text,
)

logger = logging.getLogger("radar.jobs.service")


def normalize_title(title: str) -> str:
    """Cleans title by removing brackets, trailing locations, separators, and punctuation."""
    if not title:
        return ""
    # Strip after common location/type separators like " - ", " | ", " – "
    t = re.split(r"\s+[-|–]\s+", title)[0]
    # Remove parenthetical tags like (Remote), [Lagos], (Full-time)
    t = re.sub(r"[\(\[\{].*?[\)\]\}]", "", t)
    t = re.sub(r"[^\w\s]", "", t.lower())
    return " ".join(t.split())


def normalize_company(company: str) -> str:
    """Normalizes company name (e.g. 'Paystack Payments Limited' -> 'paystack')."""
    if not company:
        return ""
    c = company.lower()
    for suffix in (
        "payments", "payment", "ltd", "limited", "inc", "incorporated",
        "corp", "corporation", "technologies", "technology", "tech",
        "plc", "llc", "group", "holdings", "solutions", "services",
    ):
        c = re.sub(rf"\b{suffix}\b", "", c)
    c = re.sub(r"[^\w\s]", "", c)
    return " ".join(c.split())


class JobIngestionService:
    """
    Cross-platform job deduplication, skill extraction, and storage pipeline.
    Ensures that the same vacancy posted on Greenhouse, Remotive, and job boards
    is unified rather than duplicated.
    """

    async def ingest_job(
        self,
        db: AsyncSession,
        raw_data: dict,
        source_id: uuid.UUID,
        source_platform: str,
        original_source_url: str,
    ) -> Tuple[Job, str]:
        title = raw_data.get("title", "").strip()
        company = raw_data.get("company_name", "").strip()
        description = raw_data.get("description", "").strip()
        apply_url = raw_data.get("application_url", original_source_url).strip()

        norm_title = normalize_title(title)
        norm_company = normalize_company(company)

        # Extract canonical domain of application URL
        apply_domain = None
        try:
            apply_domain = urlparse(apply_url).netloc.lower()
        except Exception:
            pass

        # Serialize concurrent ingestion of the same vacancy (see advisory_xact_lock).
        await advisory_xact_lock(db, f"job:{norm_company}:{norm_title}")

        # 1. Deterministic Cross-Platform Duplicate Detection
        stmt = (
            select(Job)
            .where(
                Job.normalized_company == norm_company,
                Job.normalized_title == norm_title,
            )
            .options(selectinload(Job.skills))
        )
        existing = await db.scalar(stmt)

        if existing:
            # Vacancy already discovered on another platform!
            existing.other_sources_count += 1
            existing.last_verified_at = datetime.now(timezone.utc)

            # Enrich missing fields without destroying original
            if not existing.description and description:
                existing.description = description
            if not existing.salary_max and raw_data.get("salary_max"):
                existing.salary_min = raw_data.get("salary_min")
                existing.salary_max = raw_data.get("salary_max")
                existing.salary_currency = raw_data.get("salary_currency")

            await db.commit()
            logger.info("Deduplicated cross-platform job vacancy: '%s' at '%s'", title, company)
            return existing, "DEDUPLICATED"

        # 2. Category, Skills & Metadata Extraction
        category = raw_data.get("category") or classify_category(title, description)
        experience_level = raw_data.get("experience_level") or extract_experience_level(title, description)
        remote_status = raw_data.get("remote_status") or extract_remote_status(raw_data.get("location_text", ""), description)
        employment_type = raw_data.get("employment_type", "FULL_TIME")

        # 3. Create New Job Record
        new_job = Job(
            title=title,
            normalized_title=norm_title,
            company_name=company,
            normalized_company=norm_company,
            company_website=raw_data.get("company_website"),
            description=description,
            requirements_text=raw_data.get("requirements_text"),
            education_requirements=raw_data.get("education_requirements"),
            category=category,
            employment_type=employment_type,
            remote_status=remote_status,
            experience_level=experience_level,
            salary_min=raw_data.get("salary_min"),
            salary_max=raw_data.get("salary_max"),
            salary_currency=raw_data.get("salary_currency"),
            location_text=raw_data.get("location_text"),
            city=raw_data.get("city"),
            country=raw_data.get("country", "Nigeria"),
            application_deadline=raw_data.get("application_deadline"),
            application_url=apply_url,
            canonical_apply_domain=apply_domain,
            primary_source_id=source_id,
            source_platform=source_platform,
            original_source_url=original_source_url,
            status="ACTIVE",
            published_at=raw_data.get("published_at"),
            discovered_at=datetime.now(timezone.utc),
            last_verified_at=datetime.now(timezone.utc),
        )
        db.add(new_job)
        await db.flush()

        # 4. Extract and persist skills
        skills_found = extract_skills_from_text(f"{title} {description}")
        for s in skills_found:
            job_skill = JobSkill(
                job_id=new_job.id,
                skill_name=s,
                normalized_skill=s.lower(),
                is_required=True,
                extraction_origin="INFERRED",
            )
            db.add(job_skill)

        await db.commit()
        await db.refresh(new_job)
        return new_job, "CREATED"
