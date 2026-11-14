import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, AsyncIterator, List, Optional, Tuple

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

MLH_BASE = "https://www.mlh.com"

# MLH has no public events API. The season events page is server-rendered with Inertia,
# which embeds the page's data as JSON in <script data-page="app" type="application/json">.
# Reading that JSON is far more robust than scraping the HTML layout.
_PAGE_DATA_RE = re.compile(r'<script[^>]*\bdata-page="app"[^>]*>(.*?)</script>', re.S)

_FORMAT_TO_DELIVERY = {"physical": "PHYSICAL", "digital": "VIRTUAL", "hybrid": "HYBRID"}


def current_season(now: Optional[datetime] = None) -> int:
    """MLH seasons are named by the year they end and start around August."""
    now = now or datetime.now(timezone.utc)
    return now.year + 1 if now.month >= 8 else now.year


def _parse_time(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@register_adapter("mlh_events")
class MLHEventsAdapter(SourceAdapter[NormalizedEvent]):
    """
    Upcoming student hackathons from Major League Hacking (MLH), read from the public
    season events page (www.mlh.com/seasons/<year>/events, allowed by robots.txt).
    """

    module_type = "EVENT"
    collection_method = CollectionMethod.STRUCTURED_DATA
    required_env_vars = ()

    async def discover(self, query_params: dict[str, Any]) -> AsyncIterator[DiscoverySeed]:
        season = self.source_config.get("season") or current_season()
        yield DiscoverySeed(
            url=f"{MLH_BASE}/seasons/{season}/events",
            method="GET",
            headers={"Accept": "text/html"},
            cursor_metadata={"season": str(season)},
        )

    async def extract(self, artifact: RawFetchArtifact) -> Tuple[list[ExtractedItem], list[DiscoverySeed]]:
        if artifact.status_code != 200:
            logger.warning("MLH events page returned status %d for %s", artifact.status_code, artifact.final_url)
            return [], []

        match = _PAGE_DATA_RE.search(artifact.body_text)
        if not match:
            # Layout changed: fail loudly (dead-lettered as an extract error) rather than silently.
            raise ValueError("MLH events page no longer embeds Inertia page data (data-page='app').")
        props = json.loads(match.group(1)).get("props", {})
        events = props.get("upcomingEvents")
        if not isinstance(events, list):
            raise ValueError("MLH page data has no 'upcomingEvents' list.")

        items: List[ExtractedItem] = []
        for e in events:
            slug, name = e.get("slug"), e.get("name")
            if not slug or not name:
                continue
            items.append(
                ExtractedItem(
                    external_id=f"mlh_{e.get('id') or slug}",
                    source_url=f"{MLH_BASE}/events/{slug}",
                    raw_data=e,
                    discovered_at=datetime.now(timezone.utc),
                )
            )
        return items, []

    def normalize(self, item: ExtractedItem) -> NormalizedEvent:
        raw = item.raw_data
        name = (raw.get("name") or "").strip()
        venue = raw.get("venueAddress") or {}
        delivery = _FORMAT_TO_DELIVERY.get(str(raw.get("formatType", "")).lower(), "UNSPECIFIED")
        location = raw.get("location") or ("Online" if delivery == "VIRTUAL" else None)
        focus = (raw.get("customFields") or {}).get("hackathon_focus") or []
        starts = _parse_time(raw.get("startsAt"))

        return NormalizedEvent(
            name=name,
            organizer=raw.get("organizationName") or "Major League Hacking (MLH)",
            description=(
                f"MLH member hackathon: {name}"
                + (f", {raw.get('dateRange')}" if raw.get("dateRange") else "")
                + (f", {location}" if location else "")
                + "."
            ),
            event_type="HACKATHON",
            delivery_mode=delivery,
            location_text=location,
            city=venue.get("city"),
            country=venue.get("country"),
            # The event's own site is where people register; fall back to its MLH page.
            registration_url=raw.get("websiteUrl") or item.source_url,
            event_website=raw.get("websiteUrl"),
            # MLH doesn't publish registration deadlines; registration closes when the event starts.
            registration_deadline=starts,
            start_date=starts,
            end_date=_parse_time(raw.get("endsAt")),
            is_free_participation=True,
            student_eligible=True,
            international_eligible=delivery == "VIRTUAL",
            source_platform="mlh",
            source_url=item.source_url,
            themes=["hackathon", *[str(f).lower() for f in focus]],
        )

    def validate(self, normalized: NormalizedEvent) -> ValidationOutcome[NormalizedEvent]:
        errors = []
        if not normalized.name or len(normalized.name) < 3:
            errors.append("Event name is empty or too short.")
        if not normalized.registration_url.startswith("http"):
            errors.append("Invalid registration URL.")
        if normalized.start_date is None:
            errors.append("Event has no start date.")
        return ValidationOutcome(
            is_valid=not errors,
            record=normalized if not errors else None,
            errors=errors,
        )
