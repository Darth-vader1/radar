from datetime import datetime, timedelta, timezone
import pytest
from app.models.event import EventStatus
from app.modules.events.adapters.devpost import DevpostHackathonsAdapter, NormalizedEvent
from app.modules.events.adapters.zindi import ZindiCompetitionsAdapter
from app.modules.events.services.event_classifier import (
    classify_event_categories,
    compute_event_status,
    normalize_event_name,
    parse_prize_amount,
)
from app.modules.scraping.adapter_base import ExtractedItem, RateLimitPolicy


def test_event_name_normalization():
    assert normalize_event_name("Hackathon: Global GenAI Hackathon 2026 [Virtual]") == "global genai hackathon"
    assert normalize_event_name("Announcing: Web3 Lagos Hack (Online)") == "web3 lagos hack"
    assert normalize_event_name("   Pan-African Data Cup   ") == "pan-african data cup"


def test_event_lifecycle_state_machine():
    now = datetime(2026, 11, 8, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Completed
    status = compute_event_status(
        start_date=now - timedelta(days=10),
        end_date=now - timedelta(days=2),
        registration_deadline=now - timedelta(days=5),
        now=now,
    )
    assert status == EventStatus.COMPLETED.value

    # 2. Ongoing
    status = compute_event_status(
        start_date=now - timedelta(days=1),
        end_date=now + timedelta(days=2),
        registration_deadline=now - timedelta(days=3),
        now=now,
    )
    assert status == EventStatus.ONGOING.value

    # 3. Registration Closing Soon (within 7 days)
    status = compute_event_status(
        start_date=now + timedelta(days=10),
        end_date=now + timedelta(days=12),
        registration_deadline=now + timedelta(days=3),
        now=now,
    )
    assert status == EventStatus.REGISTRATION_CLOSING_SOON.value

    # 4. Registration Closed (deadline passed, but event hasn't ended)
    status = compute_event_status(
        start_date=now + timedelta(days=2),
        end_date=now + timedelta(days=5),
        registration_deadline=now - timedelta(days=1),
        now=now,
    )
    assert status == EventStatus.REGISTRATION_CLOSED.value

    # 5. Upcoming (registration hasn't opened yet)
    status = compute_event_status(
        start_date=now + timedelta(days=30),
        end_date=now + timedelta(days=32),
        registration_deadline=now + timedelta(days=25),
        registration_opens_at=now + timedelta(days=5),
        now=now,
    )
    assert status == EventStatus.UPCOMING.value

    # 6. Open Registration
    status = compute_event_status(
        start_date=now + timedelta(days=30),
        end_date=now + timedelta(days=32),
        registration_deadline=now + timedelta(days=20),
        now=now,
    )
    assert status == EventStatus.OPEN_REGISTRATION.value


def test_prize_amount_parsing():
    # USD formats
    has_cash, val, summary = parse_prize_amount("Build with Gemini. $50,000 in prizes across 4 tracks.")
    assert has_cash is True
    assert val == 50000.0
    assert "$50,000" in summary

    # Suffix multiplier (k)
    has_cash, val, summary = parse_prize_amount("Total prize pool: $25k + sponsor credits")
    assert has_cash is True
    assert val == 25000.0

    # Nigerian Naira
    has_cash, val, summary = parse_prize_amount("Grand prize: ₦15,000,000 for top Nigerian fintech solutions.")
    assert has_cash is True
    assert val == 10000.0  # 15m / 1500
    assert "₦15,000,000" in summary

    # Generic cash indicator without exact digits
    has_cash, val, summary = parse_prize_amount("Participants will compete for substantial cash prizes and mentorship.")
    assert has_cash is True
    assert val is None
    assert summary == "Cash prizes available"

    # Zero/swag prizes
    has_cash, val, summary = parse_prize_amount("Winners will receive custom mechanical keyboards, t-shirts, and stickers.")
    assert has_cash is False
    assert val is None


def test_event_category_classification():
    # AI / LLMs
    cats_ai = classify_event_categories(
        name="Global Agentic Hackathon",
        description="Build autonomous LLM agents and multi-modal assistants using Gemini and PyTorch."
    )
    assert "ai" in cats_ai

    # Blockchain
    cats_web3 = classify_event_categories(
        name="Ethereum Nigeria Buildathon",
        description="Deploy smart contracts on Arbitrum and Polygon with Solidity."
    )
    assert "blockchain" in cats_web3

    # Cybersecurity
    cats_sec = classify_event_categories(
        name="Lagos Cyber Defense CTF",
        description="Capture the flag competition testing penetration testing and cryptography skills."
    )
    assert "cybersecurity" in cats_sec


def test_devpost_adapter_normalization():
    adapter = DevpostHackathonsAdapter(
        source_config={},
        rate_policy=RateLimitPolicy(requests_per_minute=20)
    )

    item = ExtractedItem(
        external_id="devpost_12345",
        source_url="https://gemini-sprint.devpost.com/",
        raw_data={
            "id": 12345,
            "title": "Google Gemini Developer Sprint 2026",
            "organization_name": "Google Developers",
            "url": "https://gemini-sprint.devpost.com/",
            "prize_amount": "$75,000",
            "online": True,
            "themes": [{"name": "AI"}, {"name": "Cloud"}],
            "submission_period_dates": "Nov 1 - Dec 15, 2026",
        },
        discovered_at=datetime.now(timezone.utc),
    )

    normalized = adapter.normalize(item)
    outcome = adapter.validate(normalized)

    assert outcome.is_valid is True
    assert normalized.name == "Google Gemini Developer Sprint 2026"
    assert normalized.has_cash_prizes is True
    assert normalized.prize_amount_usd_est == 75000.0
    assert normalized.delivery_mode == "VIRTUAL"
    assert "AI" in normalized.themes


def test_zindi_adapter_normalization():
    adapter = ZindiCompetitionsAdapter(
        source_config={},
        rate_policy=RateLimitPolicy(requests_per_minute=20)
    )

    item = ExtractedItem(
        external_id="zindi_c1",
        source_url="https://zindi.africa/competitions/crop-yield-prediction-challenge",
        raw_data={
            "id": "c1",
            "slug": "crop-yield-prediction-challenge",
            "title": "Crop Yield Prediction Challenge for African Agriculture",
            "host": "FAO & Zindi",
            "reward": "$12,000",
            "tags": ["Agritech", "Machine Learning", "Climate"],
            "end_date": "2026-12-31T23:59:59Z",
        },
        discovered_at=datetime.now(timezone.utc),
    )

    normalized = adapter.normalize(item)
    outcome = adapter.validate(normalized)

    assert outcome.is_valid is True
    assert normalized.event_type == "COMPETITION"
    assert normalized.has_cash_prizes is True
    assert normalized.prize_amount_usd_est == 12000.0
    assert normalized.organizer == "FAO & Zindi"
