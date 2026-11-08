"""
End-to-end pipeline test: seeded Source -> SourceRun -> PipelineOrchestrator.execute_run
-> rows in extracted_records and the business / job / event domain tables.

Only the network is faked (a gateway that serves fixture payloads per URL); the real
adapter registry, adapters, ingestion services and PostgreSQL schema are used.
"""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.models.business import Business
from app.models.event import Event
from app.models.job import Job
from app.models.source import ExtractedRecord, RunStatus, Source, SourceRun
from app.modules.adapters_loader import load_adapters
from app.modules.scraping import pipeline as pipeline_module
from app.modules.scraping.adapter_base import RawFetchArtifact
from app.modules.scraping.pipeline import PipelineOrchestrator

pytestmark = pytest.mark.integration

DEADLINE = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

FIXTURES = {
    "https://remotive.com/api/remote-jobs": {
        "jobs": [
            {
                "id": 101,
                "title": "Senior Python Backend Engineer",
                "company_name": "Acme Cloud",
                "company_url": "https://acme.example",
                "url": "https://remotive.com/remote-jobs/software-dev/senior-python-101",
                "description": "<p>Build APIs with Python, FastAPI, PostgreSQL and Docker.</p>",
                "candidate_required_location": "Worldwide",
                "publication_date": "2026-11-01T10:00:00",
            },
            {
                "id": 102,
                "title": "Frontend Engineer (React)",
                "company_name": "Beta Labs",
                "url": "https://remotive.com/remote-jobs/software-dev/frontend-102",
                "description": "<p>React, TypeScript, Next.js.</p>",
                "candidate_required_location": "Africa",
                "publication_date": "2026-11-02T10:00:00",
            },
        ]
    },
    "https://overpass-api.de/api/interpreter": {
        "elements": [
            {"type": "node", "id": 9001, "lat": 6.6, "lon": 3.35,
             "tags": {"name": "Mama Put Kitchen", "amenity": "restaurant", "addr:city": "Ikeja", "phone": "+2348012345678"}},
            {"type": "node", "id": 9002, "lat": 6.61, "lon": 3.36,
             "tags": {"name": "Allen Avenue Pharmacy", "amenity": "pharmacy", "addr:city": "Ikeja"}},
            {"type": "node", "id": 9003, "lat": 6.61, "lon": 3.36, "tags": {"amenity": "bank"}},  # unnamed: skipped
        ]
    },
    "https://devpost.com/api/hackathons": {
        "hackathons": [
            {
                "id": 555,
                "title": "Global GenAI Builders Hackathon",
                "url": "https://genai-builders.devpost.com/",
                "organization_name": "GenAI Collective",
                "submission_period_ends_at": DEADLINE,
                "prize_amount": "$25,000",
                "online": True,
                "displayed_location": {"location": "Online"},
                "themes": [{"name": "Machine Learning/AI"}],
            }
        ]
    },
}


def _fixture_for(url: str):
    for prefix, payload in FIXTURES.items():
        if url.startswith(prefix):
            # Devpost paginates; serve results on page 1 only.
            if "devpost" in url and "page=1" not in url:
                return {"hackathons": []}
            return payload
    raise AssertionError(f"Unexpected outbound URL in test: {url}")


def _fake_gateway():
    async def fetch(seed, rate_policy=None):
        return RawFetchArtifact(
            seed=seed,
            final_url=seed.url,
            status_code=200,
            content_type="application/json",
            body_text=json.dumps(_fixture_for(seed.url)),
            fetched_at=datetime.now(timezone.utc),
        )

    return SimpleNamespace(fetch=AsyncMock(side_effect=fetch), close=AsyncMock())


SOURCES = {
    "remotive_jobs": dict(module_type="JOB", source_category="JOB_BOARD", base_url="https://remotive.com"),
    "osm_overpass": dict(module_type="BUSINESS", source_category="OPEN_DATA", base_url="https://overpass-api.de"),
    "devpost_hackathons": dict(module_type="EVENT", source_category="EVENT_PLATFORM", base_url="https://devpost.com"),
}


async def _create_source_and_run(sessionmaker, adapter_key: str):
    async with sessionmaker() as session:
        source = Source(
            slug=f"test-{adapter_key}",
            name=f"Test {adapter_key}",
            collection_method="OFFICIAL_API",
            adapter_key=adapter_key,
            adapter_config={},
            rate_limit_rpm=60,
            max_concurrency=1,
            crawl_budget_pages=10,
            is_enabled=True,
            respect_robots_txt=True,
            required_env_vars=[],
            **SOURCES[adapter_key],
        )
        session.add(source)
        await session.flush()
        run = SourceRun(source_id=source.id, trigger_type="MANUAL", status=RunStatus.QUEUED.value, search_params={})
        session.add(run)
        await session.commit()
        return source.id, run.id


async def _new_run(sessionmaker, source_id):
    async with sessionmaker() as session:
        run = SourceRun(source_id=source_id, trigger_type="MANUAL", status=RunStatus.QUEUED.value, search_params={})
        session.add(run)
        await session.commit()
        return run.id


async def _execute(sessionmaker, run_id):
    orchestrator = PipelineOrchestrator(gateway=_fake_gateway())
    await orchestrator.execute_run(run_id)
    async with sessionmaker() as session:
        return await session.scalar(select(SourceRun).where(SourceRun.id == run_id))


@pytest.fixture
def pipeline_db(db_sessionmaker, monkeypatch):
    load_adapters()
    monkeypatch.setattr(pipeline_module, "AsyncSessionLocal", db_sessionmaker)
    return db_sessionmaker


@pytest.mark.parametrize(
    "adapter_key, model, expected",
    [
        ("remotive_jobs", Job, 2),
        ("osm_overpass", Business, 2),
        ("devpost_hackathons", Event, 1),
    ],
)
async def test_run_stores_records_in_domain_table(pipeline_db, adapter_key, model, expected):
    source_id, run_id = await _create_source_and_run(pipeline_db, adapter_key)

    run = await _execute(pipeline_db, run_id)

    assert run.status == RunStatus.COMPLETED.value, run.error_summary
    assert run.errors_count == 0
    assert run.pages_fetched >= 1
    assert run.records_extracted == expected
    assert run.records_created == expected
    assert run.finished_at is not None

    async with pipeline_db() as session:
        assert await session.scalar(select(func.count()).select_from(model)) == expected
        records = (await session.scalars(
            select(ExtractedRecord).where(ExtractedRecord.source_run_id == run_id)
        )).all()
        assert len(records) == expected
        assert all(r.processing_status == "STORED" and r.canonical_entity_id for r in records)

        source = await session.scalar(select(Source).where(Source.id == source_id))
        assert source.last_success_at is not None
        assert source.last_error_at is None
        assert source.total_records_collected == expected


async def test_second_run_deduplicates_instead_of_duplicating(pipeline_db):
    source_id, first_run_id = await _create_source_and_run(pipeline_db, "remotive_jobs")
    await _execute(pipeline_db, first_run_id)

    second = await _execute(pipeline_db, await _new_run(pipeline_db, source_id))

    assert second.status == RunStatus.COMPLETED.value, second.error_summary
    assert second.records_created == 0
    assert second.records_deduplicated == 2
    async with pipeline_db() as session:
        assert await session.scalar(select(func.count()).select_from(Job)) == 2


async def test_event_run_links_inferred_categories(pipeline_db):
    _, run_id = await _create_source_and_run(pipeline_db, "devpost_hackathons")
    await _execute(pipeline_db, run_id)

    async with pipeline_db() as session:
        event = await session.scalar(select(Event))
        assert event.has_cash_prizes is True
        assert float(event.prize_amount_usd_est) == 25000.0
        assert event.registration_deadline is not None
        assert event.categories, "expected at least one inferred category"


async def test_unknown_adapter_fails_run_cleanly(pipeline_db):
    source_id, run_id = await _create_source_and_run(pipeline_db, "remotive_jobs")
    async with pipeline_db() as session:
        source = await session.scalar(select(Source).where(Source.id == source_id))
        source.adapter_key = "does_not_exist"
        await session.commit()

    run = await _execute(pipeline_db, run_id)

    assert run.status == RunStatus.FAILED.value
    assert "does_not_exist" in run.error_summary
