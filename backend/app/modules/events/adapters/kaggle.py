import base64
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, AsyncIterator, List, Optional, Tuple

from app.core.config import get_credential
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

LIST_URL = "https://www.kaggle.com/api/v1/competitions/list"
PAGE_SIZE = 20
MAX_PAGES = 10


def competition_url(raw: dict[str, Any]) -> str:
    """The API now returns full URLs in `url`/`ref`; older responses gave a bare slug in `ref`."""
    for value in (raw.get("url"), raw.get("ref")):
        if isinstance(value, str) and value.startswith("http"):
            return value
    return f"https://www.kaggle.com/competitions/{raw.get('ref') or raw.get('id')}"


def parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


_MONEY = re.compile(r"([\d][\d,]*(?:\.\d+)?)")


def parse_reward(reward: Any) -> Tuple[Optional[str], Optional[float]]:
    """
    "400,000 Usd" -> ("$400,000", 400000.0). Non-cash rewards ("Knowledge", "Kudos", "Swag") and
    other currencies keep their text but get no USD estimate.
    """
    if not isinstance(reward, str) or not reward.strip():
        return None, None
    text = reward.strip()
    match = _MONEY.search(text)
    is_usd = "usd" in text.lower() or "$" in text
    if match and is_usd:
        amount = float(match.group(1).replace(",", ""))
        if amount > 0:
            return f"${amount:,.0f}", amount
    lowered = text.lower()
    if lowered == "knowledge":
        return "Practice competition (no prize)", None
    if lowered == "kudos":
        return "Kudos only (no prize)", None
    if "swag" in lowered:
        return "Merchandise prizes", None
    return text, None


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
        yield self._page_seed(1)

    @staticmethod
    def _auth_header() -> str:
        """New Kaggle API tokens (KGAT_...) use Bearer auth; legacy kaggle.json keys use Basic username:key."""
        key = get_credential("KAGGLE_KEY") or ""
        if key.startswith("KGAT_"):
            return f"Bearer {key}"
        username = get_credential("KAGGLE_USERNAME") or ""
        return "Basic " + base64.b64encode(f"{username}:{key}".encode()).decode()

    def _page_seed(self, page: int) -> DiscoverySeed:
        return DiscoverySeed(
            url=f"{LIST_URL}?page={page}",
            method="GET",
            headers={"Authorization": self._auth_header(), "Accept": "application/json"},
            cursor_metadata={"page": page},
        )

    async def extract(self, artifact: RawFetchArtifact) -> Tuple[list[ExtractedItem], list[DiscoverySeed]]:
        if artifact.status_code != 200:
            logger.warning("Kaggle API returned status %d for %s", artifact.status_code, artifact.final_url)
            return [], []

        try:
            competitions = json.loads(artifact.body_text)
        except json.JSONDecodeError as e:
            logger.error("Failed parsing Kaggle JSON: %s", e)
            return [], []
        if not isinstance(competitions, list):
            return [], []

        items: List[ExtractedItem] = []
        for c in competitions:
            if not isinstance(c, dict) or not c.get("title"):
                continue
            items.append(ExtractedItem(
                external_id=f"kaggle_{c.get('id') or c.get('ref')}",
                source_url=competition_url(c),
                raw_data=c,
                discovered_at=datetime.now(timezone.utc),
            ))

        # A full page means there may be more; the crawl budget caps how far this goes.
        next_seeds: list[DiscoverySeed] = []
        page = int(artifact.seed.cursor_metadata.get("page", 1)) if artifact.seed else 1
        if len(competitions) >= PAGE_SIZE and page < MAX_PAGES:
            next_seeds.append(self._page_seed(page + 1))
        return items, next_seeds

    def normalize(self, item: ExtractedItem) -> NormalizedEvent:
        raw = item.raw_data
        title = (raw.get("title") or "").strip()
        description = (raw.get("description") or "").strip() or f"Kaggle machine learning competition: {title}"
        url = competition_url(raw)
        # Teams must join before the entry deadline, which can be earlier than the final deadline.
        registration_deadline = parse_ts(raw.get("newEntrantDeadline")) or parse_ts(raw.get("deadline"))
        prize_summary, prize_usd = parse_reward(raw.get("reward"))

        category = (raw.get("category") or "").strip()
        themes = ["ai", "machine-learning", "data-science"]
        if category:
            themes.append(category.lower().replace(" ", "-"))

        return NormalizedEvent(
            name=title,
            organizer=raw.get("organizationName") or "Kaggle",
            description=description,
            event_type="COMPETITION",
            delivery_mode="VIRTUAL",
            location_text="Online (Worldwide)",
            registration_url=url,
            event_website="https://www.kaggle.com/competitions",
            registration_deadline=registration_deadline,
            end_date=parse_ts(raw.get("deadline")),
            prize_summary=prize_summary,
            has_cash_prizes=bool(prize_usd),
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
