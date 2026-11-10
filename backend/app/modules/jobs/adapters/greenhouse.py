import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator, List, Optional, Tuple

from pydantic import BaseModel

from app.modules.scraping.adapter_base import (
    CollectionMethod,
    DiscoverySeed,
    ExtractedItem,
    RawFetchArtifact,
    SourceAdapter,
    ValidationOutcome,
)
from app.modules.scraping.registry import register_adapter

logger = logging.getLogger("radar.jobs.greenhouse")


class NormalizedJob(BaseModel):
    title: str
    company_name: str
    company_website: Optional[str] = None
    description: str
    location_text: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    application_url: str
    published_at: Optional[datetime] = None


@register_adapter("greenhouse_boards")
class GreenhouseBoardsAdapter(SourceAdapter[NormalizedJob]):
    """
    Discovers tech vacancies from public Greenhouse Job Board endpoints.
    Used by leading Nigerian & African fintechs (Paystack, Moniepoint, Wave)
    as well as top remote engineering organizations (GitLab, Cloudflare, Andela).
    Zero API key required.
    """

    module_type = "JOB"
    collection_method = CollectionMethod.OFFICIAL_API
    required_env_vars = ()

    DEFAULT_BOARD_TOKENS = [
        "paystack", "moniepoint", "andela", "wave", "gitlab", "cloudflare"
    ]

    async def discover(self, query_params: dict[str, Any]) -> AsyncIterator[DiscoverySeed]:
        board_tokens = self.source_config.get("board_tokens") or self.DEFAULT_BOARD_TOKENS

        for token in board_tokens:
            yield DiscoverySeed(
                url=f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true",
                method="GET",
                cursor_metadata={"company_token": token},
            )

    async def extract(self, artifact: RawFetchArtifact) -> Tuple[list[ExtractedItem], list[DiscoverySeed]]:
        if artifact.status_code != 200:
            logger.warning("Greenhouse API returned status %d for %s", artifact.status_code, artifact.final_url)
            return [], []

        try:
            payload = json.loads(artifact.body_text)
            jobs = payload.get("jobs", [])
        except json.JSONDecodeError as e:
            logger.error("Failed parsing Greenhouse JSON: %s", e)
            return [], []

        company_token = artifact.seed.cursor_metadata.get("company_token", "Tech Company")
        company_name = company_token.capitalize()

        items: List[ExtractedItem] = []
        for j in jobs:
            job_id = str(j.get("id"))
            title = j.get("title")
            if not title:
                continue

            item = ExtractedItem(
                external_id=f"greenhouse_{company_token}_{job_id}",
                source_url=j.get("absolute_url", f"https://boards.greenhouse.io/{company_token}/jobs/{job_id}"),
                raw_data={
                    **j,
                    "company_name": company_name,
                    "company_token": company_token,
                },
                discovered_at=datetime.now(timezone.utc),
            )
            items.append(item)

        return items, []

    def normalize(self, item: ExtractedItem) -> NormalizedJob:
        raw = item.raw_data
        company_name = raw.get("company_name", "Tech Employer")
        title = raw.get("title", "").strip()
        location_obj = raw.get("location", {})
        location_name = location_obj.get("name") if isinstance(location_obj, dict) else str(location_obj or "")

        # HTML body description
        desc_html = raw.get("content", "")

        city = None
        country = None
        if location_name:
            if "lagos" in location_name.lower() or "nigeria" in location_name.lower():
                country = "Nigeria"
                if "lagos" in location_name.lower():
                    city = "Lagos"
            elif "remote" in location_name.lower():
                country = "Remote"

        updated_at_str = raw.get("updated_at")
        pub_dt = None
        if updated_at_str:
            try:
                pub_dt = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
            except Exception:
                pass

        return NormalizedJob(
            title=title,
            company_name=company_name,
            company_website=f"https://boards.greenhouse.io/{raw.get('company_token')}",
            description=desc_html,
            location_text=location_name or "Remote / Unspecified",
            city=city,
            country=country or "Worldwide",
            application_url=item.source_url,
            published_at=pub_dt,
        )

    def validate(self, normalized: NormalizedJob) -> ValidationOutcome[NormalizedJob]:
        errors = []
        if not normalized.title:
            errors.append("Job title is required.")
        if not normalized.company_name:
            errors.append("Company name is required.")
        if not normalized.application_url:
            errors.append("Application URL is required.")

        return ValidationOutcome(
            is_valid=len(errors) == 0,
            record=normalized,
            errors=errors,
        )
