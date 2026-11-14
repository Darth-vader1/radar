"""Rule-based insights API: aggregates and highlight sentences computed from collected data."""
from datetime import datetime, timedelta, timezone

import pytest
from test_auth_api import register_and_login

from app.api.v1.insights import build_highlights
from app.core.config import settings
from app.models.business import Business
from app.models.event import Event
from app.models.job import Job, JobSkill

pytestmark = pytest.mark.integration
API = f"{settings.API_V1_PREFIX}/insights"


def job(i, company, remote="REMOTE", status="ACTIVE", skills=(), salary=None, days_old=1):
    j = Job(
        title=f"Engineer {i}", normalized_title=f"engineer {i}", company_name=company,
        normalized_company=company.lower(), description="d", application_url=f"https://jobs.example.com/{i}",
        source_platform="Greenhouse", original_source_url=f"https://jobs.example.com/{i}",
        remote_status=remote, status=status, salary_min=salary,
        discovered_at=datetime.now(timezone.utc) - timedelta(days=days_old),
    )
    j.skills = [JobSkill(skill_name=s, normalized_skill=s.lower()) for s in skills]
    return j


async def seed(db):
    now = datetime.now(timezone.utc)
    async with db() as s:
        s.add_all([
            job(1, "Acme", skills=["Python", "SQL"], salary=50000),
            job(2, "Acme", skills=["Python"], days_old=30),
            job(3, "Beta", remote="ONSITE", skills=["python", "Go"]),
            job(4, "Gone", status="EXPIRED", skills=["Rust", "Rust2", "Rust3"]),  # excluded everywhere
        ])
        s.add_all([
            Event(name="Soon Hack", normalized_name="soon hack", description="d", event_type="HACKATHON",
                  registration_url="https://e.example.com/1", source_url="https://e.example.com/1",
                  registration_deadline=now + timedelta(days=3), status="OPEN_REGISTRATION",
                  prize_amount_usd_est=5000),
            Event(name="Later Hack", normalized_name="later hack", description="d", event_type="HACKATHON",
                  registration_url="https://e.example.com/2", source_url="https://e.example.com/2",
                  registration_deadline=now + timedelta(days=40), status="OPEN_REGISTRATION",
                  prize_amount_usd_est=2500),
            Event(name="Closed", normalized_name="closed", description="d", event_type="GRANT",
                  registration_url="https://e.example.com/3", source_url="https://e.example.com/3",
                  registration_deadline=now - timedelta(days=3), status="REGISTRATION_CLOSED",
                  prize_amount_usd_est=99999),
        ])
        s.add_all([
            Business(name="Top Lead", normalized_name="top lead", country="Nigeria", city="Ikeja",
                     category="Restaurant", lead_score=80, phone_number="+2348000000000",
                     website_status="NO_WEBSITE_FOUND", original_source_url="https://osm.org/node/1"),
            Business(name="Low Lead", normalized_name="low lead", country="Nigeria", city="Abuja",
                     category="Restaurant", lead_score=20, website_status="HAS_WEBSITE",
                     original_source_url="https://osm.org/node/2"),
        ])
        await s.commit()


async def test_insights_aggregates_only_active_records(client, db):
    await register_and_login(client)
    await seed(db)
    r = await client.get(API)
    assert r.status_code == 200, r.text
    data = r.json()

    jobs = data["jobs"]
    assert jobs["total_active"] == 3  # the expired job is excluded
    assert jobs["new_last_7_days"] == 2
    assert jobs["remote_share_pct"] == 66.7
    assert jobs["with_salary_pct"] == 33.3
    # "Python" and "python" are one skill, counted once per job
    assert jobs["top_skills"][0]["count"] == 3
    assert jobs["top_skills"][0]["name"].lower() == "python"
    assert all("rust" not in s["name"].lower() for s in jobs["top_skills"])
    assert jobs["top_companies"][0] == {"name": "Acme", "count": 2}
    assert jobs["by_remote_status"] == {"REMOTE": 2, "ONSITE": 1}

    events = data["events"]
    assert events["total_active"] == 2
    assert events["closing_within_7_days"] == 1
    assert events["total_prize_usd"] == 7500
    assert [e["name"] for e in events["next_deadlines"]] == ["Soon Hack", "Later Hack"]

    biz = data["businesses"]
    assert biz["total"] == 2 and biz["avg_lead_score"] == 50
    assert biz["no_website_count"] == 1
    assert biz["top_leads"][0]["name"] == "Top Lead" and biz["top_leads"][0]["has_phone"] is True
    assert biz["by_city"] == {"Ikeja": 1, "Abuja": 1}

    text = " ".join(data["highlights"])
    assert "listed in 100% of active jobs (3 of 3)" in text
    assert "1 event closes registration in the next 7 days." in text
    assert "1 of 2 businesses have no website" in text
    assert data["freshness"]["jobs"] is not None


async def test_insights_empty_database(client, db):
    await register_and_login(client)
    data = (await client.get(API)).json()
    assert data["highlights"] == []
    assert data["jobs"]["total_active"] == 0 and data["jobs"]["remote_share_pct"] == 0
    assert data["businesses"]["avg_lead_score"] == 0
    assert data["freshness"] == {"jobs": None, "events": None, "businesses": None}


async def test_insights_requires_auth(client, db):
    assert (await client.get(API)).status_code == 401


def test_highlight_pluralisation():
    from app.schemas.insights import BusinessInsights, EventInsights, JobInsights

    empty_jobs = JobInsights(total_active=0, new_last_7_days=0, remote_share_pct=0, with_salary_pct=0,
                             top_skills=[], top_companies=[], by_remote_status={}, by_experience={}, by_category={})
    events = EventInsights(total_active=4, closing_within_7_days=3, total_prize_usd=0, next_deadlines=[],
                           by_type={"HACKATHON": 3, "GRANT": 1}, by_delivery_mode={})
    biz = BusinessInsights(total=0, avg_lead_score=0, no_website_count=0, top_leads=[], by_city={}, top_categories=[])
    assert build_highlights(empty_jobs, events, biz) == [
        "3 events close registration in the next 7 days.",
        "Most open events are hackathons (3 of 4).",
    ]
