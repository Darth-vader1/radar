"""
Idempotent reference-data seed: permissions, roles and the default discovery sources.

    python -m app.cli seed

Deliberately does NOT create or modify users (create admins with `python -m app.cli
create-admin`) and does NOT insert sample/demo records: everything shown to users must
come from a real source.
"""
import logging
import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import Permission, Role, RolePermission
from app.models.source import ConfigStatus, Source

logger = logging.getLogger("radar.seed")

PERMISSIONS = [
    ("sources:manage", "Create, edit, toggle, and configure discovery sources"),
    ("tasks:control", "Trigger, pause, resume, cancel discovery tasks"),
    ("records:export", "Export records to CSV, Excel, and JSON"),
    ("scoring:configure", "Modify lead scoring rules and weights"),
    ("users:manage", "Manage system users, roles, and permissions"),
]

ROLES = [
    ("super_admin", "Full unrestricted administrative access to entire platform", [p for p, _ in PERMISSIONS]),
    ("admin", "Administrative operations excluding super-admin user elevation",
     ["sources:manage", "tasks:control", "records:export", "scoring:configure"]),
    ("researcher", "Discovery triggers, record review, and exports", ["tasks:control", "records:export"]),
    ("standard_user", "Search, read, and bookmark records", []),
]


def _status_for(required_env_vars: list[str]) -> str:
    missing = [v for v in required_env_vars if not os.environ.get(v)]
    return ConfigStatus.AWAITING_CONFIGURATION.value if missing else ConfigStatus.READY.value


def default_sources() -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = [
        dict(
            slug="osm_overpass_businesses", name="OpenStreetMap Overpass POI Directory", module_type="BUSINESS",
            source_category="open_map_api", base_url="https://overpass-api.de/api/interpreter",
            adapter_key="osm_overpass", requires_credentials=False, required_env_vars=[],
            rate_limit_rpm=20, crawl_budget_pages=50,
            adapter_config={
                "default_countries": ["Nigeria", "Ghana", "Kenya"],
                "default_cities": ["Lagos", "Abuja", "Ikeja", "Port Harcourt"],
                "amenities": ["restaurant", "cafe", "fast_food", "pharmacy", "hospital", "bank"],
            },
        ),
        dict(
            slug="google_places_api", name="Google Places API (New)", module_type="BUSINESS",
            source_category="places_api", base_url="https://places.googleapis.com/v1/places:searchText",
            adapter_key="google_places_api", requires_credentials=True, required_env_vars=["GOOGLE_PLACES_API_KEY"],
            rate_limit_rpm=60, crawl_budget_pages=100, adapter_config={},
        ),
        dict(
            slug="greenhouse_tech_boards", name="Greenhouse Public Job Boards (Nigeria & Remote Tech)",
            module_type="JOB", source_category="ats_api", base_url="https://boards-api.greenhouse.io/v1/boards",
            adapter_key="greenhouse_boards", requires_credentials=False, required_env_vars=[],
            rate_limit_rpm=30, crawl_budget_pages=200,
            adapter_config={"board_tokens": ["paystack", "moniepoint", "andela", "wave", "gitlab", "cloudflare"]},
        ),
        dict(
            slug="remotive_tech_jobs", name="Remotive Remote Developer Jobs", module_type="JOB",
            source_category="job_board_api", base_url="https://remotive.com/api/remote-jobs",
            adapter_key="remotive_jobs", requires_credentials=False, required_env_vars=[],
            rate_limit_rpm=20, crawl_budget_pages=50,
            adapter_config={"categories": ["software-dev", "data", "devops", "qa"]},
        ),
        dict(
            slug="devpost_hackathons", name="Devpost Developer Hackathons & Grants", module_type="EVENT",
            source_category="hackathon_platform", base_url="https://devpost.com/api/hackathons",
            adapter_key="devpost_hackathons", requires_credentials=False, required_env_vars=[],
            rate_limit_rpm=20, crawl_budget_pages=50, adapter_config={},
        ),
        dict(
            slug="zindi_africa_competitions", name="Zindi Africa AI & Data Competitions", module_type="EVENT",
            source_category="hackathon_platform", base_url="https://zindi.africa/api/v1/competitions",
            adapter_key="zindi_competitions", requires_credentials=False, required_env_vars=[],
            rate_limit_rpm=20, crawl_budget_pages=50, adapter_config={},
        ),
        dict(
            slug="kaggle_competitions", name="Kaggle Competitions & Machine Learning Challenges", module_type="EVENT",
            source_category="hackathon_platform", base_url="https://www.kaggle.com/api/v1/competitions/list",
            adapter_key="kaggle_competitions", requires_credentials=True,
            required_env_vars=["KAGGLE_USERNAME", "KAGGLE_KEY"],
            rate_limit_rpm=20, crawl_budget_pages=50, adapter_config={},
        ),
        dict(
            slug="mlh_events", name="Major League Hacking (MLH) Global Hackathons", module_type="EVENT",
            source_category="hackathon_platform", base_url="https://mlh.io/api/v2/events",
            adapter_key="mlh_events", requires_credentials=False, required_env_vars=[],
            rate_limit_rpm=20, crawl_budget_pages=50, adapter_config={},
        ),
    ]
    for s in sources:
        s["collection_method"] = "OFFICIAL_API"
        s["config_status"] = _status_for(s["required_env_vars"])
    return sources


async def seed_reference_data(db: AsyncSession) -> dict[str, int]:
    """Creates anything missing; never overwrites existing rows. Returns counts of rows added."""
    added = {"permissions": 0, "roles": 0, "role_permissions": 0, "sources": 0}

    perms: dict[str, Permission] = {}
    for code, desc in PERMISSIONS:
        perm = await db.scalar(select(Permission).where(Permission.code == code))
        if perm is None:
            perm = Permission(code=code, description=desc)
            db.add(perm)
            await db.flush()
            added["permissions"] += 1
        perms[code] = perm

    for name, desc, codes in ROLES:
        role = await db.scalar(select(Role).where(Role.name == name))
        if role is None:
            role = Role(name=name, description=desc)
            db.add(role)
            await db.flush()
            added["roles"] += 1
        for code in codes:
            exists = await db.scalar(select(RolePermission).where(
                RolePermission.role_id == role.id, RolePermission.permission_id == perms[code].id
            ))
            if exists is None:
                db.add(RolePermission(role_id=role.id, permission_id=perms[code].id))
                added["role_permissions"] += 1

    for data in default_sources():
        if await db.scalar(select(Source).where(Source.slug == data["slug"])) is None:
            db.add(Source(**data))
            added["sources"] += 1

    await db.commit()
    logger.info("Seed complete: %s", added)
    return added
