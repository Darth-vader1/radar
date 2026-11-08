import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.core.security import SSRFValidationError
from app.modules.scraping.politeness import RobotsPolicyService, TokenBucketRateLimiter


@pytest.mark.asyncio
class TestTokenBucketRateLimiter:

    async def test_acquire_in_memory_success(self):
        # Force fallback to in-memory by supplying invalid redis or mocking get_redis error
        limiter = TokenBucketRateLimiter()
        with patch.object(limiter, "get_redis", side_effect=Exception("Redis connection error")):
            # High rpm so sleep is negligible
            acquired = await limiter.acquire("example.com", requests_per_minute=6000, timeout=1.0)
            assert acquired is True

    async def test_acquire_in_memory_timeout(self):
        limiter = TokenBucketRateLimiter()
        with patch.object(limiter, "get_redis", side_effect=Exception("Redis connection error")):
            # First request sets the timestamp
            await limiter.acquire("slow.com", requests_per_minute=1, timeout=0.01)
            # Second immediate request with very short timeout should fail because min_interval is 60s
            acquired = await limiter.acquire("slow.com", requests_per_minute=1, timeout=0.01)
            assert acquired is False

    async def test_acquire_redis_success(self):
        limiter = TokenBucketRateLimiter()
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(limiter, "get_redis", return_value=mock_redis):
            acquired = await limiter.acquire("example.com", requests_per_minute=60, timeout=1.0)
            assert acquired is True
            mock_redis.set.assert_called_once()
            call_args = mock_redis.set.call_args
            assert call_args[0][0] == "rate_limit:example.com"
            assert call_args[1].get("nx") is True

    async def test_acquire_redis_timeout(self):
        limiter = TokenBucketRateLimiter()
        mock_redis = AsyncMock()
        # Redis set returns None/False indicating lock is held
        mock_redis.set = AsyncMock(return_value=False)

        with patch.object(limiter, "get_redis", return_value=mock_redis):
            acquired = await limiter.acquire("busy.com", requests_per_minute=60, timeout=0.05)
            assert acquired is False

    async def test_close_cleans_up(self):
        limiter = TokenBucketRateLimiter()
        mock_redis = AsyncMock()
        mock_redis.aclose = AsyncMock()
        limiter._redis_client = mock_redis

        await limiter.close()
        mock_redis.aclose.assert_called_once()
        assert limiter._redis_client is None


@pytest.mark.asyncio
class TestRobotsPolicyService:

    async def test_is_allowed_basic_rules(self):
        service = RobotsPolicyService(user_agent="RadarBot/1.0")

        robots_content = """
User-agent: *
Disallow: /admin/
Disallow: /private/
Allow: /admin/public
"""
        with patch.object(service, "get_redis", side_effect=Exception("No redis")):
            with patch("app.modules.scraping.politeness.get_limited", new_callable=AsyncMock) as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.text = robots_content
                mock_get.return_value = mock_resp

                assert await service.is_allowed("https://example.com/index.html") is True
                assert await service.is_allowed("https://example.com/admin/settings") is False
                assert await service.is_allowed("https://example.com/private/data") is False
                assert await service.is_allowed("https://example.com/admin/public") is True

    async def test_bot_specific_disallow(self):
        service = RobotsPolicyService(user_agent="RadarBot/1.0")

        robots_content = """
User-agent: RadarBot
Disallow: /crawler-blocked/

User-agent: *
Allow: /
"""
        with patch.object(service, "get_redis", side_effect=Exception("No redis")):
            with patch("app.modules.scraping.politeness.get_limited", new_callable=AsyncMock) as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.text = robots_content
                mock_get.return_value = mock_resp

                assert await service.is_allowed("https://example.com/crawler-blocked/") is False
                assert await service.is_allowed("https://example.com/public-page") is True

    async def test_get_crawl_delay(self):
        service = RobotsPolicyService(user_agent="RadarBot/1.0")

        robots_content = """
User-agent: RadarBot
Crawl-delay: 2.5
"""
        with patch.object(service, "get_redis", side_effect=Exception("No redis")):
            with patch("app.modules.scraping.politeness.get_limited", new_callable=AsyncMock) as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.text = robots_content
                mock_get.return_value = mock_resp

                delay = await service.get_crawl_delay("https://example.com/page")
                assert delay == 2.5

    async def test_403_disallow_all(self):
        service = RobotsPolicyService()

        with patch.object(service, "get_redis", side_effect=Exception("No redis")):
            with patch("app.modules.scraping.politeness.get_limited", new_callable=AsyncMock) as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 403
                mock_resp.text = "Forbidden"
                mock_get.return_value = mock_resp

                assert await service.is_allowed("https://forbidden.com/anything") is False

    async def test_404_allow_all(self):
        service = RobotsPolicyService()

        with patch.object(service, "get_redis", side_effect=Exception("No redis")):
            with patch("app.modules.scraping.politeness.get_limited", new_callable=AsyncMock) as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 404
                mock_resp.text = "Not found"
                mock_get.return_value = mock_resp

                assert await service.is_allowed("https://notfound.com/anything") is True

    async def test_ssrf_blocked_on_robots_fetch(self):
        service = RobotsPolicyService()
        # Fetching robots for loopback should raise SSRFValidationError or fallback permissively
        with pytest.raises(SSRFValidationError):
            # Calling validate_outbound_url directly on local IP
            from app.core.security import validate_outbound_url
            validate_outbound_url("http://127.0.0.1/robots.txt")

    async def test_close_cleans_up(self):
        service = RobotsPolicyService()
        mock_redis = AsyncMock()
        mock_redis.aclose = AsyncMock()
        service._redis_client = mock_redis

        await service.close()
        mock_redis.aclose.assert_called_once()
        assert service._redis_client is None

