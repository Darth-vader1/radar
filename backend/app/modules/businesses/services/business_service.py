import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.locks import advisory_xact_lock
from app.models.business import (
    Business,
    BusinessContact,
    BusinessSocialProfile,
    EmailVerification,
    LeadScore,
    VerificationStatus,
    WebsiteStatus,
)
from app.modules.businesses.adapters.osm_overpass import NormalizedBusiness
from app.modules.businesses.adapters.site_enricher import BusinessSiteEnricher
from app.modules.businesses.services.email_verifier import EmailVerifierService
from app.modules.businesses.services.lead_scorer import LeadScoringEngine
from app.modules.businesses.services.website_checker import WebsiteCheckerService

logger = logging.getLogger("radar.businesses.service")


def normalize_string(val: str) -> str:
    """Lowercases, removes punctuation, and trims excess whitespace."""
    if not val:
        return ""
    clean = re.sub(r"[^\w\s]", "", val.lower())
    return " ".join(clean.split())


class BusinessIngestionService:
    """
    Coordinates website verification, email enrichment, deduplication,
    lead scoring, and database persistence for BusinessRadar.
    """

    def __init__(
        self,
        website_checker: Optional[WebsiteCheckerService] = None,
        email_verifier: Optional[EmailVerifierService] = None,
        site_enricher: Optional[BusinessSiteEnricher] = None,
        lead_scorer: Optional[LeadScoringEngine] = None,
    ):
        self.website_checker = website_checker or WebsiteCheckerService()
        self.email_verifier = email_verifier or EmailVerifierService()
        self.site_enricher = site_enricher or BusinessSiteEnricher()
        self.lead_scorer = lead_scorer or LeadScoringEngine()

    async def ingest_business(
        self,
        db: AsyncSession,
        normalized: NormalizedBusiness,
        source_id: uuid.UUID,
        original_source_url: str,
    ) -> Tuple[Business, str]:
        """
        Processes normalized business: deduplicates, verifies website,
        enriches contacts, computes lead score, and stores in PostgreSQL.
        Returns: (business, "CREATED" | "UPDATED" | "DEDUPLICATED")
        """
        norm_name = normalize_string(normalized.name)
        norm_country = normalized.country.strip().lower()

        # Serialize concurrent ingestion of the same business (see advisory_xact_lock).
        await advisory_xact_lock(db, f"business:{norm_country}:{norm_name}")

        # 1. Deduplication check against existing businesses
        stmt = (
            select(Business)
            .where(
                Business.normalized_name == norm_name,
                func.lower(Business.country) == norm_country,
            )
            .options(
                selectinload(Business.contacts),
                selectinload(Business.social_profiles),
            )
        )
        existing = await db.scalar(stmt)

        is_new = existing is None
        business = existing if existing else Business(
            name=normalized.name.strip(),
            normalized_name=norm_name,
            original_source_url=original_source_url,
            primary_source_id=source_id,
            country=normalized.country,
            # Initialise collections up front: touching an unloaded relationship on a new
            # object after flush triggers a lazy load, which raises MissingGreenlet in async.
            contacts=[],
            social_profiles=[],
        )

        # Update core fields if new or previously missing
        if is_new or not business.category:
            business.category = normalized.category
        if is_new or not business.subcategory:
            business.subcategory = normalized.subcategory
        if is_new or not business.physical_address:
            business.physical_address = normalized.physical_address
        if is_new or not business.city:
            business.city = normalized.city
        if is_new or not business.state:
            business.state = normalized.state
        if is_new or (normalized.latitude and not business.latitude):
            business.latitude = normalized.latitude
            business.longitude = normalized.longitude

        # 2. Website Availability State Machine Check
        target_web_url = normalized.website_url or business.website_url
        web_check = await self.website_checker.verify_website(
            candidate_url=target_web_url,
            business_name=business.name,
            secondary_discovery_attempted=True,
        )

        business.website_status = web_check.status.value
        if web_check.normalized_url and not web_check.is_social_url:
            business.website_url = web_check.normalized_url
            try:
                business.website_domain = urlparse(web_check.normalized_url).netloc.lower()
            except Exception:
                pass

        if is_new:
            db.add(business)
            await db.flush()

        # Handle social profile discovered in place of website
        if web_check.is_social_url and web_check.normalized_url:
            self._add_social_profile(
                business,
                platform=web_check.social_platform or "OTHER",
                url=web_check.normalized_url,
                source="website_verification",
            )

        # 3. Direct Phone Contact
        if normalized.phone_number:
            business.phone_number = normalized.phone_number
            business.phone_verification_status = VerificationStatus.UNVERIFIED.value
            self._add_contact(
                business,
                contact_type="PHONE",
                value=normalized.phone_number,
                source="directory_seed",
                status="UNVERIFIED",
            )

        # 4. Website Content Enrichment (if operational)
        if business.website_status == WebsiteStatus.HAS_WEBSITE.value and business.website_url:
            enrichment_data = await self.site_enricher.enrich_from_website(business.website_url)

            if enrichment_data.has_online_ordering:
                business.has_online_ordering = True

            # Add discovered social profiles
            for soc in enrichment_data.social_profiles:
                self._add_social_profile(business, platform=soc["platform"], url=soc["url"], source="site_enrichment")

            # Add discovered phone numbers
            for ph in enrichment_data.phones:
                self._add_contact(business, contact_type="PHONE", value=ph, source="site_enrichment", status="UNVERIFIED")

            # Verify and add discovered emails
            for em in enrichment_data.emails:
                ver_res = self.email_verifier.verify_email(em)
                if ver_res.syntax_valid and ver_res.status != VerificationStatus.INVALID:
                    if not business.public_email:
                        business.public_email = ver_res.email
                        business.email_domain = ver_res.domain
                        business.email_verification_status = ver_res.status.value

                    self._add_contact(
                        business,
                        contact_type="EMAIL",
                        value=ver_res.email,
                        source="site_enrichment",
                        status=ver_res.status.value,
                        confidence=ver_res.confidence_score,
                    )

                    # Persist verification audit log
                    ev = EmailVerification(
                        business_id=business.id,
                        email_address=ver_res.email,
                        syntax_valid=ver_res.syntax_valid,
                        domain=ver_res.domain,
                        mx_records_found=ver_res.mx_records_found,
                        mx_hosts=ver_res.mx_hosts,
                        disposable_domain=ver_res.disposable_domain,
                        role_based_prefix=ver_res.role_based_prefix,
                        status=ver_res.status.value,
                        confidence_score=ver_res.confidence_score,
                    )
                    db.add(ev)

        # Assess online presence tier
        soc_count = len(business.social_profiles)
        has_web = business.website_status == WebsiteStatus.HAS_WEBSITE.value
        if has_web and soc_count >= 2:
            business.online_presence = "STRONG"
        elif has_web or soc_count >= 1:
            business.online_presence = "MODERATE"
        elif business.website_status == WebsiteStatus.NO_WEBSITE_FOUND.value and soc_count == 0:
            business.online_presence = "NONE"
        else:
            business.online_presence = "WEAK"

        # 5. Lead Scoring Engine Execution
        score_res = await self.lead_scorer.calculate_score(business, db=db)
        business.lead_score = score_res.score
        business.lead_score_explanation = score_res.breakdown
        business.last_verified_at = datetime.now(timezone.utc)

        # Persist lead score audit record
        ls = LeadScore(
            business_id=business.id,
            score=score_res.score,
            breakdown=score_res.breakdown,
        )
        db.add(ls)

        await db.commit()
        await db.refresh(business)

        return business, "CREATED" if is_new else "UPDATED"

    def _add_contact(
        self,
        business: Business,
        contact_type: str,
        value: str,
        source: str,
        status: str,
        confidence: float = 0.5,
    ) -> None:
        clean_val = value.strip().lower()
        if not business.contacts:
            business.contacts = []

        for c in business.contacts:
            if c.contact_type == contact_type and c.normalized_value == clean_val:
                return

        new_c = BusinessContact(
            business_id=business.id,
            contact_type=contact_type,
            value=value.strip(),
            normalized_value=clean_val,
            discovery_source=source,
            verification_status=status,
            confidence_score=confidence,
            is_primary=(len(business.contacts) == 0),
        )
        business.contacts.append(new_c)

    def _add_social_profile(
        self,
        business: Business,
        platform: str,
        url: str,
        source: str,
    ) -> None:
        clean_url = url.strip()
        if not business.social_profiles:
            business.social_profiles = []

        for sp in business.social_profiles:
            if sp.platform == platform and sp.profile_url == clean_url:
                return

        new_sp = BusinessSocialProfile(
            business_id=business.id,
            platform=platform,
            profile_url=clean_url,
            is_active=True,
            discovery_source=source,
        )
        business.social_profiles.append(new_sp)
