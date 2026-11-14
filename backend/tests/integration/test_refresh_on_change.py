"""Re-runs pick up changes at the source instead of treating every known record as a duplicate."""
import pytest
import test_pipeline_e2e as e2e
from sqlalchemy import select
from test_run_lifecycle import create_run, create_source, execute

from app.models.event import Event

pytestmark = pytest.mark.integration


async def test_changed_deadline_at_source_updates_stored_event(db, monkeypatch):
    source_id = await create_source(db, "devpost_hackathons")
    first, _ = await execute(db, await create_run(db, source_id))
    assert first.records_created == 1

    hackathon = dict(e2e.FIXTURES["https://devpost.com/api/hackathons"]["hackathons"][0])
    hackathon["submission_period_ends_at"] = "2027-03-31T23:00:00+00:00"   # organiser extended the deadline
    monkeypatch.setitem(e2e.FIXTURES, "https://devpost.com/api/hackathons", {"hackathons": [hackathon]})

    second, _ = await execute(db, await create_run(db, source_id))
    assert second.records_updated == 1 and second.records_deduplicated == 0

    async with db() as s:
        events = (await s.scalars(select(Event))).all()
    assert len(events) == 1
    assert events[0].registration_deadline.isoformat().startswith("2027-03-31")


async def test_unchanged_record_is_still_deduplicated(db):
    source_id = await create_source(db, "devpost_hackathons")
    await execute(db, await create_run(db, source_id))
    again, _ = await execute(db, await create_run(db, source_id))
    assert again.records_deduplicated == 1 and again.records_created == 0 and again.records_updated == 0
