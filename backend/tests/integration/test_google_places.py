"""
Google Places, used two ways: hand-run searches stored with guardrails, and live lookups that are
never stored. Google is faked with httpx.MockTransport, so these tests make no paid calls.
"""
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from test_auth_api import CSRF, register_and_login
from test_run_lifecycle import as_admin

from app.core.config import settings
from app.models.business import Business
from app.models.saved import SavedRecord
from app.models.source import ExtractedRecord, Source
from app.modules.businesses.adapters.google_places import GooglePlacesAdapter, city_and_state
from app.modules.businesses.adapters.osm_overpass import NormalizedBusiness
from app.modules.businesses.services import google_lookup
from app.modules.businesses.services.business_service import BusinessIngestionService
from app.modules.scraping.adapter_base import RawFetchArtifact
from app.modules.scraping.scheduling import dispatch_due_sources

pytestmark = pytest.mark.integration
API = settings.API_V1_PREFIX
PLACE = {
    "id": "ChIJ_place_1",
    "displayName": {"text": "Cilantro Ikeja"},
    "formattedAddress": "12 Allen Ave, Ikeja, Lagos 100001, Nigeria",
    "internationalPhoneNumber": "+234 803 000 0000",
    "websiteUri": None,
    "googleMapsUri": "https://maps.google.com/?cid=123",
    "location": {"latitude": 6.6, "longitude": 3.35},
    "primaryTypeDisplayName": {"text": "Restaurant"},
}


@pytest.fixture(autouse=True)
def google_key(monkeypatch):
    from app.modules.businesses.adapters import google_places as adapter_module
    monkeypatch.setattr(adapter_module, "get_credential", lambda name: "AIza-test-key")
    monkeypatch.setattr(google_lookup, "get_credential", lambda name: "AIza-test-key")


@pytest.fixture
def no_website_checks(monkeypatch):
    """Ingestion would otherwise try to visit websites over the network."""
    from app.modules.businesses.services import business_service

    class Offline:
        async def verify_website(self, candidate_url, business_name, secondary_discovery_attempted=False):
            from app.models.business import WebsiteStatus
            from app.modules.businesses.services.website_checker import WebsiteCheckResult
            return WebsiteCheckResult(status=WebsiteStatus.NO_WEBSITE_FOUND, normalized_url=None, is_social_url=False,
                                      social_platform=None, explanation="offline in tests")

    monkeypatch.setattr(business_service, "WebsiteCheckerService", Offline)


# --- adapter ---------------------------------------------------------------

async def test_adapter_builds_query_follows_pages_and_normalizes():
    adapter = GooglePlacesAdapter({"default_query": "restaurants in Ikeja, Lagos"}, None)
    seed = [s async for s in adapter.discover({})][0]
    assert seed.body == {"textQuery": "restaurants in Ikeja, Lagos, Nigeria", "pageSize": 20}
    assert seed.headers["X-Goog-Api-Key"] == "AIza-test-key" and "nextPageToken" in seed.headers["X-Goog-FieldMask"]

    custom = [s async for s in adapter.discover({"query": "pharmacies in Abuja"})][0]
    assert custom.body["textQuery"] == "pharmacies in Abuja, Nigeria"

    artifact = RawFetchArtifact(seed=seed, final_url=seed.url, status_code=200, content_type="application/json",
                                body_text=json.dumps({"places": [PLACE], "nextPageToken": "tok2"}),
                                fetched_at=datetime.now(UTC))
    items, next_seeds = await adapter.extract(artifact)
    assert items[0].source_url == "https://maps.google.com/?cid=123"  # real Maps link, not a made-up cid
    assert next_seeds[0].body["pageToken"] == "tok2" and next_seeds[0].cursor_metadata["page"] == 2

    biz = adapter.normalize(items[0])
    assert (biz.name, biz.city, biz.state, biz.category) == ("Cilantro Ikeja", "Ikeja", "Lagos", "Restaurant")
    assert biz.google_place_id == "ChIJ_place_1" and biz.data_origin == "google_places"
    assert biz.raw_tags == {}  # the Google payload isn't copied onto the business


def test_city_and_state_from_address():
    assert city_and_state("5 Admiralty Way, Lekki, Lagos, Nigeria") == ("Lagos", "Lagos")
    assert city_and_state("Plot 1, Wuse 2, Abuja, Nigeria") == ("Abuja", "Federal Capital Territory")
    assert city_and_state("Somewhere, Kano, Nigeria") == (None, None)


# --- guardrails ------------------------------------------------------------

async def make_google_source(db, **overrides):
    async with db() as s:
        src = Source(slug="google_places_api", name="Google Places", module_type="BUSINESS", source_category="x",
                     base_url="https://places.googleapis.com", collection_method="OFFICIAL_API",
                     adapter_key="google_places_api", required_env_vars=[], crawl_budget_pages=3,
                     adapter_config={"manual_only": True}, **overrides)
        s.add(src)
        await s.commit()
        return src.id


async def test_manual_only_source_is_never_scheduled(client, db, monkeypatch):
    from app.modules.scraping import scheduling
    queued = []

    async def fake_dispatch(db_, source, trigger, *a, **k):
        queued.append(source.slug)
    monkeypatch.setattr(scheduling, "create_and_dispatch_run", fake_dispatch)

    source_id = await make_google_source(db, schedule_cron="* * * * *")  # even if a schedule slipped in
    assert await dispatch_due_sources(sessionmaker=db, now=datetime.now(UTC) + timedelta(minutes=5)) == []
    assert queued == []

    await as_admin(client, db)
    r = await client.patch(f"{API}/sources/{source_id}", json={"schedule_cron": "0 5 * * *"}, headers=CSRF)
    assert r.status_code == 400


async def test_google_results_never_merge_into_other_sources(db, no_website_checks):
    osm_id = await make_google_source(db)  # reuse helper for a second source row
    async with db() as s:
        osm = await s.get(Source, osm_id)
        osm.slug, osm.adapter_key = "osm", "osm_overpass"
        google = Source(slug="google_places_api", name="Google", module_type="BUSINESS", source_category="x",
                        base_url="https://g", collection_method="OFFICIAL_API", adapter_key="google_places_api",
                        required_env_vars=[])
        s.add(google)
        await s.commit()
        google_id = google.id

    svc = BusinessIngestionService()
    async with db() as s:
        existing, outcome = await svc.ingest_business(s, NormalizedBusiness(name="Cilantro Ikeja", city="Ikeja"),
                                                      osm_id, "https://www.openstreetmap.org/node/1")
        await s.commit()
    async with db() as s:
        merged, outcome = await svc.ingest_business(
            s, NormalizedBusiness(name="Cilantro Ikeja", phone_number="+2348030000000", google_place_id="ChIJ_place_1",
                                  data_origin="google_places"),
            google_id, "https://maps.google.com/?cid=123")
        await s.commit()
    assert outcome == "DEDUPLICATED"
    async with db() as s:
        row = await s.get(Business, existing.id)
        assert row.google_place_id == "ChIJ_place_1"  # only the place ID is attached
        assert row.phone_number is None and row.original_source_url.startswith("https://www.openstreetmap.org")


# --- purge + export --------------------------------------------------------

async def test_remove_all_google_data(client, db):
    google_id = await make_google_source(db)
    async with db() as s:
        g = Business(name="From Google", normalized_name="from google", country="Nigeria",
                     original_source_url="https://maps.google.com/?cid=1", primary_source_id=google_id,
                     google_place_id="ChIJ_g")
        other = Business(name="From OSM", normalized_name="from osm", country="Nigeria",
                         original_source_url="https://www.openstreetmap.org/node/2", google_place_id="ChIJ_keep")
        s.add_all([g, other])
        await s.flush()
        s.add(ExtractedRecord(source_id=google_id, entity_type="BUSINESS", source_url="https://maps.google.com/?cid=1",
                              content_hash="h", raw_payload={"displayName": {"text": "From Google"}}))
        await s.commit()
        g_id, other_id = g.id, other.id

    await as_admin(client, db)
    await client.post(f"{API}/saved", json={"entity_type": "BUSINESS", "entity_id": str(g_id)}, headers=CSRF)
    await client.post(f"{API}/saved", json={"entity_type": "BUSINESS", "entity_id": str(other_id)}, headers=CSRF)

    # CSV export leaves Google businesses out unless asked.
    csv_default = (await client.get(f"{API}/saved/export.csv")).text
    assert "From OSM" in csv_default and "From Google" not in csv_default
    assert "From Google" in (await client.get(f"{API}/saved/export.csv", params={"include_google": "true"})).text

    assert (await client.get(f"{API}/admin/google-data")).json() == {"businesses": 1, "raw_records": 1}
    r = await client.delete(f"{API}/admin/google-data", headers=CSRF)
    assert r.status_code == 200 and r.json() == {"businesses": 1, "raw_records": 1}

    async with db() as s:
        assert await s.get(Business, g_id) is None
        kept = await s.get(Business, other_id)
        assert kept is not None and kept.google_place_id == "ChIJ_keep"  # place IDs may be kept
        assert await s.scalar(select(func.count(ExtractedRecord.id))) == 0
        assert await s.scalar(select(func.count(SavedRecord.id))) == 1  # the OSM bookmark remains


async def test_standard_users_cannot_remove_google_data(client, db):
    await register_and_login(client)
    assert (await client.delete(f"{API}/admin/google-data", headers=CSRF)).status_code == 403


# --- live lookup -------------------------------------------------------------

def fake_google(monkeypatch, calls, details_status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.headers.get("X-Goog-FieldMask")))
        if request.url.path.endswith(":searchText"):
            return httpx.Response(200, json={"places": [{"id": "ChIJ_found"}]})
        if details_status != 200:
            return httpx.Response(details_status, json={"error": {"message": "nope"}})
        return httpx.Response(200, json={
            "id": "ChIJ_found", "displayName": {"text": "Mama Put"}, "nationalPhoneNumber": "0803 000 0000",
            "websiteUri": "https://mamaput.ng", "googleMapsUri": "https://maps.google.com/?cid=9", "rating": 4.4,
            "userRatingCount": 120, "regularOpeningHours": {"weekdayDescriptions": ["Monday: 8 AM - 9 PM"]},
        })
    monkeypatch.setattr(google_lookup, "client_factory",
                        lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kw))


async def test_live_lookup_shows_details_and_stores_only_the_place_id(client, db, monkeypatch):
    async with db() as s:
        b = Business(name="Mama Put", normalized_name="mama put", country="Nigeria", city="Ikeja",
                     original_source_url="https://www.openstreetmap.org/node/3")
        s.add(b)
        await s.commit()
        bid = b.id
    calls = []
    fake_google(monkeypatch, calls)
    await as_admin(client, db)

    r = await client.get(f"{API}/businesses/{bid}/google")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["matched_by"] == "search" and data["phone"] == "0803 000 0000" and data["rating"] == 4.4
    assert data["opening_hours"] == ["Monday: 8 AM - 9 PM"] and data["attribution"] == "Google Maps"
    assert [c[1] for c in calls] == ["/v1/places:searchText", "/v1/places/ChIJ_found"]
    assert calls[0][2] == "places.id"  # the search asks only for the ID

    async with db() as s:
        row = await s.get(Business, bid)
        assert row.google_place_id == "ChIJ_found"
        assert row.phone_number is None and row.website_url is None  # nothing else stored

    calls.clear()
    again = (await client.get(f"{API}/businesses/{bid}/google")).json()
    assert again["matched_by"] == "place_id" and [c[1] for c in calls] == ["/v1/places/ChIJ_found"]


async def test_live_lookup_errors_and_permissions(client, db, monkeypatch):
    async with db() as s:
        b = Business(name="Gone Place", normalized_name="gone place", country="Nigeria",
                     original_source_url="https://www.openstreetmap.org/node/4", google_place_id="ChIJ_gone")
        s.add(b)
        await s.commit()
        bid = b.id

    await register_and_login(client)
    assert (await client.get(f"{API}/businesses/{bid}/google")).status_code == 403  # paid call: researchers+

    client.cookies.clear()
    await as_admin(client, db)
    fake_google(monkeypatch, [], details_status=404)
    assert (await client.get(f"{API}/businesses/{bid}/google")).status_code == 404

    monkeypatch.setattr(google_lookup, "get_credential", lambda name: None)
    r = await client.get(f"{API}/businesses/{bid}/google")
    assert r.status_code == 400 and "GOOGLE_PLACES_API_KEY" in r.json()["detail"]
