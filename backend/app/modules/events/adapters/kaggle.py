from datetime import datetime, timezone
import json
import logging
import os
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

logger = logging.getLogger("radar.events.kaggle")


@register_adapter("kaggle_competitions")
class KaggleCompetitionsAdapter(SourceAdapter[NormalizedEvent]):
    """
    Kaggle Competitions official REST API adapter.
    Discovers AI/ML competitions, prizes, and deadlines.
    Requires KAGGLE_USERNAME and KAGGLE_KEY in environment.
    """

    module_type = "EVENT"
    collection_method = CollectionMethod.OFFICIAL_API
    required_env_vars = ("KAGGLE_USERNAME", "KAGGLE_KEY")

    async def discover(self, query_params: dict[str, Any]) -> AsyncIterator[DiscoverySeed]:
        username = os.environ.get("KAGGLE_USERNAME", "")
        key = os.environ.get("KAGGLE_KEY", "")

        import base64
        auth_header = base64.b64encode(f"{username}:{key}".encode()).decode()

        yield DiscoverySeed(
            url="https://www.kaggle.com/api/v1/competitions/list?page=1",
            method="GET",
            headers={
                "Authorization": f"Basic {auth_header}",
                "Accept": "application/json",
            },
            cursor_metadata={"page": 1},
        )

    async def extract(self, artifact: RawFetchArtifact) -> Tuple[list[ExtractedItem], list[DiscoverySeed]]:
        if artifact.status_code != 200:
            logger.warning("Kaggle API returned status %d for %s", artifact.status_code, artifact.final_url)
            return [], []

        try:
            competitions = json.loads(artifact.body_text)
            if not isinstance(competitions, list):
                competitions = []
        except json.JSONDecodeError as e:
            logger.error("Failed parsing Kaggle JSON: %s", e)
            return [], []

        items: List[ExtractedItem] = []
        for c in competitions:
            ref = c.get("ref")
            title = c.get("title")
            url = c.get("url") or f"https://www.kaggle.com/c/{ref}"
            if not title:
                continue

            item = ExtractedItem(
                external_id=f"kaggle_{ref or c.get('id')}",
                source_url=url,
                raw_data=c,
                discovered_at=datetime.now(timezone.utc),
            )
            items.append(item)

        return items, []

    def normalize(self, item: ExtractedItem) -> NormalizedEvent:
        raw = item.raw_data
        title = raw.get("title", "").strip()
        ref = raw.get("ref", "")
        description = raw.get("description") or f"Kaggle Machine Learning Challenge: {title}"

        # Deadline
        deadline_dt = None
        deadline_str = raw.get("deadline")
        if deadline_str:
            try:
                deadline_dt = datetime.fromisoformat(deadline_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        # Prize
        prize_usd = None
        has_cash = False
        reward_str = raw.get("reward")
        if reward_str:
            clean_digits = "".join(c for c in reward_str if c.isdigit() or c == ".")
            if clean_digits:
                try:
                    prize_usd = float(clean_digits)
                    has_cash = prize_usd > 0
                except ValueError:
                    pass

        category = raw.get("category", "")
        themes = ["ai", "machine-learning", "data-science"]
        if category:
            themes.append(category.lower())

        url = raw.get("url") or f"https://www.kaggle.com/c/{ref}"

        return NormalizedEvent(
            name=title,
            organizer=raw.get("organizationName") or "Kaggle",
            description=description,
            event_type="COMPETITION",
            delivery_mode="VIRTUAL",
            location_text="Online (Worldwide)",
            registration_url=url,
            event_website="https://www.kaggle.com",
            registration_deadline=deadline_dt,
            prize_summary=reward_str or (f"${prize_usd:,.0f} Prize Pool" if prize_usd else None),
            has_cash_prizes=has_cash,
            prize_amount_usd_est=prize_usd,
            is_free_participation=True,
            student_eligible=True,
            international_eligible=True,
            source_platform="kaggle",
            source_url=url,
            themes=themes,
        )

    def validate(self, normalized: NormalizedEvent) -> ValidationOutcome[NormalizedEvent]:
        errors = []
        if not normalized.name or len(normalized.name) < 3:
            errors.append("Kaggle competition title too short.")
        if not normalized.registration_url or not normalized.registration_url.startswith("http"):
            errors.append("Invalid Kaggle URL.")

        return ValidationOutcome(
            is_valid=len(errors) == 0,
            record=normalized if len(errors) == 0 else None,
            errors=errors,
        )
