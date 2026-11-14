"""Job deduplication against PostgreSQL: distinct openings stay separate, true cross-posts merge."""
import uuid

import pytest
from sqlalchemy import func, select

from app.models.job import Job
from app.modules.jobs.services.job_service import JobIngestionService, normalize_location

pytestmark = pytest.mark.integration


def job(title="Senior Solutions Architect", location="Austin, TX", url=None, company="Cloudflare"):
    return {
        "title": title,
        "company_name": company,
        "description": "Design systems.",
        "location_text": location,
        "application_url": url or f"https://boards.greenhouse.io/cloudflare/jobs/{uuid.uuid4().int % 10**8}",
    }


async def make_source(db, slug):
    from app.models.source import Source

    async with db() as s:
        src = Source(slug=slug, name=slug, module_type="JOB", source_category="test", base_url="https://example.com",
                     collection_method="OFFICIAL_API", adapter_key="greenhouse_boards", adapter_config={},
                     required_env_vars=[])
        s.add(src)
        await s.commit()
        return src.id


async def ingest(db, data, platform="greenhouse", source_id=None):
    async with db() as s:
        _, outcome = await JobIngestionService().ingest_job(
            db=s, raw_data=data, source_id=source_id, source_platform=platform,
            original_source_url=data["application_url"],
        )
        return outcome


async def count(db):
    async with db() as s:
        return await s.scalar(select(func.count()).select_from(Job))


def test_location_normalization():
    assert normalize_location("Austin, TX | Remote") == "austin tx remote"
    assert normalize_location("  LONDON,  UK ") == "london uk"
    assert normalize_location(None) == ""


async def test_same_title_in_different_cities_are_separate_jobs(db):
    assert await ingest(db, job(location="Austin, TX")) == "CREATED"
    assert await ingest(db, job(location="London, UK")) == "CREATED"
    assert await ingest(db, job(location="Lisbon, Portugal")) == "CREATED"
    assert await count(db) == 3


async def test_same_vacancy_on_another_board_is_merged(db):
    greenhouse, remotive = await make_source(db, "gh"), await make_source(db, "rm")
    assert await ingest(db, job(location="London, UK"), source_id=greenhouse) == "CREATED"
    # Same company/title/location (formatting differs), different source and URL.
    assert await ingest(db, job(location="london uk", url="https://remotive.com/jobs/123"),
                        platform="remotive", source_id=remotive) == "DEDUPLICATED"
    assert await count(db) == 1


async def test_repeated_title_and_location_within_one_source_are_separate_openings(db):
    greenhouse = await make_source(db, "gh")
    for _ in range(3):  # e.g. three distinct "Business Development Representative" roles, all "Hybrid"
        assert await ingest(db, job(title="Business Development Representative", location="Hybrid"),
                            source_id=greenhouse) == "CREATED"
    assert await count(db) == 3


async def test_same_application_url_is_the_same_job(db):
    url = "https://boards.greenhouse.io/cloudflare/jobs/42"
    assert await ingest(db, job(url=url, location="Austin, TX")) == "CREATED"
    assert await ingest(db, job(url=url, location="Austin (Hybrid)", title="Sr. Solutions Architect")) == "DEDUPLICATED"
    assert await count(db) == 1
