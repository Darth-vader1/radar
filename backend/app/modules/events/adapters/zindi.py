from datetime import datetime, timezone
import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
from pydantic import BaseModel

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

logger = logging.getLogger("radar.events.zindi")


@register_adapter("zindi_competitions")
class ZindiCompetitionsAdapter(SourceAdapter[NormalizedEvent]):
    """
    Discovers AI and Data Science competitions and hackathons from Zindi Africa.
    Features pan-African and global AI challenges with explicit USD prize pools.
    Zero API key required for public listing endpoint.
    """

    module_type = "EVENT"
    collection_method = CollectionMethod.OFFICIAL_API
    required_env_vars = ()

    async def discover(self, query_params: dict[str, Any]) -> AsyncIterator[DiscoverySeed]:
        endpoint = self.source_config.get(
            "endpoint", "https://zindi.africa/api/v1/competitions?active=true"
        )
        yield DiscoverySeed(
            url=endpoint,
            method="GET",
            cursor_metadata={"source": "zindi_africa"},
        )

    async def extract(self, artifact: RawFetchArtifact) -> Tuple[list[ExtractedItem], list[DiscoverySeed]]:
        if artifact.status_code != 200:
            logger.warning("Zindi API returned status %d for %s", artifact.status_code, artifact.final_url)
            return [], []

        try:
            payload = json.loads(artifact.body_text)
            competitions = payload if isinstance(payload, list) else payload.get("data", payload.get("competitions", []))
        except json.JSONDecodeError as e:
            logger.error("Failed parsing Zindi JSON: %s", e)
            return [], []

        items: List[ExtractedItem] = []
        for c in competitions:
            cid = str(c.get("id") or c.get("slug"))
            title = c.get("title") or c.get("name")
            slug = c.get("slug", cid)
            if not title:
                continue

            event_url = f"https://zindi.africa/competitions/{slug}"
            item = ExtractedItem(
                external_id=f"zindi_{cid}",
                source_url=event_url,
                raw_data=c,
                discovered_at=datetime.now(timezone.utc),
            )
            items.append(item)

        return items, []

    def normalize(self, item: ExtractedItem) -> NormalizedEvent:
        raw = item.raw_data
        title = raw.get("title") or raw.get("name", "").strip()
        slug = raw.get("slug", "")
        description = raw.get("subtitle") or raw.get("description") or f"Zindi Africa machine learning competition: {title}"
        organizer = raw.get("host") or raw.get("organization") or "Zindi Africa"

        # Dates
        deadline_dt = None
        end_date_str = raw.get("end_date") or raw.get("deadline")
        if end_date_str:
            try:
                deadline_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        start_dt = None
        start_date_str = raw.get("start_date")
        if start_date_str:
            try:
                start_dt = datetime.fromisoformat(start_date_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        # Prize
        prize_usd = None
        has_cash = False
        prize_str = None
        raw_reward = raw.get("reward") or raw.get("prize") or raw.get("prize_amount")
        if raw_reward:
            prize_str = str(raw_reward)
            clean_digits = "".join(c for c in prize_str if c.isdigit() or c == ".")
            if clean_digits:
                try:
                    prize_usd = float(clean_digits)
                    has_cash = prize_usd > 0
                except ValueError:
                    pass

        themes = ["ai", "machine-learning", "data-science"]
        tags_raw = raw.get("tags", [])
        if isinstance(tags_raw, list):
            themes.extend([str(t).lower() for t in tags_raw])

        return NormalizedEvent(
            name=title,
            organizer=organizer,
            description=description,
            event_type="COMPETITION",
            delivery_mode="VIRTUAL",
            location_text="Online (Pan-Africa & Global)",
            registration_url=f"https://zindi.africa/competitions/{slug}",
            event_website="https://zindi.africa",
            registration_deadline=deadline_dt,
            start_date=start_dt,
            end_date=deadline_dt,
            prize_summary=f"${prize_usd:,.0f} USD Prize Pool" if prize_usd else prize_str,
            has_cash_prizes=has_cash,
            prize_amount_usd_est=prize_usd,
            is_free_participation=True,
            student_eligible=True,
            international_eligible=True,
            source_platform="zindi_africa",
            source_url=item.source_url,
            themes=themes,
        )

    def validate(self, normalized: NormalizedEvent) -> ValidationOutcome[NormalizedEvent]:
        errors = []
        if not normalized.name or len(normalized.name) < 3:
            errors.append("Competition title is empty or too short.")
        if not normalized.registration_url or not normalized.registration_url.startswith("http"):
            errors.append("Invalid registration URL.")

        return ValidationOutcome(
            is_valid=len(errors) == 0,
            record=normalized if len(errors) == 0 else None,
            errors=errors,
        )
