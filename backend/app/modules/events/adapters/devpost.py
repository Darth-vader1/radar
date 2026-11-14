import html
import json
import logging
import re
from datetime import datetime, time, timezone
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


_TAG_RE = re.compile(r"<[^>]+>")
_MONTH_DAY_YEAR = re.compile(r"^(?P<mon>[A-Za-z]{3,9})\s+(?P<day>\d{1,2})(?:,\s*(?P<year>\d{4}))?$")
_DAY_YEAR = re.compile(r"^(?P<day>\d{1,2})(?:,\s*(?P<year>\d{4}))?$")


def strip_html(value: Optional[str]) -> str:
    """Devpost embeds markup in some fields, e.g. '$<span data-currency-value>30,000</span>'."""
    return html.unescape(_TAG_RE.sub("", value or "")).strip()


def _date(mon: str, day: str, year: int) -> Optional[datetime]:
    for fmt in ("%b %d %Y", "%B %d %Y"):
        try:
            return datetime.strptime(f"{mon[:3] if fmt == '%b %d %Y' else mon} {day} {year}", fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_submission_period(text: Optional[str]) -> tuple[Optional[datetime], Optional[datetime]]:
    """
    Parses Devpost's human-readable submission period into (start, end) UTC datetimes.
    Handles "Oct 30 - Dec 04, 2026", "Nov 01 - 15, 2026" and "Dec 15, 2026 - Jan 10, 2027".
    The end is set to 23:59:59 UTC that day (Devpost doesn't publish the exact cut-off time).
    """
    if not text or " - " not in text:
        return None, None
    left, right = (part.strip() for part in text.split(" - ", 1))
    r = _MONTH_DAY_YEAR.match(right) or _DAY_YEAR.match(right)
    lm = _MONTH_DAY_YEAR.match(left)
    if not r or not lm or not (r.groupdict().get("year") or lm.group("year")):
        return None, None
    end_year = int(r.group("year") or lm.group("year"))
    end_mon = r.groupdict().get("mon") or lm.group("mon")
    end = _date(end_mon, r.group("day"), end_year)
    start_year = int(lm.group("year")) if lm.group("year") else end_year
    start = _date(lm.group("mon"), lm.group("day"), start_year)
    if start and end and start > end and not lm.group("year"):
        start = start.replace(year=start_year - 1)  # e.g. "Dec 15 - Jan 10, 2027"
    if end:
        end = datetime.combine(end.date(), time(23, 59, 59), tzinfo=timezone.utc)
    return start, end


def parse_prize(raw_prize: Optional[str]) -> tuple[Optional[str], bool, Optional[float]]:
    """Returns (summary, has_cash, usd_estimate). Only dollar amounts get a USD estimate."""
    text = strip_html(raw_prize)
    if not text:
        return None, False, None
    digits = re.sub(r"[^\d.]", "", text)
    try:
        amount = float(digits) if digits else 0.0
    except ValueError:
        amount = 0.0
    usd = amount if amount > 0 and "$" in text else None
    if amount <= 0 and not re.search(r"[A-Za-z]", text):
        return None, False, None  # a bare "$0" says nothing useful
    return (f"{text} in prizes" if amount > 0 else text), amount > 0, usd


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

        # Dates: the public API gives a readable period ("Oct 30 - Dec 04, 2026"), not timestamps.
        submission_period = raw.get("submission_period_dates") or ""
        start_dt, deadline_dt = parse_submission_period(submission_period)
        sub_ends_at = raw.get("submission_period_ends_at")  # present in some API variants
        if sub_ends_at:
            try:
                deadline_dt = datetime.fromisoformat(sub_ends_at.replace("Z", "+00:00"))
            except ValueError:
                pass

        # Delivery mode: Devpost marks online hackathons; everything else is in person.
        is_online = raw.get("online") or ("online" in str(raw.get("displayed_location", "")).lower())
        delivery_mode = "VIRTUAL" if is_online else "PHYSICAL"

        prize_summary, has_cash, prize_usd = parse_prize(raw.get("prize_amount"))

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
            # Devpost publishes the submission window; people can join until it closes, so the
            # deadline drives the status (open / closing soon / closed). Judging end is unknown.
            start_date=start_dt,
            end_date=None,
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
