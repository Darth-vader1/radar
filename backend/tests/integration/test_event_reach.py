"""Nigeria-first event filtering: which events someone in Nigeria can actually take part in."""
from datetime import datetime, timedelta, timezone

import pytest
from test_auth_api import register_and_login

from app.core.config import settings
from app.models.event import Event

pytestmark = pytest.mark.integration
API = f"{settings.API_V1_PREFIX}/events"


def event(name, mode, country=None, location=None, status="OPEN_REGISTRATION", prize=None):
    return Event(name=name, normalized_name=name.lower(), description="d", delivery_mode=mode, country=country,
                 location_text=location, registration_url=f"https://e.example/{name}",
                 source_url=f"https://e.example/{name}", status=status, prize_amount_usd_est=prize,
                 registration_deadline=datetime.now(timezone.utc) + timedelta(days=10))


async def seed(db):
    async with db() as s:
        s.add_all([
            event("Online Hack", "VIRTUAL", prize=1000),
            event("Hybrid Summit", "HYBRID", country="US"),
            event("US In Person", "PHYSICAL", country="US", prize=5000),
            event("Canada In Person", "PHYSICAL", country="CA"),
            event("Lagos Meetup", "PHYSICAL", country="NG"),
            event("Abuja Hack", "PHYSICAL", location="Abuja, FCT"),  # country missing, city in location text
            event("Nairobi Hack", "PHYSICAL", country="Kenya"),
            event("Closed Online", "VIRTUAL", status="REGISTRATION_CLOSED"),
        ])
        await s.commit()


async def names(client, **params):
    r = await client.get(API, params=params)
    assert r.status_code == 200, r.text
    return {e["name"] for e in r.json()}


async def test_reach_filters_events(client, db):
    await register_and_login(client)
    await seed(db)

    assert await names(client, reach="nigeria", active_only=True) == {
        "Online Hack", "Hybrid Summit", "Lagos Meetup", "Abuja Hack", "Nairobi Hack",
    }
    assert await names(client, reach="in_nigeria") == {"Lagos Meetup", "Abuja Hack"}
    assert len(await names(client, reach="all")) == 8
    assert len(await names(client)) == 8  # no reach parameter: unchanged behaviour
    assert (await client.get(API, params={"reach": "mars"})).status_code == 422


async def test_stats_follow_reach_and_report_counts(client, db):
    await register_and_login(client)
    await seed(db)

    nigeria = (await client.get(f"{API}/stats", params={"reach": "nigeria"})).json()
    assert nigeria["total_active_events"] == 5
    assert nigeria["total_cash_prize_usd"] == 1000  # the US in-person prize is not counted here
    assert nigeria["by_reach"] == {"nigeria": 5, "in_nigeria": 2, "all": 7}

    everything = (await client.get(f"{API}/stats")).json()
    assert everything["total_active_events"] == 7 and everything["total_cash_prize_usd"] == 6000
    assert everything["by_reach"] == nigeria["by_reach"]
