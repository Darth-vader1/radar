import asyncio
import pytest
import protego
from app.modules.scraping.politeness import RobotsPolicyService, TokenBucketRateLimiter


@pytest.mark.asyncio
async def test_robots_policy_evaluation():
    robots_text = """
    User-agent: *
    Disallow: /admin/
    Disallow: /secret/
    Allow: /public/
    Allow: /jobs/

    User-agent: RadarBot
    Disallow: /radar-forbidden/
    Allow: /
    """
    parsed = protego.Protego.parse(robots_text)

    # General bot rules
    assert parsed.can_fetch("https://example.com/public/page", "OtherBot") is True
    assert parsed.can_fetch("https://example.com/admin/settings", "OtherBot") is False

    # Specific RadarBot rules
    assert parsed.can_fetch("https://example.com/radar-forbidden/data", "RadarBot") is False
    assert parsed.can_fetch("https://example.com/jobs/dev", "RadarBot") is True


@pytest.mark.asyncio
async def test_rate_limiter_in_memory_fallback():
    limiter = TokenBucketRateLimiter(redis_url="redis://nonexistent-host:6379/9")

    # High RPM: interval is tiny
    t0 = asyncio.get_event_loop().time()
    res1 = await limiter.acquire("example.com", requests_per_minute=600, timeout=1.0)
    res2 = await limiter.acquire("example.com", requests_per_minute=600, timeout=1.0)
    t1 = asyncio.get_event_loop().time()

    assert res1 is True
    assert res2 is True
    assert (t1 - t0) >= 0.1  # min 0.1s interval between two 600 RPM calls
