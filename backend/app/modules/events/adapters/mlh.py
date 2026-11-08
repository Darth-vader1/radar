from datetime import datetime, timezone
import json
import logging
import re
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from app.modules.events.adapters.devpost import NormalizedEvent
from app.modules.scraping.adapter_base import (
    CollectionMethod,
    DiscoverySeed,
    ExtractedItem,
    RawFetchArtifact,
    SourceAdapter,
    ValidationOutcome,
)
from app.modules.scraping.registry import register_adapter

logger = logging.getLogger("radar.events.mlh")


@register_adapter("mlh_events")
class MLHEventsAdapter(SourceAdapter[NormalizedEvent]):
    """
    Discovers student and developer hackathons from Major League Hacking (MLH).
    Features student eligibility, hardware labs, and digital/physical badges.
    Zero API key required.
    """

    module_type = "EVENT"
    collection_method = CollectionMethod.OFFICIAL_API
    required_env_vars = ()

    async def discover(self, query_params: dict[str, Any]) -> AsyncIterator[DiscoverySeed]:
        # MLH provides a public seasons JSON/API
        endpoint = self.source_config.get(
            "endpoint", "https://mlh.io/api/v2/events"
        )
        yield DiscoverySeed(
            url=endpoint,
            method="GET",
            cursor_metadata={"season": "2026"},
        )

    async def extract(self, artifact: RawFetchArtifact) -> Tuple[list[ExtractedItem], list[DiscoverySeed]]:
        if artifact.status_code != 200:
            logger.warning("MLH API returned status %d for %s", artifact.status_code, artifact.final_url)
            return [], []

        try:
            payload = json.loads(artifact.body_text)
            events = payload if isinstance(payload, list) else payload.get("events", payload.get("data", []))
        except json.JSONDecodeError as e:
            logger.error("Failed parsing MLH JSON: %s", e)
            return [], []

        items: List[ExtractedItem] = []
        for ev in events:
            name = ev.get("name") or ev.get("title")
            url = ev.get("url") or ev.get("website")
            if not name or not url:
                continue

            eid = str(ev.get("id") or name.lower().replace(" ", "_"))
            item = ExtractedItem(
                external_id=f"mlh_{eid}",
                source_url=url,
                raw_data=ev,
                discovered_at=datetime.now(timezone.utc),
            )
            items.append(item)

        return items, []

    def normalize(self, item: ExtractedItem) -> NormalizedEvent:
        raw = item.raw_data
        name = raw.get("name") or raw.get("title", "").strip()
        url = raw.get("url") or raw.get("website", item.source_url)
        location = raw.get("location", "Everywhere (Digital)")
        is_digital = "digital" in str(location).lower() or "virtual" in str(location).lower()

        # Dates
        start_dt = None
        end_dt = None
        start_str = raw.get("start_date") or raw.get("startDate")
        if start_str:
            try:
                start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        end_str = raw.get("end_date") or raw.get("endDate")
        if end_str:
            try:
                end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        return NormalizedEvent(
            name=name,
            organizer=raw.get("organizer") or "MLH Member Hackathon",
            description=f"Official MLH hackathon: {name}. Location: {location}.",
            event_type="HACKATHON",
            delivery_mode="VIRTUAL" if is_digital else "PHYSICAL",
            location_text=location,
            registration_url=url,
            event_website=url,
            registration_deadline=start_dt,  # MLH registration generally closes at start
            start_date=start_dt,
            end_date=end_dt,
            prize_summary="MLH Winner Medals, Swag, and Category Prizes",
            has_cash_prizes=False,
            is_free_participation=True,
            student_eligible=True,
            international_eligible=True,
            source_platform="mlh",
            source_url=url,
            themes=["web-dev", "mobile-dev", "ai", "robotics"],
        )

    def validate(self, normalized: NormalizedEvent) -> ValidationOutcome[NormalizedEvent]:
        errors = []
        if not normalized.name or len(normalized.name) < 3:
            errors.append("MLH event name is empty.")
        if not normalized.registration_url or not normalized.registration_url.startswith("http"):
            errors.append("Invalid MLH registration URL.")

        return ValidationOutcome(
            is_valid=len(errors) == 0,
            record=normalized if len(errors) == 0 else None,
            errors=errors,
        )
