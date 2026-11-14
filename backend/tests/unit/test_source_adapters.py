"""
Adapter tests built from trimmed copies of the real responses (2026-11), so a drift between
an adapter and its source's actual format shows up here rather than as silent empty runs.
"""
import json
from datetime import datetime, timezone

import pytest

from app.modules.events.adapters.mlh import MLHEventsAdapter, current_season
from app.modules.events.adapters.zindi import ZindiCompetitionsAdapter, parse_usd_reward
from app.modules.jobs.adapters.greenhouse import GreenhouseBoardsAdapter
from app.modules.scraping.adapter_base import DiscoverySeed, RateLimitPolicy, RawFetchArtifact
from app.modules.scraping.pipeline import _max_response_bytes

POLICY = RateLimitPolicy()


def artifact(url: str, body: str, status: int = 200, content_type: str = "application/json") -> RawFetchArtifact:
    return RawFetchArtifact(
        seed=DiscoverySeed(url=url), final_url=url, status_code=status,
        content_type=content_type, body_text=body, fetched_at=datetime.now(timezone.utc),
    )


# --- Zindi -----------------------------------------------------------------------------

ZINDI_PAGE = {
    "data": [
        {"id": "GenAI-for-Good-Challenge", "title": "GenAI for Good Challenge", "open": True,
         "organization": "IEEE x UNDP", "reward": "$40 000 USD", "reward_type": "prize",
         "start_time": "2026-11-05T16:30:00.000Z", "end_time": "2026-12-13T04:59:00.000Z",
         "is_access_restricted": False, "secret_code_required": False},
        {"id": "PyCon-Somalia", "title": "PyCon Somalia Hack", "open": True,
         "reward": "Awards at PyCon Somalia", "reward_type": "points",
         "end_time": "2026-12-01T00:00:00.000Z"},
        {"id": "Private-Cohort", "title": "Cohort only", "open": True, "is_access_restricted": True},
        {"id": "Old-One", "title": "Finished competition", "open": False},
    ],
    "meta": {"total_count": 521, "open_count": 6},
}


async def test_zindi_discovers_open_competitions_on_current_api_host():
    seeds = [s async for s in ZindiCompetitionsAdapter({}, POLICY).discover({})]
    assert len(seeds) == 1
    assert seeds[0].url.startswith("https://api.zindi.world/v1/competitions")
    assert "status=open" in seeds[0].url


async def test_zindi_extract_keeps_public_open_competitions_only():
    adapter = ZindiCompetitionsAdapter({}, POLICY)
    items, nxt = await adapter.extract(artifact("https://api.zindi.world/v1/competitions", json.dumps(ZINDI_PAGE)))

    assert [i.external_id for i in items] == ["zindi_GenAI-for-Good-Challenge", "zindi_PyCon-Somalia"]
    assert items[0].source_url == "https://zindi.africa/competitions/GenAI-for-Good-Challenge"
    assert nxt == []
    assert all(adapter.validate(adapter.normalize(i)).is_valid for i in items)


async def test_zindi_non_json_response_yields_nothing():
    items, _ = await ZindiCompetitionsAdapter({}, POLICY).extract(
        artifact("https://api.zindi.world/v1/competitions", "<!DOCTYPE html><html>", content_type="text/html")
    )
    assert items == []


@pytest.mark.parametrize(
    "reward, reward_type, expected",
    [
        ("$40 000 USD", "prize", 40000.0),
        ("$1 500 USD", "prize", 1500.0),
        ("Awards at PyCon Somalia", "points", None),
        ("KES 100 000", "prize", None),   # other currencies are not reported as USD
        ("Knowledge", "knowledge", None),
        (None, "prize", None),
    ],
)
def test_zindi_reward_parsing(reward, reward_type, expected):
    assert parse_usd_reward(reward, reward_type) == expected


# --- MLH -----------------------------------------------------------------------------------

def mlh_page(upcoming):
    data = {"component": "SeasonEvents/Index", "props": {"upcomingEvents": upcoming, "pastEvents": []}}
    return (
        "<!DOCTYPE html><html><head></head><body>"
        f'<script data-page="app" type="application/json">{json.dumps(data)}</script>'
        "</body></html>"
    )


MLH_EVENT = {
    "id": "01a0162f-b065-b062-8eb4-6a532b05ba7f", "slug": "emory-hacks-b9", "name": "Emory Hacks",
    "status": "pending", "startsAt": "2026-11-13T19:00:00Z", "endsAt": "2026-11-15T18:00:00Z",
    "dateRange": "NOV 13 - 15", "location": "Atlanta, GA", "formatType": "physical",
    "websiteUrl": "https://emoryhacks.com/", "venueAddress": {"city": "Atlanta", "state": "GA", "country": "US"},
    "customFields": {"hackathon_focus": ["Software"]}, "organizationName": None,
}


def test_mlh_season_rolls_over_in_august():
    assert current_season(datetime(2026, 7, 31, tzinfo=timezone.utc)) == 2026
    assert current_season(datetime(2026, 8, 1, tzinfo=timezone.utc)) == 2027
    assert current_season(datetime(2026, 11, 12, tzinfo=timezone.utc)) == 2027


async def test_mlh_discovers_current_season_page_on_mlh_com():
    seeds = [s async for s in MLHEventsAdapter({"season": 2027}, POLICY).discover({})]
    assert seeds[0].url == "https://www.mlh.com/seasons/2027/events"


async def test_mlh_extracts_and_normalizes_upcoming_events():
    adapter = MLHEventsAdapter({}, POLICY)
    virtual = {**MLH_EVENT, "id": "v1", "slug": "global-hack", "name": "Global Hack Week",
               "formatType": "digital", "location": None, "websiteUrl": None, "venueAddress": {}}
    items, _ = await adapter.extract(
        artifact("https://www.mlh.com/seasons/2027/events", mlh_page([MLH_EVENT, virtual]), content_type="text/html")
    )
    assert [i.source_url for i in items] == [
        "https://www.mlh.com/events/emory-hacks-b9", "https://www.mlh.com/events/global-hack"
    ]

    physical = adapter.normalize(items[0])
    assert adapter.validate(physical).is_valid
    assert physical.delivery_mode == "PHYSICAL" and physical.city == "Atlanta" and physical.country == "US"
    assert physical.registration_url == "https://emoryhacks.com/"
    assert physical.start_date == datetime(2026, 11, 13, 19, 0, tzinfo=timezone.utc)

    online = adapter.normalize(items[1])
    assert online.delivery_mode == "VIRTUAL" and online.international_eligible is True
    assert online.registration_url == "https://www.mlh.com/events/global-hack"  # no website: MLH page


async def test_mlh_layout_change_fails_loudly():
    with pytest.raises(ValueError, match="Inertia page data"):
        await MLHEventsAdapter({}, POLICY).extract(
            artifact("https://www.mlh.com/seasons/2027/events", "<html><body>redesigned</body></html>", content_type="text/html")
        )


# --- Greenhouse & size limits ----------------------------------------------------------------

async def test_greenhouse_default_boards_exclude_boards_that_left_greenhouse():
    seeds = [s async for s in GreenhouseBoardsAdapter({}, POLICY).discover({})]
    tokens = [s.cursor_metadata["company_token"] for s in seeds]
    assert {"paystack", "andela", "wave"}.isdisjoint(tokens)
    assert {"moniepoint", "gitlab", "cloudflare"} <= set(tokens)


@pytest.mark.parametrize(
    "config, expected",
    [({}, None), ({"max_response_mb": 25}, 25 * 1024 * 1024), ({"max_response_mb": "2.5"}, int(2.5 * 1024 * 1024)),
     ({"max_response_mb": "lots"}, None), (None, None)],
)
def test_per_source_response_limit_from_config(config, expected):
    assert _max_response_bytes(config) == expected


# --- Devpost ---------------------------------------------------------------------------------

from app.modules.events.adapters.devpost import (  # noqa: E402
    DevpostHackathonsAdapter,
    parse_prize,
    parse_submission_period,
)

DEVPOST_RAW = {  # real public API shape (2026-11)
    "id": 26781, "title": "Kiroween 2026", "url": "https://kiroween.devpost.com/",
    "organization_name": "Kiro", "open_state": "open",
    "displayed_location": {"icon": "globe", "location": "Online"},
    "submission_period_dates": "Oct 30 - Dec 04, 2026",
    "prize_amount": "$<span data-currency-value>100,000</span>",
    "themes": [{"id": 6, "name": "Machine Learning/AI"}],
}


@pytest.mark.parametrize(
    "text, start, end",
    [
        ("Oct 30 - Dec 04, 2026", (2026, 10, 30), (2026, 12, 4)),
        ("Nov 01 - 15, 2026", (2026, 11, 1), (2026, 11, 15)),
        ("Dec 15, 2026 - Jan 10, 2027", (2026, 12, 15), (2027, 1, 10)),
        ("Dec 15 - Jan 10, 2027", (2026, 12, 15), (2027, 1, 10)),
    ],
)
def test_devpost_submission_period_parsing(text, start, end):
    s, e = parse_submission_period(text)
    assert (s.year, s.month, s.day) == start
    assert (e.year, e.month, e.day, e.hour, e.minute) == (*end, 23, 59)  # end of the last day, UTC


@pytest.mark.parametrize("text", [None, "", "TBD", "Ongoing"])
def test_devpost_unparseable_period_gives_no_dates(text):
    assert parse_submission_period(text) == (None, None)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("$<span data-currency-value>100,000</span>", ("$100,000 in prizes", True, 100000.0)),
        ("€<span data-currency-value>5,000</span>", ("€5,000 in prizes", True, None)),  # not USD
        ("Non-cash prizes", ("Non-cash prizes", False, None)),
        ("$<span data-currency-value>0</span>", (None, False, None)),
        (None, (None, False, None)),
    ],
)
def test_devpost_prize_parsing_strips_html(raw, expected):
    assert parse_prize(raw) == expected


def test_devpost_normalize_real_record():
    from app.modules.scraping.adapter_base import ExtractedItem

    adapter = DevpostHackathonsAdapter({}, POLICY)
    item = ExtractedItem(external_id="devpost_26781", source_url=DEVPOST_RAW["url"], raw_data=DEVPOST_RAW,
                         discovered_at=datetime.now(timezone.utc))
    ev = adapter.normalize(item)
    assert "<" not in (ev.prize_summary or "")
    assert ev.prize_summary == "$100,000 in prizes" and ev.prize_amount_usd_est == 100000.0
    assert ev.registration_deadline is not None and ev.registration_deadline.date().isoformat() == "2026-12-04"
    assert ev.start_date is not None and ev.start_date.date().isoformat() == "2026-10-30"
    assert ev.delivery_mode == "VIRTUAL"
    in_person = adapter.normalize(ExtractedItem(
        external_id="x", source_url="https://x.devpost.com/",
        raw_data={**DEVPOST_RAW, "displayed_location": {"icon": "map-marker", "location": "Lagos, Nigeria"}},
        discovered_at=datetime.now(timezone.utc)))
    assert in_person.delivery_mode == "PHYSICAL"


# --- OpenStreetMap Overpass -----------------------------------------------------------------

from app.modules.businesses.adapters.osm_overpass import OpenStreetMapOverpassAdapter  # noqa: E402


@pytest.mark.parametrize(
    "requested, city, state",
    [
        ("Ikeja", "Ikeja", "Lagos"),
        ("Abuja", "Abuja", "Federal Capital Territory"),       # used to fall back to Ikeja
        ("Lagos", "Lagos", "Lagos"),                            # used to fall back to Ikeja
        ("Victoria Island", "Lagos", "Lagos"),
        ("Port Harcourt", "Port Harcourt", "Rivers"),           # offered in the UI, was missing
        ("Ibadan", "Ibadan", "Oyo"),
    ],
)
def test_osm_city_maps_to_its_own_area(requested, city, state):
    area = OpenStreetMapOverpassAdapter.match_area(requested)
    assert (area["city"], area["state"]) == (city, state)


async def test_osm_businesses_get_the_crawled_areas_city_and_state():
    from app.modules.scraping.adapter_base import ExtractedItem

    adapter = OpenStreetMapOverpassAdapter({}, POLICY)
    seed = [s async for s in adapter.discover({"city": "Abuja"})][0]
    assert seed.cursor_metadata == {"city": "Abuja", "state": "Federal Capital Territory", "country": "Nigeria"}
    item = ExtractedItem(
        external_id="osm_node_1", source_url="https://www.openstreetmap.org/node/1",
        raw_data={"name": "Wuse Market Pharmacy", "tags": {"amenity": "pharmacy"}, "metadata": seed.cursor_metadata},
        discovered_at=datetime.now(timezone.utc),
    )
    biz = adapter.normalize(item)
    assert (biz.city, biz.state, biz.country) == ("Abuja", "Federal Capital Territory", "Nigeria")  # not "Lagos"


# --- Kaggle (current API: KGAT_ bearer tokens, full URLs, "400,000 Usd" rewards) ---

def test_kaggle_reward_parsing():
    from app.modules.events.adapters.kaggle import parse_reward

    assert parse_reward("400,000 Usd") == ("$400,000", 400000.0)
    assert parse_reward("$25,000") == ("$25,000", 25000.0)
    assert parse_reward("10,000 Eur") == ("10,000 Eur", None)  # no USD estimate for other currencies
    assert parse_reward("Knowledge") == ("Practice competition (no prize)", None)
    assert parse_reward("3 Swag") == ("Merchandise prizes", None)
    assert parse_reward("") == (None, None)


def test_kaggle_auth_header_supports_new_and_legacy_keys(monkeypatch):
    import base64

    from app.modules.events.adapters import kaggle

    creds = {"KAGGLE_KEY": "KGAT_abc123", "KAGGLE_USERNAME": "someone"}
    monkeypatch.setattr(kaggle, "get_credential", lambda name: creds.get(name))
    assert kaggle.KaggleCompetitionsAdapter._auth_header() == "Bearer KGAT_abc123"

    creds["KAGGLE_KEY"] = "0123456789abcdef0123456789abcdef"
    expected = base64.b64encode(b"someone:0123456789abcdef0123456789abcdef").decode()
    assert kaggle.KaggleCompetitionsAdapter._auth_header() == f"Basic {expected}"


async def test_kaggle_extract_and_normalize_current_payload(monkeypatch):
    import json as _json
    from datetime import datetime, timezone

    from app.modules.events.adapters import kaggle
    from app.modules.scraping.adapter_base import RawFetchArtifact

    monkeypatch.setattr(kaggle, "get_credential", lambda name: "KGAT_x" if name == "KAGGLE_KEY" else None)
    payload = [{
        "id": 178013, "title": "Agent Harness Challenge",
        "ref": "https://www.kaggle.com/competitions/agent-harness",
        "url": "https://www.kaggle.com/competitions/agent-harness",
        "description": "Build agents", "organizationName": "Google", "category": "Featured",
        "reward": "400,000 Usd", "deadline": "2027-01-05T23:59:59Z", "newEntrantDeadline": "2026-12-29T23:59:59Z",
    }] * kaggle.PAGE_SIZE
    adapter = kaggle.KaggleCompetitionsAdapter({}, None)
    seed = [s async for s in adapter.discover({})][0]
    assert seed.headers["Authorization"] == "Bearer KGAT_x"
    artifact = RawFetchArtifact(seed=seed, final_url=seed.url, status_code=200, content_type="application/json",
                                body_text=_json.dumps(payload), fetched_at=datetime.now(timezone.utc))
    items, next_seeds = await adapter.extract(artifact)
    assert len(items) == kaggle.PAGE_SIZE and next_seeds[0].url.endswith("page=2")  # full page -> next page

    event = adapter.normalize(items[0])
    assert event.registration_url == "https://www.kaggle.com/competitions/agent-harness"
    assert event.registration_deadline == datetime(2026, 12, 29, 23, 59, 59, tzinfo=timezone.utc)  # entry deadline
    assert event.end_date == datetime(2027, 1, 5, 23, 59, 59, tzinfo=timezone.utc)
    assert (event.prize_summary, event.prize_amount_usd_est, event.has_cash_prizes) == ("$400,000", 400000.0, True)
    assert event.delivery_mode == "VIRTUAL" and event.organizer == "Google"
    assert adapter.validate(event).is_valid


def test_get_credential_reads_env_file_values_and_env_overrides(monkeypatch):
    from app.core import config

    monkeypatch.delenv("KAGGLE_KEY", raising=False)
    monkeypatch.setattr(config.settings, "KAGGLE_KEY", "from-dotenv")
    assert config.get_credential("KAGGLE_KEY") == "from-dotenv"  # .env values count, not only os.environ
    monkeypatch.setenv("KAGGLE_KEY", "from-environment")
    assert config.get_credential("KAGGLE_KEY") == "from-environment"

    monkeypatch.setattr(config.settings, "GOOGLE_PLACES_API_KEY", None)
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    assert config.missing_credentials(["KAGGLE_KEY", "GOOGLE_PLACES_API_KEY"]) == ["GOOGLE_PLACES_API_KEY"]
