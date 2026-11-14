import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx

from app.core.config import settings
from app.core.http import Resolver, ResponseTooLargeError, read_limited, safe_async_client
from app.core.security import HostResolutionError, SSRFValidationError, validate_outbound_url
from app.modules.scraping.adapter_base import DiscoverySeed, RateLimitPolicy, RawFetchArtifact
from app.modules.scraping.politeness import RobotsPolicyService, TokenBucketRateLimiter

logger = logging.getLogger("radar.scraping.gateway")


class FetchError(Exception):
    """Base exception for scraping fetch failures."""
    pass


class RobotsDisallowedError(FetchError):
    """Raised when crawling a URL is prohibited by robots.txt."""

    def __init__(self, url: str, message: Optional[str] = None):
        self.url = url
        super().__init__(message or f"Robots.txt disallows crawling {url}")


class RateLimitExceededError(FetchError):
    """Raised when rate limiting cannot be acquired within timeout."""

    def __init__(self, domain: str, requests_per_minute: int, timeout: float, message: Optional[str] = None):
        self.domain = domain
        self.requests_per_minute = requests_per_minute
        self.timeout = timeout
        super().__init__(
            message
            or f"Rate limit exceeded or timed out for domain '{domain}' (limit: {requests_per_minute} rpm, timeout: {timeout}s)"
        )


class DisallowedContentTypeError(FetchError):
    """Raised when a response's content type is not one the crawler processes."""


# Crawlers only ever parse markup, JSON, feeds and plain text. Anything else (archives,
# executables, media) is rejected before its body is read.
ALLOWED_CONTENT_TYPE_PREFIXES = (
    "text/",
    "application/json",
    "application/ld+json",
    "application/xml",
    "application/xhtml+xml",
    "application/rss+xml",
    "application/atom+xml",
    "application/javascript",
)


def _content_type_allowed(content_type: str) -> bool:
    if not content_type:
        return True  # many APIs omit it; the size cap still applies
    base = content_type.split(";", 1)[0].strip().lower()
    return base.startswith(ALLOWED_CONTENT_TYPE_PREFIXES) or base.endswith(("+json", "+xml"))


# Network failures worth retrying (the request may well succeed a few seconds later).
TRANSIENT_HTTP_ERRORS = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2.0

# Absolute ceiling for any per-source max_response_bytes override.
MAX_RESPONSE_BYTES_CEILING = 50 * 1024 * 1024


class FetcherGateway:
    """
    Unified, SSRF-guarded fetcher for HTTP and JavaScript-rendered pages
    with built-in robots.txt compliance and token-bucket rate limiting.
    """

    def __init__(
        self,
        user_agent: str = settings.HTTP_USER_AGENT,
        timeout: float = settings.DEFAULT_REQUEST_TIMEOUT,
        max_redirect_hops: int = settings.MAX_REDIRECT_HOPS,
        robots_service: Optional[RobotsPolicyService] = None,
        rate_limiter: Optional[TokenBucketRateLimiter] = None,
        enforce_robots: bool = True,
        enforce_rate_limit: bool = True,
        default_requests_per_minute: int = 30,
        rate_limit_timeout: float = 15.0,
        max_response_bytes: Optional[int] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        resolver: Optional[Resolver] = None,
    ):
        self.user_agent = user_agent
        self.timeout = timeout
        self.max_redirect_hops = max_redirect_hops
        self.robots_service = robots_service or RobotsPolicyService(user_agent=self.user_agent)
        self.rate_limiter = rate_limiter or TokenBucketRateLimiter()
        self.enforce_robots = enforce_robots
        self.enforce_rate_limit = enforce_rate_limit
        self.default_requests_per_minute = default_requests_per_minute
        self.rate_limit_timeout = rate_limit_timeout
        self.max_response_bytes = max_response_bytes or settings.MAX_RESPONSE_BYTES
        # Network layer override (tests); SSRF pinning always wraps it.
        self._transport = transport
        self._resolver = resolver

    async def close(self) -> None:
        """Cleans up Redis and HTTP resources in politeness services."""
        if self.robots_service is not None:
            await self.robots_service.close()
        if self.rate_limiter is not None:
            await self.rate_limiter.close()

    async def fetch(
        self,
        seed: DiscoverySeed,
        rate_policy: Optional[RateLimitPolicy] = None,
        enforce_robots: Optional[bool] = None,
        enforce_rate_limit: Optional[bool] = None,
    ) -> RawFetchArtifact:
        """
        SSRF-guarded, politeness-checked fetcher.
        Checks robots.txt compliance, acquires token-bucket rate limits (factoring in
        crawl-delay), and dispatches to either Playwright headless rendering or HTTPX.
        """
        effective_policy = rate_policy or seed.rate_policy

        # 1. Robots.txt policy enforcement
        should_check_robots = self.enforce_robots if enforce_robots is None else enforce_robots
        if effective_policy is not None:
            should_check_robots = should_check_robots and effective_policy.respect_robots_txt

        if should_check_robots:
            allowed = await self.robots_service.is_allowed(seed.url)
            if not allowed:
                raise RobotsDisallowedError(seed.url)

        # 2. Rate limiting enforcement
        should_rate_limit = self.enforce_rate_limit if enforce_rate_limit is None else enforce_rate_limit
        if should_rate_limit:
            parsed = urlparse(seed.url)
            domain = (parsed.hostname or parsed.netloc).lower()
            rpm = (
                effective_policy.requests_per_minute
                if effective_policy is not None
                else self.default_requests_per_minute
            )

            # Factor in crawl-delay if robots.txt specifies one
            crawl_delay = await self.robots_service.get_crawl_delay(seed.url)
            if crawl_delay and crawl_delay > 0:
                crawl_delay_rpm = int(60.0 / crawl_delay)
                if crawl_delay_rpm > 0:
                    rpm = min(rpm, crawl_delay_rpm)

            acquired = await self.rate_limiter.acquire(
                domain=domain,
                requests_per_minute=rpm,
                timeout=self.rate_limit_timeout,
            )
            if not acquired:
                raise RateLimitExceededError(
                    domain=domain,
                    requests_per_minute=rpm,
                    timeout=self.rate_limit_timeout,
                )

        # 3. Execution dispatch
        max_bytes = effective_policy.max_response_bytes if effective_policy is not None else None
        timeout = effective_policy.request_timeout_seconds if effective_policy is not None else None
        if seed.requires_js:
            return await self.fetch_rendered(seed)
        return await self.fetch_http(seed, max_bytes=max_bytes, timeout=timeout)

    async def fetch_http(
        self,
        seed: DiscoverySeed,
        max_bytes: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> RawFetchArtifact:
        """
        Fetches with retries: timeouts, dropped connections and DNS failures are retried
        (RETRY_ATTEMPTS in total, with backoff). Everything else -- SSRF blocks, oversized or
        disallowed responses, HTTP error statuses -- is returned or raised immediately.
        """
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                return await self._fetch_http_once(seed, max_bytes, timeout)
            except (FetchError, HostResolutionError) as exc:
                transient = isinstance(exc, HostResolutionError) or isinstance(exc.__cause__, TRANSIENT_HTTP_ERRORS)
                if not transient or attempt == RETRY_ATTEMPTS:
                    raise
                delay = RETRY_BACKOFF_SECONDS * attempt
                logger.warning("Transient error fetching %s (attempt %d/%d), retrying in %.0fs: %s",
                               seed.url, attempt, RETRY_ATTEMPTS, delay, exc)
                await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    async def _fetch_http_once(
        self, seed: DiscoverySeed, max_bytes: Optional[int], timeout: Optional[float]
    ) -> RawFetchArtifact:
        """
        SSRF-guarded HTTP request with hop-by-hop redirect verification.
        Every request (initial and each redirect hop) goes through SSRFSafeTransport, which
        resolves, validates and pins the connection IP. Bodies are streamed with a size cap.
        """
        current_url = seed.url
        validate_outbound_url(current_url)  # fail fast with a clear error before connecting

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            **seed.headers,
        }

        async with safe_async_client(
            timeout=timeout or self.timeout,
            follow_redirects=False,
            transport=self._transport,
            resolver=self._resolver,
        ) as client:
            hops = 0
            method = seed.method.upper()
            # httpx *replaces* a URL's query string with `params` (even an empty dict, which
            # silently turned ".../list?page=2" into ".../list"), so merge them into the URL instead.
            if seed.params:
                current_url = str(httpx.URL(current_url).copy_merge_params(seed.params))
            params = None
            body = seed.body

            while hops <= self.max_redirect_hops:
                try:
                    async with client.stream(
                        method=method,
                        url=current_url,
                        params=params if hops == 0 else None,
                        headers=headers,
                        json=body if (isinstance(body, dict) and hops == 0) else None,
                        content=body if (isinstance(body, str) and hops == 0) else None,
                    ) as resp:
                        # Check if this is a redirect
                        if resp.is_redirect:
                            location = resp.headers.get("location")
                            if not location:
                                raise FetchError(f"Redirect without Location header from {current_url}")
                            hops += 1
                            next_url = urljoin(current_url, location)
                            validate_outbound_url(next_url)
                            current_url = next_url
                            method = "GET"
                            body = None
                            continue

                        content_type = resp.headers.get("content-type", "").lower()
                        if not _content_type_allowed(content_type):
                            raise DisallowedContentTypeError(
                                f"Refusing to download content type '{content_type}' from {current_url}"
                            )

                        limit = min(max_bytes or self.max_response_bytes, MAX_RESPONSE_BYTES_CEILING)
                        limited = await read_limited(resp, limit)
                except ResponseTooLargeError as exc:
                    raise FetchError(str(exc)) from exc
                except httpx.RequestError as exc:
                    # Some httpx errors (e.g. ReadTimeout) have an empty message; always name the type.
                    raise FetchError(f"HTTP request error for {current_url}: {type(exc).__name__}: {exc}") from exc

                return RawFetchArtifact(
                    seed=seed,
                    final_url=current_url,
                    status_code=limited.status_code,
                    content_type=content_type,
                    body_text=limited.text,
                    fetched_at=datetime.now(timezone.utc),
                    response_headers=dict(limited.headers),
                )

            raise FetchError(f"Exceeded max redirect hops ({self.max_redirect_hops}) for {seed.url}")

    async def fetch_rendered(self, seed: DiscoverySeed) -> RawFetchArtifact:
        """
        Renders dynamic JavaScript pages using Playwright with network route interception.
        Aborts images, fonts, media, and stylesheets for performance while
        enforcing SSRF policy on all requested subresources.
        """
        validate_outbound_url(seed.url)

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("Playwright not installed; falling back to fetch_http.")
            return await self.fetch_http(seed)

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
                )
                context = await browser.new_context(
                    user_agent=self.user_agent,
                    viewport={"width": 1280, "height": 800},
                )
                page = await context.new_page()

                # Intercept network requests for SSRF protection & speed optimization
                async def handle_route(route):
                    request = route.request
                    res_type = request.resource_type
                    req_url = request.url

                    # Block heavy non-essential media
                    if res_type in ("image", "media", "font", "stylesheet"):
                        await route.abort()
                        return

                    # SSRF check on subresources
                    try:
                        validate_outbound_url(req_url)
                        await route.continue_()
                    except SSRFValidationError as e:
                        logger.warning("Playwright subresource blocked by SSRF: %s (%s)", req_url, e)
                        await route.abort()

                await page.route("**/*", handle_route)

                try:
                    response = await page.goto(
                        seed.url,
                        timeout=int(self.timeout * 1000),
                        wait_until="domcontentloaded",
                    )
                    # Allow client-side rendering to settle
                    await page.wait_for_timeout(1000)

                    content = await page.content()
                    status_code = response.status if response else 200
                    final_url = page.url
                    content_type = "text/html; charset=utf-8"

                finally:
                    await context.close()
                    await browser.close()

                return RawFetchArtifact(
                    seed=seed,
                    final_url=final_url,
                    status_code=status_code,
                    content_type=content_type,
                    body_text=content,
                    fetched_at=datetime.now(timezone.utc),
                    response_headers={},
                )

        except Exception as e:
            logger.warning("Playwright rendering failed: %s. Falling back to HTTPX.", e)
            return await self.fetch_http(seed)
