from dataclasses import dataclass, field
import logging
import re
from typing import List, Optional, Set
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import httpx

from app.core.http import get_limited, safe_async_client

from app.core.config import settings
from app.core.security import SSRFValidationError, validate_outbound_url

logger = logging.getLogger("radar.businesses.site_enricher")

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
PHONE_REGEX = re.compile(r"(\+?[0-9]{1,4}[\s\-]?)?(\(?[0-9]{2,4}\)?[\s\-]?)?[0-9]{3,4}[\s\-]?[0-9]{3,4}")

ONLINE_ORDERING_DOMAINS = {
    "chowdeck.com", "glovoapp.com", "paystack.shop",
    "shopify.com", "woocommerce.com", "jumia.com.ng",
    "konga.com", "edenlife.ng", "flutterwave.com/store"
}


@dataclass
class EnrichedContactData:
    emails: Set[str] = field(default_factory=set)
    phones: Set[str] = field(default_factory=set)
    social_profiles: List[dict] = field(default_factory=list)
    has_online_ordering: bool = False
    ordering_links: List[str] = field(default_factory=list)


# Homepages/contact pages are parsed for contact details only; 2 MB is ample.
ENRICH_MAX_BYTES = 2 * 1024 * 1024


class BusinessSiteEnricher:
    """
    Crawls a discovered business website (homepage + /contact) to enrich
    email addresses, phone numbers, social media links, and online ordering availability.
    """

    def __init__(self, timeout: float = 12.0):
        self.timeout = timeout

    async def enrich_from_website(self, website_url: str) -> EnrichedContactData:
        data = EnrichedContactData()
        if not website_url:
            return data

        try:
            validate_outbound_url(website_url)
        except SSRFValidationError:
            return data

        async with safe_async_client(timeout=self.timeout, follow_redirects=True) as client:
            pages_to_visit = [website_url]

            # Try to discover contact link on homepage
            try:
                resp = await get_limited(client, website_url, max_bytes=ENRICH_MAX_BYTES, truncate=True)
                if resp.status_code == 200:
                    self._parse_page(resp.text, resp.url, data)

                    # Look for contact / about page link
                    soup = BeautifulSoup(resp.text, "lxml")
                    for a in soup.find_all("a", href=True):
                        href = a["href"].lower()
                        if any(kw in href for kw in ("contact", "about", "get-in-touch")):
                            contact_url = urljoin(resp.url, a["href"])
                            if contact_url not in pages_to_visit and len(pages_to_visit) < 3:
                                pages_to_visit.append(contact_url)
            except Exception as e:
                logger.debug("Enrichment failed on %s: %s", website_url, e)
                return data

            # Visit contact page if discovered
            if len(pages_to_visit) > 1:
                contact_url = pages_to_visit[1]
                try:
                    validate_outbound_url(contact_url)
                    resp = await get_limited(client, contact_url, max_bytes=ENRICH_MAX_BYTES, truncate=True)
                    if resp.status_code == 200:
                        self._parse_page(resp.text, resp.url, data)
                except Exception:
                    pass

        return data

    def _parse_page(self, html_text: str, base_url: str, data: EnrichedContactData) -> None:
        soup = BeautifulSoup(html_text, "lxml")

        # 1. mailto: links and raw emails
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("mailto:"):
                clean = href.replace("mailto:", "").split("?")[0].strip().lower()
                if clean:
                    data.emails.add(clean)

            if href.startswith("tel:"):
                clean_phone = href.replace("tel:", "").strip()
                if clean_phone:
                    data.phones.add(clean_phone)

            # Social profile links
            parsed = urlparse(urljoin(base_url, href))
            dom = parsed.netloc.lower()

            if "instagram.com" in dom and len(parsed.path) > 1:
                data.social_profiles.append({"platform": "INSTAGRAM", "url": urljoin(base_url, href)})
            elif ("facebook.com" in dom or "fb.com" in dom) and len(parsed.path) > 1:
                data.social_profiles.append({"platform": "FACEBOOK", "url": urljoin(base_url, href)})
            elif "linkedin.com" in dom and len(parsed.path) > 1:
                data.social_profiles.append({"platform": "LINKEDIN", "url": urljoin(base_url, href)})
            elif ("twitter.com" in dom or "x.com" in dom) and len(parsed.path) > 1:
                data.social_profiles.append({"platform": "X_TWITTER", "url": urljoin(base_url, href)})

            # Online ordering links
            for ord_dom in ONLINE_ORDERING_DOMAINS:
                if ord_dom in dom or ord_dom in href:
                    data.has_online_ordering = True
                    data.ordering_links.append(urljoin(base_url, href))

        # Check raw text for email pattern
        text = soup.get_text()
        found_emails = EMAIL_REGEX.findall(text)
        for em in found_emails[:5]:
            clean_em = em.strip().lower()
            if not clean_em.endswith((".png", ".jpg", ".jpeg", ".svg")):
                data.emails.add(clean_em)
