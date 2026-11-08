from datetime import datetime, timezone
import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from app.modules.scraping.adapter_base import (
    CollectionMethod,
    DiscoverySeed,
    ExtractedItem,
    RateLimitPolicy,
    RawFetchArtifact,
    SourceAdapter,
    ValidationOutcome,
)
from app.modules.scraping.registry import register_adapter

logger = logging.getLogger("radar.events.devpost")


class NormalizedEvent(BaseModel):
    name: str
    organizer: Optional[str] = None
    description: str
    event_type: str = "HACKATHON"
    delivery_mode: str = "VIRTUAL"
    location_text: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    registration_url: str
    event_website: Optional[str] = None
    registration_deadline: Optional[datetime] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    prize_summary: Optional[str] = None
    has_cash_prizes: bool = False
    prize_amount_usd_est: Optional[float] = None
    is_free_participation: bool = True
    student_eligible: Optional[bool] = None
    international_eligible: Optional[bool] = None
    source_platform: str = "devpost"
    source_url: str
    themes: List[str] = []


@register_adapter("devpost_hackathons")
class DevpostHackathonsAdapter(SourceAdapter[NormalizedEvent]):
    """
    Discovers developer hackathons, challenges, and tech grants from Devpost.
    Zero API key required.
    """

    module_type = "EVENT"
    collection_method = CollectionMethod.OFFICIAL_API
    required_env_vars = ()

    async def discover(self, query_params: dict[str, Any]) -> AsyncIterator[DiscoverySeed]:
        base_endpoint = self.source_config.get(
            "endpoint", "https://devpost.com/api/hackathons?challenge_type[]=online&sort_by=Recently+Added"
        )
        # Yield first 2 pages by default
        max_pages = min(self.source_config.get("max_pages", 2), 5)
        for page in range(1, max_pages + 1):
            url = f"{base_endpoint}&page={page}" if "page=" not in base_endpoint else base_endpoint
            yield DiscoverySeed(
                url=url,
                method="GET",
                cursor_metadata={"page": page},
            )

    async def extract(self, artifact: RawFetchArtifact) -> Tuple[list[ExtractedItem], list[DiscoverySeed]]:
        if artifact.status_code != 200:
            logger.warning("Devpost API returned status %d for %s", artifact.status_code, artifact.final_url)
            return [], []

        try:
            payload = json.loads(artifact.body_text)
            hackathons = payload.get("hackathons", [])
        except json.JSONDecodeError as e:
            logger.error("Failed parsing Devpost JSON: %s", e)
            return [], []

        items: List[ExtractedItem] = []
        for h in hackathons:
            hid = str(h.get("id"))
            title = h.get("title")
            url = h.get("url")
            if not title or not url:
                continue

            item = ExtractedItem(
                external_id=f"devpost_{hid}",
                source_url=url,
                raw_data=h,
                discovered_at=datetime.now(timezone.utc),
            )
            items.append(item)

        return items, []

    def normalize(self, item: ExtractedItem) -> NormalizedEvent:
        raw = item.raw_data
        title = raw.get("title", "").strip()
        organizer = raw.get("organization_name") or raw.get("displayed_location", {}).get("location")
        url = raw.get("url", item.source_url)

        # Dates & deadlines
        deadline_dt = None
        submission_period = raw.get("submission_period_dates") or ""
        # Devpost sometimes provides direct ISO timestamps
        sub_ends_at = raw.get("submission_period_ends_at")
        if sub_ends_at:
            try:
                deadline_dt = datetime.fromisoformat(sub_ends_at.replace("Z", "+00:00"))
            except ValueError:
                pass

        # Delivery mode
        is_online = raw.get("online") or ("online" in str(raw.get("displayed_location", "")).lower())
        delivery_mode = "VIRTUAL" if is_online else "HYBRID"

        # Prize parsing
        prize_summary = None
        has_cash = False
        prize_usd = None
        prize_str = raw.get("prize_amount")
        if prize_str:
            prize_summary = f"{prize_str} in prizes"
            # Strip '$' and commas to convert to float
            clean_digits = "".join(c for c in prize_str if c.isdigit() or c == ".")
            if clean_digits:
                try:
                    prize_usd = float(clean_digits)
                    has_cash = prize_usd > 0
                except ValueError:
                    pass

        # Themes / tags
        themes = []
        themes_data = raw.get("themes", [])
        if isinstance(themes_data, list):
            for t in themes_data:
                if isinstance(t, dict) and "name" in t:
                    themes.append(t["name"])
                elif isinstance(t, str):
                    themes.append(t)

        description = raw.get("description") or f"Developer hackathon on Devpost: {title}. {submission_period}"

        return NormalizedEvent(
            name=title,
            organizer=organizer,
            description=description,
            event_type="HACKATHON",
            delivery_mode=delivery_mode,
            location_text=str(raw.get("displayed_location", {}).get("location", "Virtual / Worldwide")),
            registration_url=url,
            event_website=url,
            registration_deadline=deadline_dt,
            prize_summary=prize_summary,
            has_cash_prizes=has_cash,
            prize_amount_usd_est=prize_usd,
            is_free_participation=True,
            student_eligible=True,
            international_eligible=True,
            source_platform="devpost",
            source_url=item.source_url,
            themes=themes,
        )

    def validate(self, normalized: NormalizedEvent) -> ValidationOutcome[NormalizedEvent]:
        errors = []
        if not normalized.name or len(normalized.name) < 3:
            errors.append("Event name is empty or too short.")
        if not normalized.registration_url or not normalized.registration_url.startswith("http"):
            errors.append("Invalid registration URL.")

        return ValidationOutcome(
            is_valid=len(errors) == 0,
            record=normalized if len(errors) == 0 else None,
            errors=errors,
        )
