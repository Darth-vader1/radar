import logging
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import httpx

from app.core.http import get_limited, safe_async_client
from app.core.security import SSRFValidationError, validate_outbound_url
from app.models.business import WebsiteStatus

logger = logging.getLogger("radar.businesses.website_checker")

# Common social domains often mistakenly stored as business website in sparse directories
SOCIAL_DOMAINS = {
    "instagram.com", "www.instagram.com",
    "facebook.com", "www.facebook.com", "fb.com", "m.facebook.com",
    "twitter.com", "x.com",
    "linkedin.com", "www.linkedin.com",
    "wa.me", "api.whatsapp.com",
    "tiktok.com", "www.tiktok.com",
}

# Domains indicative of parked or expired domains
PARKING_INDICATORS = {
    "sedoparking", "godaddy.com/domainsearch", "dan.com",
    "hugedomains.com", "domainmarket.com", "parked-content",
    "buy this domain", "domain for sale"
}


@dataclass
class WebsiteCheckResult:
    status: WebsiteStatus
    normalized_url: Optional[str]
    is_social_url: bool
    social_platform: Optional[str]
    explanation: str


class WebsiteCheckerService:
    """
    Classifies website availability:
      1. HAS_WEBSITE
      2. NO_WEBSITE_FOUND
      3. WEBSITE_UNREACHABLE
      4. WEBSITE_BROKEN
      5. WEBSITE_REDIRECTS_INCORRECTLY
      6. WEBSITE_REQUIRES_MANUAL_VERIFICATION

    CRITICAL RULE: An absent website field in a directory must NOT automatically
    mean that a business has no website.
    """

    def __init__(self, timeout: float = 12.0):
        self.timeout = timeout

    async def verify_website(
        self,
        candidate_url: Optional[str],
        business_name: str,
        secondary_discovery_attempted: bool = False,
    ) -> WebsiteCheckResult:
        if not candidate_url or not candidate_url.strip():
            if not secondary_discovery_attempted:
                # Primary source didn't provide a website, but secondary checks haven't run yet
                return WebsiteCheckResult(
                    status=WebsiteStatus.WEBSITE_REQUIRES_MANUAL_VERIFICATION,
                    normalized_url=None,
                    is_social_url=False,
                    social_platform=None,
                    explanation="No website provided in primary source; pending secondary search check."
                )
            else:
                return WebsiteCheckResult(
                    status=WebsiteStatus.NO_WEBSITE_FOUND,
                    normalized_url=None,
                    is_social_url=False,
                    social_platform=None,
                    explanation="No website found after primary directory inspection and secondary discovery checks."
                )

        raw_url = candidate_url.strip()
        if not (raw_url.startswith("http://") or raw_url.startswith("https://")):
            raw_url = f"https://{raw_url}"

        # 1. Parse domain
        try:
            parsed = urlparse(raw_url)
            domain = parsed.netloc.lower()
        except Exception:
            return WebsiteCheckResult(
                status=WebsiteStatus.WEBSITE_BROKEN,
                normalized_url=raw_url,
                is_social_url=False,
                social_platform=None,
                explanation="Malformed URL syntax."
            )

        # 2. Check if URL is actually a social profile
        for social_dom in SOCIAL_DOMAINS:
            if domain == social_dom or domain.endswith(f".{social_dom}"):
                platform = "INSTAGRAM" if "instagram" in domain else ("FACEBOOK" if "facebook" in domain or "fb.com" in domain else "OTHER")
                return WebsiteCheckResult(
                    status=WebsiteStatus.WEBSITE_REQUIRES_MANUAL_VERIFICATION,
                    normalized_url=raw_url,
                    is_social_url=True,
                    social_platform=platform,
                    explanation=f"URL points to a {platform} social profile rather than a standalone commercial website."
                )

        # 3. SSRF validation check
        try:
            validate_outbound_url(raw_url)
        except SSRFValidationError as e:
            logger.warning("Website probe blocked by SSRF policy for %s: %s", raw_url, e)
            return WebsiteCheckResult(
                status=WebsiteStatus.WEBSITE_UNREACHABLE,
                normalized_url=raw_url,
                is_social_url=False,
                social_platform=None,
                explanation="URL resolves to a prohibited (private or internal) address range."
            )

        # 4. HTTP network probe
        try:
            async with safe_async_client(
                timeout=self.timeout,
                follow_redirects=True,
                max_redirects=5,
            ) as client:
                # Only the first few KB are inspected; truncate instead of downloading huge pages.
                resp = await get_limited(client, raw_url, max_bytes=64 * 1024, truncate=True)

                # Check anti-bot challenges (Cloudflare / Turnstile / 403 / 429)
                if resp.status_code in (403, 429):
                    return WebsiteCheckResult(
                        status=WebsiteStatus.WEBSITE_REQUIRES_MANUAL_VERIFICATION,
                        normalized_url=str(resp.url),
                        is_social_url=False,
                        social_platform=None,
                        explanation=f"Received HTTP {resp.status_code} challenge/WAF block. Requires manual verification."
                    )

                if resp.status_code >= 500:
                    return WebsiteCheckResult(
                        status=WebsiteStatus.WEBSITE_BROKEN,
                        normalized_url=str(resp.url),
                        is_social_url=False,
                        social_platform=None,
                        explanation=f"Target web server returned internal error HTTP {resp.status_code}."
                    )

                if resp.status_code >= 400:
                    return WebsiteCheckResult(
                        status=WebsiteStatus.WEBSITE_BROKEN,
                        normalized_url=str(resp.url),
                        is_social_url=False,
                        social_platform=None,
                        explanation=f"Target returned client error HTTP {resp.status_code}."
                    )

                # Inspect body for parking indicators
                body_lower = resp.text[:4000].lower()
                final_domain = urlparse(str(resp.url)).netloc.lower()

                # Redirected to completely unrelated domain or parking service
                for indicator in PARKING_INDICATORS:
                    if indicator in body_lower or indicator in final_domain:
                        return WebsiteCheckResult(
                            status=WebsiteStatus.WEBSITE_REDIRECTS_INCORRECTLY,
                            normalized_url=str(resp.url),
                            is_social_url=False,
                            social_platform=None,
                            explanation=f"Domain redirected to a parked or domain sales page ({indicator})."
                        )

                return WebsiteCheckResult(
                    status=WebsiteStatus.HAS_WEBSITE,
                    normalized_url=str(resp.url),
                    is_social_url=False,
                    social_platform=None,
                    explanation=f"Website active and operational (HTTP {resp.status_code})."
                )

        except (httpx.ConnectTimeout, httpx.ReadTimeout):
            return WebsiteCheckResult(
                status=WebsiteStatus.WEBSITE_UNREACHABLE,
                normalized_url=raw_url,
                is_social_url=False,
                social_platform=None,
                explanation="Connection timed out while probing website."
            )
        except httpx.ConnectError:
            return WebsiteCheckResult(
                status=WebsiteStatus.WEBSITE_UNREACHABLE,
                normalized_url=raw_url,
                is_social_url=False,
                social_platform=None,
                explanation="Could not establish network connection (DNS failure or host down)."
            )
        except Exception as exc:
            return WebsiteCheckResult(
                status=WebsiteStatus.WEBSITE_BROKEN,
                normalized_url=raw_url,
                is_social_url=False,
                social_platform=None,
                explanation=f"Error inspecting website: {exc}"
            )
