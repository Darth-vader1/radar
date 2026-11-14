"""Saved records API: per-user bookmarks with notes, tags, filtering and CSV export."""
import csv
import io
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import delete
from test_auth_api import CSRF, register_and_login

from app.core.config import settings
from app.main import app
from app.models.business import Business
from app.models.event import Event
from app.models.job import Job

pytestmark = pytest.mark.integration
API = f"{settings.API_V1_PREFIX}/saved"


async def make_entities(db):
    async with db() as s:
        biz = Business(name="Mama Put Kitchen", normalized_name="mama put kitchen", country="Nigeria",
                       city="Ikeja", category="Restaurant", original_source_url="https://www.openstreetmap.org/node/1")
        job = Job(title="Senior Python Engineer", normalized_title="senior python engineer", company_name="Acme",
                  normalized_company="acme", description="Build APIs", location_text="Remote",
                  application_url="https://jobs.example.com/1", source_platform="Greenhouse",
                  original_source_url="https://jobs.example.com/1")
        event = Event(name="Global GenAI Hackathon", normalized_name="global genai hackathon", description="d",
                      registration_url="https://hack.example.com", source_url="https://hack.example.com",
                      registration_deadline=datetime.now(timezone.utc) + timedelta(days=20),
                      status="OPEN_REGISTRATION", source_platform="devpost", prize_summary="$10,000 in prizes")
        s.add_all([biz, job, event])
        await s.commit()
        return biz.id, job.id, event.id


async def save(client, entity_type, entity_id, **extra):
    return await client.post(API, json={"entity_type": entity_type, "entity_id": str(entity_id), **extra}, headers=CSRF)


async def test_save_list_update_and_remove(client, db):
    await register_and_login(client)
    biz_id, job_id, event_id = await make_entities(db)

    r = await save(client, "JOB", job_id, note="Strong fit", tags=["Python", " remote ", "python"])
    assert r.status_code == 201
    saved = r.json()
    assert saved["tags"] == ["python", "remote"]  # normalised + de-duplicated
    assert saved["entity"]["title"] == "Senior Python Engineer"
    assert saved["entity"]["url"] == "https://jobs.example.com/1"

    again = await save(client, "JOB", job_id)
    assert again.status_code == 200 and again.json()["id"] == saved["id"]  # idempotent

    await save(client, "BUSINESS", biz_id, tags=["lagos-leads"])
    await save(client, "EVENT", event_id)

    listed = (await client.get(API)).json()
    assert [x["entity_type"] for x in listed] == ["EVENT", "BUSINESS", "JOB"]  # newest first
    assert listed[0]["entity"]["facts"]["prize_summary"] == "$10,000 in prizes"

    upd = await client.patch(f"{API}/{saved['id']}", json={"note": "  Interviewing  ", "tags": ["priority"]}, headers=CSRF)
    assert upd.status_code == 200
    assert upd.json()["note"] == "Interviewing" and upd.json()["tags"] == ["priority"]

    status_resp = await client.get(f"{API}/by-entity/JOB/{job_id}")
    assert status_resp.status_code == 200
    assert (await client.delete(f"{API}/{saved['id']}", headers=CSRF)).status_code == 204
    assert (await client.get(f"{API}/by-entity/JOB/{job_id}")).status_code == 404


async def test_filters_by_type_tag_and_search(client, db):
    await register_and_login(client)
    biz_id, job_id, event_id = await make_entities(db)
    await save(client, "JOB", job_id, tags=["python"])
    await save(client, "BUSINESS", biz_id, tags=["lagos"], note="Call the owner about catering")
    await save(client, "EVENT", event_id, tags=["python"])

    assert [x["entity_type"] for x in (await client.get(API, params={"entity_type": "BUSINESS"})).json()] == ["BUSINESS"]
    assert {x["entity_type"] for x in (await client.get(API, params={"tag": "Python"})).json()} == {"JOB", "EVENT"}
    assert [x["entity_type"] for x in (await client.get(API, params={"q": "acme"})).json()] == ["JOB"]       # company
    assert [x["entity_type"] for x in (await client.get(API, params={"q": "catering"})).json()] == ["BUSINESS"]  # note
    tags = (await client.get(f"{API}/tags")).json()
    assert tags[0] == {"tag": "python", "count": 2}


async def test_users_cannot_see_or_change_each_others_saved_records(client, db):
    biz_id, job_id, _ = await make_entities(db)
    await register_and_login(client)
    mine = (await save(client, "JOB", job_id, note="private note")).json()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as other:
        await register_and_login(other)
        assert (await other.get(API)).json() == []
        assert (await other.patch(f"{API}/{mine['id']}", json={"note": "hacked"}, headers=CSRF)).status_code == 404
        assert (await other.delete(f"{API}/{mine['id']}", headers=CSRF)).status_code == 404
        assert (await other.get(f"{API}/by-entity/JOB/{job_id}")).status_code == 404
        # The other user can save the same job independently.
        assert (await save(other, "JOB", job_id)).status_code == 201

    assert (await client.get(API)).json()[0]["note"] == "private note"  # untouched


async def test_validation_and_missing_entities(client, db):
    await register_and_login(client)
    assert (await save(client, "JOB", uuid.uuid4())).status_code == 404
    assert (await save(client, "PERSON", uuid.uuid4())).status_code == 422
    _, job_id, _ = await make_entities(db)
    too_many = [f"t{i}" for i in range(11)]
    assert (await save(client, "JOB", job_id, tags=too_many)).status_code == 422
    assert (await save(client, "JOB", job_id, note="x" * 2001)).status_code == 422


async def test_saved_entity_deleted_later_is_reported_unavailable(client, db):
    await register_and_login(client)
    _, job_id, _ = await make_entities(db)
    await save(client, "JOB", job_id)
    async with db() as s:
        await s.execute(delete(Job).where(Job.id == job_id))
        await s.commit()

    listed = (await client.get(API)).json()
    assert len(listed) == 1 and listed[0]["entity"] is None


async def test_csv_export_and_formula_injection_guard(client, db):
    await register_and_login(client)
    biz_id, job_id, _ = await make_entities(db)
    await save(client, "JOB", job_id, note="=HYPERLINK(\"http://evil\")", tags=["python"])
    await save(client, "BUSINESS", biz_id)

    r = await client.get(f"{API}/export.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text.lstrip("﻿"))))
    assert rows[0][:4] == ["type", "title", "details", "url"]
    job_row = next(row for row in rows if row[0] == "JOB")
    assert job_row[1] == "Senior Python Engineer"
    assert job_row[6].startswith("'=")  # neutralised, not executable in a spreadsheet

    only_jobs = list(csv.reader(io.StringIO((await client.get(f"{API}/export.csv", params={"entity_type": "JOB"})).text.lstrip("﻿"))))
    assert len(only_jobs) == 2


async def test_requires_authentication(client):
    assert (await client.get(API)).status_code == 401
