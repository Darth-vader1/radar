"""Job descriptions stored as plain text, skills refreshed with them, and paginated list totals."""
import pytest
from sqlalchemy import select
from test_auth_api import register_and_login
from test_job_dedup import make_source

from app.core.config import settings
from app.core.text import html_to_text, looks_like_html
from app.models.business import Business
from app.models.job import Job, JobSkill
from app.modules.jobs.services.job_service import JobIngestionService, clean_stored_job_text

pytestmark = pytest.mark.integration
API = settings.API_V1_PREFIX
GREENHOUSE_CONTENT = (
    "&lt;div class=&quot;content-intro&quot;&gt;&lt;h3&gt;About Us&lt;/h3&gt;&lt;p&gt;We build Python &amp;amp; Go "
    "services.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Kubernetes&lt;/li&gt;&lt;li&gt;PostgreSQL&lt;/li&gt;&lt;/ul&gt;"
    "&lt;script&gt;alert(1)&lt;/script&gt;&lt;/div&gt;"
)


def test_html_to_text():
    text = html_to_text(GREENHOUSE_CONTENT)
    assert text == "About Us\nWe build Python & Go services.\n\n• Kubernetes\n• PostgreSQL"
    assert "alert" not in text and "<" not in text
    assert html_to_text("<p>Apply&nbsp;now</p><br><p>Thanks</p>") == "Apply now\n\nThanks"
    assert html_to_text("Plain text stays as it is.") == "Plain text stays as it is."
    assert looks_like_html(GREENHOUSE_CONTENT) and looks_like_html("<p>x</p>")
    assert not looks_like_html("Salary < 5000 and > 1000")


def raw(description, url="https://boards.greenhouse.io/acme/jobs/1"):
    return {"title": "Backend Engineer", "company_name": "Acme", "description": description,
            "location_text": "Remote", "application_url": url}


async def ingest(db, data, source_id):
    async with db() as s:
        job, outcome = await JobIngestionService().ingest_job(
            db=s, raw_data=data, source_id=source_id, source_platform="greenhouse",
            original_source_url=data["application_url"],
        )
        return job.id, outcome


async def skills_of(db, job_id):
    async with db() as s:
        return sorted((await s.scalars(select(JobSkill.skill_name).where(JobSkill.job_id == job_id))).all())


async def test_html_descriptions_are_stored_as_text(db):
    source = await make_source(db, "gh")
    job_id, _ = await ingest(db, raw(GREENHOUSE_CONTENT), source)
    async with db() as s:
        job = await s.get(Job, job_id)
        assert job.description.startswith("About Us\nWe build Python & Go services.")


async def test_same_source_refresh_updates_description_and_skills(db):
    source = await make_source(db, "gh")
    job_id, _ = await ingest(db, raw(""), source)  # first seen without a description
    assert await skills_of(db, job_id) == []

    again, outcome = await ingest(db, raw(GREENHOUSE_CONTENT), source)
    assert again == job_id and outcome == "DEDUPLICATED"
    async with db() as s:
        job = await s.get(Job, job_id)
        assert "Kubernetes" in job.description
        assert job.other_sources_count == 0  # the same board seen again is not "another platform"
    skills = [x.lower() for x in await skills_of(db, job_id)]
    assert {"python", "go", "kubernetes", "postgresql"} <= set(skills)

    other = await make_source(db, "other-board")
    await ingest(db, raw("Different text", url="https://boards.greenhouse.io/acme/jobs/1"), other)
    async with db() as s:
        job = await s.get(Job, job_id)
        assert job.other_sources_count == 1
        assert "Kubernetes" in job.description  # another source never overwrites the description


async def test_clean_stored_job_text_repairs_old_rows(db):
    source = await make_source(db, "gh")
    async with db() as s:
        s.add(Job(title="Platform Engineer", normalized_title="platform engineer", company_name="Acme",
                  normalized_company="acme", description=GREENHOUSE_CONTENT, application_url="https://x/1",
                  source_platform="greenhouse", original_source_url="https://x/1", primary_source_id=source))
        s.add(Job(title="Writer", normalized_title="writer", company_name="Acme", normalized_company="acme",
                  description="Already plain.", application_url="https://x/2", source_platform="greenhouse",
                  original_source_url="https://x/2", primary_source_id=source))
        await s.commit()

    async with db() as s:
        result = await clean_stored_job_text(s, batch_size=1)  # small batches exercise paging
    assert result["descriptions_cleaned"] == 1 and result["jobs_total"] == 2
    async with db() as s:
        job = await s.scalar(select(Job).where(Job.title == "Platform Engineer"))
        assert not looks_like_html(job.description)
    assert "Kubernetes" in await skills_of(db, job.id)
    async with db() as s:
        assert (await clean_stored_job_text(s))["descriptions_cleaned"] == 0  # idempotent


async def test_list_endpoints_report_totals_and_page(client, db):
    await register_and_login(client)
    async with db() as s:
        s.add_all([
            Business(name=f"Shop {i:02d}", normalized_name=f"shop {i:02d}", country="Nigeria", city="Ikeja",
                     lead_score=i, original_source_url=f"https://www.openstreetmap.org/node/{i}")
            for i in range(7)
        ])
        await s.commit()

    first = await client.get(f"{API}/businesses", params={"limit": 3, "offset": 0})
    assert first.headers["X-Total-Count"] == "7" and len(first.json()) == 3
    last = await client.get(f"{API}/businesses", params={"limit": 3, "offset": 6})
    assert len(last.json()) == 1
    names = {b["name"] for b in first.json()} | {b["name"] for b in last.json()}
    assert len(names) == 4  # pages don't overlap

    filtered = await client.get(f"{API}/businesses", params={"min_lead_score": 5, "limit": 3})
    assert filtered.headers["X-Total-Count"] == "2"  # the total follows the filters

    for path in ("/jobs", "/events"):
        r = await client.get(f"{API}{path}", params={"limit": 5})
        assert r.status_code == 200 and r.headers["X-Total-Count"] == "0"
