import asyncio
import logging
from typing import Optional
from urllib.parse import urlparse

import protego
import redis.asyncio as aioredis

from app.core.config import settings
from app.core.http import get_limited, safe_async_client
from app.core.security import validate_outbound_url

logger = logging.getLogger("radar.scraping.politeness")


class TokenBucketRateLimiter:
    """
    Distributed Redis-backed Token Bucket rate limiter per domain.
    Falls back gracefully to an in-memory lock if Redis is unavailable.
    """

    def __init__(self, redis_url: str = settings.REDIS_URL):
        self.redis_url = redis_url
        self._redis_client: Optional[aioredis.Redis] = None
        self._local_locks: dict[str, asyncio.Lock] = {}
        self._local_last_request: dict[str, float] = {}

    async def get_redis(self) -> aioredis.Redis:
        if self._redis_client is None:
            self._redis_client = aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_timeout=3.0,
            )
        return self._redis_client

    async def close(self) -> None:
        """Closes the underlying Redis connection if opened."""
        if self._redis_client is not None:
            try:
                await self._redis_client.aclose()
            except Exception as e:
                logger.debug("Error closing Redis client in rate limiter: %s", e)
            finally:
                self._redis_client = None

    async def acquire(self, domain: str, requests_per_minute: int = 30, timeout: float = 15.0) -> bool:
        """
        Ensures calls to `domain` do not exceed `requests_per_minute`.
        Enforces a minimum interval between calls.
        """
        if requests_per_minute <= 0:
            return True

        min_interval = 60.0 / requests_per_minute

        try:
            r = await self.get_redis()
            key = f"rate_limit:{domain}"
            start_time = asyncio.get_event_loop().time()

            while (asyncio.get_event_loop().time() - start_time) < timeout:
                # Use Redis set with NX and PX (millisecond TTL)
                acquired = await r.set(key, "1", nx=True, px=int(min_interval * 1000))
                if acquired:
                    return True
                await asyncio.sleep(min(min_interval / 2.0, 0.5))

            logger.warning("Rate limit acquire timed out for domain %s", domain)
            return False

        except Exception as e:
            logger.debug("Redis rate limiter fallback to in-memory: %s", e)
            if domain not in self._local_locks:
                self._local_locks[domain] = asyncio.Lock()

            async with self._local_locks[domain]:
                now = asyncio.get_event_loop().time()
                elapsed = now - self._local_last_request.get(domain, 0.0)
                if elapsed < min_interval:
                    remaining_wait = min_interval - elapsed
                    if remaining_wait > timeout:
                        return False
                    await asyncio.sleep(remaining_wait)
                self._local_last_request[domain] = asyncio.get_event_loop().time()
                return True


class RobotsPolicyService:
    """
    Fetches, parses, and caches robots.txt policies per domain in Redis (24-hour TTL).
    Uses protego for standard RFC 9309 robots.txt evaluation.
    """

    CACHE_TTL_SECONDS = 86400  # 24 hours

    def __init__(self, redis_url: str = settings.REDIS_URL, user_agent: str = settings.HTTP_USER_AGENT):
        self.redis_url = redis_url
        self.user_agent = user_agent
        self._redis_client: Optional[aioredis.Redis] = None
        self._memory_cache: dict[str, protego.Protego] = {}

    async def get_redis(self) -> aioredis.Redis:
        if self._redis_client is None:
            self._redis_client = aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_timeout=3.0,
            )
        return self._redis_client

    def _extract_domain_and_robots_url(self, url: str) -> tuple[str, str]:
        parsed = urlparse(url)
        domain = (parsed.hostname or parsed.netloc).lower()
        scheme = parsed.scheme.lower() or "https"
        netloc = parsed.netloc.lower()
        robots_url = f"{scheme}://{netloc}/robots.txt"
        return domain, robots_url

    async def get_policy(self, url: str) -> protego.Protego:
        domain, robots_url = self._extract_domain_and_robots_url(url)

        # 1. Check in-memory cache
        if domain in self._memory_cache:
            return self._memory_cache[domain]

        # 2. Check Redis cache
        cache_key = f"robots_txt:{domain}"
        raw_robots_txt: Optional[str] = None

        try:
            r = await self.get_redis()
            cached = await r.get(cache_key)
            if cached is not None:
                raw_robots_txt = cached if isinstance(cached, str) else cached.decode("utf-8", "replace")
        except Exception as e:
            logger.debug("Redis robots cache read error: %s", e)

        # 3. Fetch from remote host if not cached
        if raw_robots_txt is None:
            try:
                # SSRF guard on robots.txt URL
                validate_outbound_url(robots_url)

                # Redirects are followed, but every hop is SSRF-checked by the safe transport.
                # RFC 9309: crawlers must parse at least 500 KiB; anything beyond can be ignored.
                async with safe_async_client(timeout=8.0, follow_redirects=True) as client:
                    resp = await get_limited(
                        client, robots_url, max_bytes=512 * 1024, truncate=True,
                        headers={"User-Agent": self.user_agent},
                    )
                    if resp.status_code == 200:
                        raw_robots_txt = resp.text
                    elif resp.status_code in (401, 403):
                        # Disallow all if explicitly denied
                        raw_robots_txt = "User-agent: *\nDisallow: /"
                    else:
                        # 404 or other: allow all
                        raw_robots_txt = "User-agent: *\nAllow: /"

                # Store in Redis
                try:
                    r = await self.get_redis()
                    await r.set(cache_key, raw_robots_txt, ex=self.CACHE_TTL_SECONDS)
                except Exception:
                    pass

            except Exception as exc:
                logger.debug("Could not fetch robots.txt for %s: %s (defaulting to permissive)", domain, exc)
                raw_robots_txt = "User-agent: *\nAllow: /"

        # Parse with protego
        try:
            rp = protego.Protego.parse(raw_robots_txt)
        except Exception:
            rp = protego.Protego.parse("User-agent: *\nAllow: /")

        self._memory_cache[domain] = rp
        return rp

    async def close(self) -> None:
        """Closes the underlying Redis connection if opened."""
        if self._redis_client is not None:
            try:
                await self._redis_client.aclose()
            except Exception as e:
                logger.debug("Error closing Redis client in robots service: %s", e)
            finally:
                self._redis_client = None

    async def get_crawl_delay(self, url: str) -> Optional[float]:
        """
        Returns the crawl-delay in seconds if specified in robots.txt for this bot or '*',
        otherwise None. Also checks RFC Request-rate directives if supported by the parser.
        """
        try:
            policy = await self.get_policy(url)
            bot_name = self.user_agent.split("/")[0].strip() if self.user_agent else "*"
            delay = policy.crawl_delay(bot_name)
            if delay is None:
                delay = policy.crawl_delay("*")
            if delay is not None:
                return float(delay)

            # Check for RFC Request-rate if available in protego
            req_rate = getattr(policy, "request_rate", None)
            if callable(req_rate):
                rate = policy.request_rate(bot_name) or policy.request_rate("*")
                if rate and getattr(rate, "requests", None) and getattr(rate, "seconds", None):
                    if rate.requests > 0:
                        return float(rate.seconds) / float(rate.requests)

            return None
        except Exception as e:
            logger.debug("Error getting crawl delay for %s: %s", url, e)
            return None

    async def is_allowed(self, url: str) -> bool:
        """
        Returns True if the user_agent is permitted by robots.txt to crawl url.
        Follows RFC 9309 precedence: matches specific bot first, falling back to wildcard '*'.
        """
        try:
            policy = await self.get_policy(url)
            bot_name = self.user_agent.split("/")[0].strip() if self.user_agent else "*"
            return policy.can_fetch(url, bot_name)
        except Exception as e:
            logger.warning("Error evaluating robots.txt for %s: %s (allowing)", url, e)
            return True
