import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator, List, Tuple

from app.modules.jobs.adapters.greenhouse import NormalizedJob
from app.modules.scraping.adapter_base import (
    CollectionMethod,
    DiscoverySeed,
    ExtractedItem,
    RawFetchArtifact,
    SourceAdapter,
    ValidationOutcome,
)
from app.modules.scraping.registry import register_adapter

logger = logging.getLogger("radar.jobs.remotive")


@register_adapter("remotive_jobs")
class RemotiveJobsAdapter(SourceAdapter[NormalizedJob]):
    """
    Discovers remote developer and tech vacancies from Remotive's official public API.
    Zero API key required.
    """

    module_type = "JOB"
    collection_method = CollectionMethod.OFFICIAL_API
    required_env_vars = ()

    async def discover(self, query_params: dict[str, Any]) -> AsyncIterator[DiscoverySeed]:
        category = query_params.get("category", "software-dev")
        yield DiscoverySeed(
            url=f"https://remotive.com/api/remote-jobs?category={category}&limit=50",
            method="GET",
        )

    async def extract(self, artifact: RawFetchArtifact) -> Tuple[list[ExtractedItem], list[DiscoverySeed]]:
        if artifact.status_code != 200:
            logger.warning("Remotive API returned status %d", artifact.status_code)
            return [], []

        try:
            payload = json.loads(artifact.body_text)
            jobs = payload.get("jobs", [])
        except json.JSONDecodeError as exc:
            logger.error("Failed parsing Remotive JSON: %s", exc)
            return [], []

        items: List[ExtractedItem] = []
        for j in jobs:
            job_id = str(j.get("id"))
            title = j.get("title")
            if not title:
                continue

            item = ExtractedItem(
                external_id=f"remotive_{job_id}",
                source_url=j.get("url", f"https://remotive.com/remote-jobs/{job_id}"),
                raw_data=j,
                discovered_at=datetime.now(timezone.utc),
            )
            items.append(item)

        return items, []

    def normalize(self, item: ExtractedItem) -> NormalizedJob:
        raw = item.raw_data
        company_name = raw.get("company_name", "Remote Tech Co")
        title = raw.get("title", "").strip()
        location_text = raw.get("candidate_required_location", "Worldwide Remote")
        desc = raw.get("description", "")

        pub_dt = None
        pub_str = raw.get("publication_date")
        if pub_str:
            try:
                pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            except Exception:
                pass

        return NormalizedJob(
            title=title,
            company_name=company_name,
            company_website=raw.get("company_url"),
            description=desc,
            location_text=location_text,
            country="Worldwide Remote",
            application_url=raw.get("url", item.source_url),
            published_at=pub_dt,
        )

    def validate(self, normalized: NormalizedJob) -> ValidationOutcome[NormalizedJob]:
        errors = []
        if not normalized.title:
            errors.append("Job title is required.")
        if not normalized.company_name:
            errors.append("Company name is required.")
        return ValidationOutcome(
            is_valid=len(errors) == 0,
            record=normalized,
            errors=errors,
        )
