import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business import Business, LeadScoringRule, WebsiteStatus

logger = logging.getLogger("radar.businesses.lead_scorer")

DEFAULT_SCORING_WEIGHTS: Dict[str, Dict[str, Any]] = {
    "no_website_found": {"points": 30, "label": "No website found"},
    "website_broken": {"points": 25, "label": "Website unreachable or broken"},
    "no_online_ordering": {"points": 20, "label": "No online ordering system detected"},
    "active_social_media": {"points": 15, "label": "Active social media presence"},
    "public_business_email": {"points": 15, "label": "Public business email present"},
    "high_value_category": {"points": 10, "label": "High commercial intent category"},
    "recently_discovered": {"points": 5, "label": "Recently discovered prospect"},
}

HIGH_VALUE_CATEGORIES = {
    "restaurant", "fast_food", "cafe", "pharmacy", "hospital", "clinic",
    "dentist", "hotel", "law_firm", "consulting", "retail", "supermarket",
    "gym", "spa", "real_estate"
}


@dataclass
class LeadScoreResult:
    score: int
    breakdown: List[Dict[str, Any]]
    explanation: str


class LeadScoringEngine:
    """
    Configurable sales lead scoring engine for BusinessRadar.
    Evaluates scoring rules and returns a 0-100 score with a point-by-point breakdown.
    """

    async def calculate_score(
        self,
        business: Business,
        db: Optional[AsyncSession] = None,
    ) -> LeadScoreResult:
        # 1. Load active rule weights from DB if available, else use defaults
        rules_map: Dict[str, Dict[str, Any]] = {}
        if db is not None:
            try:
                db_rules = await db.scalars(select(LeadScoringRule).where(LeadScoringRule.is_enabled.is_(True)))
                for r in db_rules:
                    rules_map[r.rule_key] = {"points": r.points, "label": r.label}
            except Exception as e:
                logger.debug("Could not read lead scoring rules from DB (%s), using defaults.", e)

        if not rules_map:
            rules_map = DEFAULT_SCORING_WEIGHTS

        total_score = 0
        breakdown: List[Dict[str, Any]] = []

        # Factor 1: Website Status
        if business.website_status == WebsiteStatus.NO_WEBSITE_FOUND.value:
            rule = rules_map.get("no_website_found")
            if rule and rule["points"] != 0:
                total_score += rule["points"]
                breakdown.append({
                    "rule_key": "no_website_found",
                    "label": rule["label"],
                    "points": rule["points"],
                    "reason": "Business has no website found on public internet"
                })
        elif business.website_status in (WebsiteStatus.WEBSITE_BROKEN.value, WebsiteStatus.WEBSITE_UNREACHABLE.value, WebsiteStatus.WEBSITE_REDIRECTS_INCORRECTLY.value):
            rule = rules_map.get("website_broken")
            if rule and rule["points"] != 0:
                total_score += rule["points"]
                breakdown.append({
                    "rule_key": "website_broken",
                    "label": rule["label"],
                    "points": rule["points"],
                    "reason": f"Website is broken or unreachable ({business.website_status})"
                })

        # Factor 2: Online Ordering
        if business.has_online_ordering is False:
            rule = rules_map.get("no_online_ordering")
            if rule and rule["points"] != 0:
                total_score += rule["points"]
                breakdown.append({
                    "rule_key": "no_online_ordering",
                    "label": rule["label"],
                    "points": rule["points"],
                    "reason": "No online storefront or food ordering link identified"
                })

        # Factor 3: Active Social Media
        social_count = len(business.social_profiles) if business.social_profiles else 0
        if social_count > 0:
            rule = rules_map.get("active_social_media")
            if rule and rule["points"] != 0:
                total_score += rule["points"]
                breakdown.append({
                    "rule_key": "active_social_media",
                    "label": rule["label"],
                    "points": rule["points"],
                    "reason": f"{social_count} social profile(s) linked (active audience engagement)"
                })

        # Factor 4: Public Business Email
        if business.public_email:
            rule = rules_map.get("public_business_email")
            if rule and rule["points"] != 0:
                total_score += rule["points"]
                breakdown.append({
                    "rule_key": "public_business_email",
                    "label": rule["label"],
                    "points": rule["points"],
                    "reason": f"Direct contact email available: {business.public_email}"
                })

        # Factor 5: Category Commercial Intent
        category_clean = (business.category or "").lower()
        if any(hvc in category_clean for hvc in HIGH_VALUE_CATEGORIES):
            rule = rules_map.get("high_value_category")
            if rule and rule["points"] != 0:
                total_score += rule["points"]
                breakdown.append({
                    "rule_key": "high_value_category",
                    "label": rule["label"],
                    "points": rule["points"],
                    "reason": f"High digital agency demand category: {business.category}"
                })

        # Factor 6: Recently Discovered
        if business.discovered_at:
            days_ago = (datetime.now(timezone.utc) - business.discovered_at).days
            if days_ago <= 14:
                rule = rules_map.get("recently_discovered")
                if rule and rule["points"] != 0:
                    total_score += rule["points"]
                    breakdown.append({
                        "rule_key": "recently_discovered",
                        "label": rule["label"],
                        "points": rule["points"],
                        "reason": f"Discovered {days_ago} days ago (fresh prospect)"
                    })

        # Cap score between 0 and 100
        clamped_score = max(0, min(100, total_score))

        summary_parts = [f"{item['label']}: +{item['points']}" for item in breakdown]
        explanation = f"Lead score: {clamped_score}/100. Reasons: " + "; ".join(summary_parts)

        return LeadScoreResult(
            score=clamped_score,
            breakdown=breakdown,
            explanation=explanation,
        )
