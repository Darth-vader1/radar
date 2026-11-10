from datetime import datetime, timezone

import pytest

from app.models.business import Business, WebsiteStatus
from app.modules.businesses.adapters.osm_overpass import OpenStreetMapOverpassAdapter
from app.modules.businesses.services.email_verifier import EmailVerifierService, VerificationStatus
from app.modules.businesses.services.lead_scorer import LeadScoringEngine
from app.modules.businesses.services.website_checker import WebsiteCheckerService
from app.modules.scraping.adapter_base import ExtractedItem, RateLimitPolicy


@pytest.mark.asyncio
async def test_website_checker_social_detection():
    checker = WebsiteCheckerService()

    # Instagram link mistakenly stored as website
    res = await checker.verify_website(
        candidate_url="https://www.instagram.com/lagos_grill_house/",
        business_name="Lagos Grill House",
    )
    assert res.is_social_url is True
    assert res.social_platform == "INSTAGRAM"
    assert res.status == WebsiteStatus.WEBSITE_REQUIRES_MANUAL_VERIFICATION


@pytest.mark.asyncio
async def test_website_checker_absent_url_rule():
    checker = WebsiteCheckerService()

    # Absent URL without secondary check
    res_pending = await checker.verify_website(
        candidate_url=None,
        business_name="Ikeja Bistro",
        secondary_discovery_attempted=False,
    )
    assert res_pending.status == WebsiteStatus.WEBSITE_REQUIRES_MANUAL_VERIFICATION

    # Absent URL with secondary check completed
    res_confirmed = await checker.verify_website(
        candidate_url=None,
        business_name="Ikeja Bistro",
        secondary_discovery_attempted=True,
    )
    assert res_confirmed.status == WebsiteStatus.NO_WEBSITE_FOUND


def test_email_verifier_syntax_and_disposable():
    verifier = EmailVerifierService()

    # Invalid syntax
    invalid_res = verifier.verify_email("not-an-email-at-all")
    assert invalid_res.syntax_valid is False
    assert invalid_res.status == VerificationStatus.INVALID

    # Disposable domain
    disp_res = verifier.verify_email("test@mailinator.com")
    assert disp_res.disposable_domain is True
    assert disp_res.status == VerificationStatus.INVALID


@pytest.mark.asyncio
async def test_lead_scoring_engine():
    scorer = LeadScoringEngine()

    # Construct test business matching high sales opportunity:
    # No website (+30), no online ordering (+20), has public email (+15), high value restaurant (+10), recent (+5)
    biz = Business(
        name="Mama Cass Restaurant Ikeja",
        normalized_name="mama cass restaurant ikeja",
        category="Restaurant",
        website_status=WebsiteStatus.NO_WEBSITE_FOUND.value,
        has_online_ordering=False,
        public_email="info@mamacass.example",
        discovered_at=datetime.now(timezone.utc),
        country="Nigeria",
        original_source_url="https://www.openstreetmap.org/node/123",
    )

    result = await scorer.calculate_score(biz)

    assert result.score >= 60
    assert any(b["rule_key"] == "no_website_found" for b in result.breakdown)
    assert any(b["rule_key"] == "public_business_email" for b in result.breakdown)
    assert any(b["rule_key"] == "no_online_ordering" for b in result.breakdown)
    assert "Lead score:" in result.explanation


def test_osm_overpass_normalization():
    adapter = OpenStreetMapOverpassAdapter(source_config={}, rate_policy=RateLimitPolicy())

    item = ExtractedItem(
        external_id="osm_node_1001",
        source_url="https://www.openstreetmap.org/node/1001",
        raw_data={
            "name": "Bungalow Restaurant & Bar",
            "lat": 6.5950,
            "lon": 3.3550,
            "tags": {
                "amenity": "restaurant",
                "cuisine": "african",
                "contact:phone": "+234 803 123 4567",
                "contact:website": "https://bungalowrestaurant.ng",
                "addr:street": "Isaac John Street",
                "addr:city": "Ikeja",
            },
            "metadata": {"city": "Ikeja", "state": "Lagos", "country": "Nigeria"},
        },
        discovered_at=datetime.now(timezone.utc),
    )

    normalized = adapter.normalize(item)
    assert normalized.name == "Bungalow Restaurant & Bar"
    assert normalized.category == "Restaurant"
    assert normalized.city == "Ikeja"
    assert normalized.phone_number == "+234 803 123 4567"
    assert normalized.website_url == "https://bungalowrestaurant.ng"

    val_res = adapter.validate(normalized)
    assert val_res.is_valid is True
