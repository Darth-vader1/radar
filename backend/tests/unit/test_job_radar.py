from app.models.job import JobCategory
from app.modules.jobs.adapters.greenhouse import GreenhouseBoardsAdapter
from app.modules.jobs.services.job_service import normalize_company, normalize_title
from app.modules.jobs.services.skill_extractor import (
    classify_category,
    extract_experience_level,
    extract_remote_status,
    extract_skills_from_text,
)
from app.modules.scraping.adapter_base import ExtractedItem, RateLimitPolicy


def test_job_normalization_helpers():
    # Title cleaning
    assert normalize_title("Senior Backend Engineer (Remote) - Lagos") == "senior backend engineer"
    assert normalize_title("Staff DevOps Architect [EMEA/Africa]") == "staff devops architect"

    # Company name cleaning
    assert normalize_company("Paystack Payments Limited") == "paystack"
    assert normalize_company("Moniepoint Inc.") == "moniepoint"


def test_tech_skills_extraction():
    job_text = """
    We are looking for a Senior Backend Engineer proficient in Python (FastAPI/Django),
    PostgreSQL, and Redis. Experience with Docker, Kubernetes, and AWS (ECS/EKS) is essential.
    Familiarity with React or TypeScript is a strong plus.
    """
    skills = extract_skills_from_text(job_text)

    expected = {"Python", "FastAPI", "Django", "PostgreSQL", "Redis", "Docker", "Kubernetes", "AWS", "React", "TypeScript"}
    for exp in expected:
        assert exp in skills


def test_category_and_seniority_classification():
    # Category
    assert classify_category("Lead Frontend React Engineer") == JobCategory.FRONTEND.value
    assert classify_category("Python Backend Developer (FastAPI)") == JobCategory.BACKEND.value
    assert classify_category("Site Reliability Engineer (DevOps)") == JobCategory.DEVOPS.value
    assert classify_category("Senior AI/ML Research Engineer") == JobCategory.AI_ML.value

    # Seniority
    assert extract_experience_level("Software Engineering Intern (Summer 2026)") == "INTERN"
    assert extract_experience_level("Junior Associate QA Engineer") == "ENTRY"
    assert extract_experience_level("Senior Cloud Infrastructure Architect") in ("SENIOR", "STAFF_PRINCIPAL")

    # Remote
    assert extract_remote_status("Lagos, Nigeria (Hybrid)") == "HYBRID"
    assert extract_remote_status("Remote - Worldwide") == "REMOTE"


def test_greenhouse_adapter_normalization():
    adapter = GreenhouseBoardsAdapter(source_config={}, rate_policy=RateLimitPolicy())

    item = ExtractedItem(
        external_id="greenhouse_paystack_4901",
        source_url="https://boards.greenhouse.io/paystack/jobs/4901",
        raw_data={
            "id": 4901,
            "title": "Senior Backend Engineer - Core Payments",
            "company_name": "Paystack",
            "company_token": "paystack",
            "content": "<p>Build high-scale fintech systems handling millions of daily transactions.</p>",
            "location": {"name": "Lagos, Nigeria"},
        },
        discovered_at=None,
    )

    normalized = adapter.normalize(item)
    assert normalized.title == "Senior Backend Engineer - Core Payments"
    assert normalized.company_name == "Paystack"
    assert normalized.country == "Nigeria"
    assert normalized.city == "Lagos"

    val_res = adapter.validate(normalized)
    assert val_res.is_valid is True
