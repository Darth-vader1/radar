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

logger = logging.getLogger("radar.events.zindi")

# Zindi's public API (moved from api.zindi.africa to api.zindi.world). `status=open` returns
# only competitions currently accepting entries; without it the list is ~500 past ones.
DEFAULT_ENDPOINT = "https://api.zindi.world/v1/competitions?status=open&per_page=50&page=0"


def _parse_time(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_usd_reward(reward: Any, reward_type: Any) -> Optional[float]:
    """
    Cash value in USD, or None. Zindi rewards look like "$40 000 USD", but also
    "Awards at PyCon Somalia" (reward_type "points") or other currencies: only cash prizes
    explicitly in USD are converted, so non-USD amounts are never mislabelled as dollars.
    """
    if reward_type != "prize" or not isinstance(reward, str):
        return None
    if "USD" not in reward.upper() and "$" not in reward:
        return None
    digits = re.sub(r"[^\d.]", "", reward)
    try:
        value = float(digits) if digits else None
    except ValueError:
        return None
    return value if value and value > 0 else None


@register_adapter("zindi_competitions")
class ZindiCompetitionsAdapter(SourceAdapter[NormalizedEvent]):
    """
    Open AI / data science competitions from Zindi (Africa's largest data science community),
    via its public JSON API. No API key required.
    """

    module_type = "EVENT"
    collection_method = CollectionMethod.OFFICIAL_API
    required_env_vars = ()

    async def discover(self, query_params: dict[str, Any]) -> AsyncIterator[DiscoverySeed]:
        yield DiscoverySeed(
            url=self.source_config.get("endpoint") or DEFAULT_ENDPOINT,
            method="GET",
            headers={"Accept": "application/json"},
            cursor_metadata={"source": "zindi"},
        )

    async def extract(self, artifact: RawFetchArtifact) -> Tuple[list[ExtractedItem], list[DiscoverySeed]]:
        if artifact.status_code != 200:
            logger.warning("Zindi API returned status %d for %s", artifact.status_code, artifact.final_url)
            return [], []
        try:
            payload = json.loads(artifact.body_text)
        except json.JSONDecodeError as e:
            logger.error("Zindi returned non-JSON from %s: %s", artifact.final_url, e)
            return [], []

        competitions = payload if isinstance(payload, list) else payload.get("data", [])
        items: List[ExtractedItem] = []
        for c in competitions:
            # The API's `id` is the competition's URL slug, e.g. "GenAI-for-Good-Challenge".
            comp_id = c.get("id") or c.get("slug")
            if not comp_id or not c.get("title"):
                continue
            if c.get("open") is False:  # endpoint override without status=open
                continue
            if c.get("is_access_restricted") or c.get("secret_code_required"):
                continue  # private competitions: not joinable by the public
            items.append(
                ExtractedItem(
                    external_id=f"zindi_{comp_id}",
                    source_url=f"https://zindi.africa/competitions/{comp_id}",
                    raw_data=c,
                    discovered_at=datetime.now(timezone.utc),
                )
            )
        return items, []

    def normalize(self, item: ExtractedItem) -> NormalizedEvent:
        raw = item.raw_data
        title = (raw.get("title") or raw.get("name") or "").strip()
        reward = raw.get("reward")
        prize_usd = parse_usd_reward(reward, raw.get("reward_type"))
        end_time = _parse_time(raw.get("end_time"))
        # Entries may close before the competition ends; fall back to the end time.
        deadline = _parse_time(raw.get("entries_close_at")) or end_time

        themes = ["ai", "machine-learning", "data-science"]
        if raw.get("is_beginner_friendly"):
            themes.append("beginner-friendly")

        organization = raw.get("organization")
        return NormalizedEvent(
            name=title,
            organizer=organization or "Zindi",
            description=(
                f"Zindi data science competition: {title}."
                + (f" Hosted by {organization}." if organization else "")
                + (f" Reward: {reward}." if reward else "")
            ),
            event_type="COMPETITION",
            delivery_mode="VIRTUAL",
            location_text="Online",
            registration_url=item.source_url,
            event_website="https://zindi.africa",
            registration_deadline=deadline,
            start_date=_parse_time(raw.get("start_time")),
            end_date=end_time,
            prize_summary=str(reward) if reward else None,
            has_cash_prizes=prize_usd is not None,
            prize_amount_usd_est=prize_usd,
            is_free_participation=True,
            student_eligible=True,
            international_eligible=True,
            source_platform="zindi",
            source_url=item.source_url,
            themes=themes,
        )

    def validate(self, normalized: NormalizedEvent) -> ValidationOutcome[NormalizedEvent]:
        errors = []
        if not normalized.name or len(normalized.name) < 3:
            errors.append("Competition title is empty or too short.")
        if not normalized.registration_url.startswith("https://zindi.africa/competitions/") or \
                normalized.registration_url.rstrip("/").endswith("/competitions"):
            errors.append("Registration URL does not point at a specific competition.")
        return ValidationOutcome(
            is_valid=not errors,
            record=normalized if not errors else None,
            errors=errors,
        )
