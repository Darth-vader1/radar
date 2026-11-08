"""
FetcherGateway tests. The network is an httpx.MockTransport and DNS is a fake resolver,
but the real SSRFSafeTransport sits between them, so SSRF checks, IP pinning, redirects,
size limits and politeness all run for real.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.security import SSRFValidationError, check_resolved_ip, validate_url_shape
from app.modules.scraping.adapter_base import DiscoverySeed, RateLimitPolicy
from app.modules.scraping import gateway as gateway_module
from app.modules.scraping.gateway import (
    FetcherGateway,
    FetchError,
    RateLimitExceededError,
    RobotsDisallowedError,
)
from app.modules.scraping.politeness import RobotsPolicyService, TokenBucketRateLimiter

PUBLIC_IP = "93.184.216.34"


class FakeNet:
    """Fake DNS + HTTP: maps hostnames to IPs and "host/path" to responses."""

    def __init__(self):
        self.dns = {"example.com": [PUBLIC_IP], "cdn.example.net": ["151.101.1.1"]}
        self.routes = {}
        self.seen = []  # (pinned_url, host_header, sni)

    async def resolve(self, host, port):
        if host not in self.dns:
            raise SSRFValidationError(f"Could not resolve host '{host}'")
        return self.dns[host]

    def resolve_sync_check(self, url, allowed_ports=None):
        _, host, port = validate_url_shape(url, allowed_ports)
        if host not in self.dns:
            # IP literals resolve to themselves
            self.dns.setdefault(host, [host])
        for ip in self.dns[host]:
            check_resolved_ip(host, ip)
        return url

    def handler(self, request: httpx.Request) -> httpx.Response:
        host = request.headers["host"]
        self.seen.append((str(request.url), host, request.extensions.get("sni_hostname")))
        key = f"{host}{request.url.path}"
        if key not in self.routes:
            return httpx.Response(404, text="not found")
        route = self.routes[key]
        return route(request) if callable(route) else route


@pytest.fixture
def net(monkeypatch):
    fake = FakeNet()
    monkeypatch.setattr(gateway_module, "validate_outbound_url", fake.resolve_sync_check)
    return fake


@pytest.fixture
def mock_robots_service():
    service = MagicMock(spec=RobotsPolicyService)
    service.is_allowed = AsyncMock(return_value=True)
    service.get_crawl_delay = AsyncMock(return_value=None)
    service.close = AsyncMock()
    return service


@pytest.fixture
def mock_rate_limiter():
    limiter = MagicMock(spec=TokenBucketRateLimiter)
    limiter.acquire = AsyncMock(return_value=True)
    limiter.close = AsyncMock()
    return limiter


@pytest.fixture
def gateway(net, mock_robots_service, mock_rate_limiter):
    return FetcherGateway(
        robots_service=mock_robots_service,
        rate_limiter=mock_rate_limiter,
        enforce_robots=True,
        enforce_rate_limit=True,
        default_requests_per_minute=30,
        rate_limit_timeout=2.0,
        max_response_bytes=10_000,
        transport=httpx.MockTransport(net.handler),
        resolver=net.resolve,
    )


def html(text, status=200, **headers):
    return httpx.Response(status, text=text, headers={"content-type": "text/html; charset=utf-8", **headers})


class TestFetcherGateway:

    async def test_fetch_http_success(self, gateway, net):
        net.routes["example.com/test"] = html("<html><body>Hello World</body></html>")
        seed = DiscoverySeed(url="https://example.com/test", method="GET")

        artifact = await gateway.fetch(seed)

        assert artifact.status_code == 200
        assert artifact.final_url == "https://example.com/test"
        assert "Hello World" in artifact.body_text
        gateway.robots_service.is_allowed.assert_called_once_with("https://example.com/test")
        gateway.rate_limiter.acquire.assert_called_once_with(
            domain="example.com", requests_per_minute=30, timeout=2.0
        )

    async def test_connection_is_pinned_to_validated_ip(self, gateway, net):
        net.routes["example.com/pin"] = html("ok")

        await gateway.fetch(DiscoverySeed(url="https://example.com/pin"), enforce_robots=False)

        pinned_url, host_header, sni = net.seen[0]
        assert pinned_url == f"https://{PUBLIC_IP}/pin"
        assert host_header == "example.com"
        assert sni == "example.com"

    async def test_robots_disallowed_raises_exception(self, gateway):
        seed = DiscoverySeed(url="https://example.com/disallowed")
        gateway.robots_service.is_allowed = AsyncMock(return_value=False)

        with pytest.raises(RobotsDisallowedError) as exc_info:
            await gateway.fetch(seed)

        assert exc_info.value.url == "https://example.com/disallowed"
        assert "Robots.txt disallows crawling" in str(exc_info.value)
        gateway.rate_limiter.acquire.assert_not_called()

    async def test_robots_bypassed_when_enforce_robots_is_false(self, gateway, net):
        net.routes["example.com/allowed-anyway"] = html("Bypassed robots")
        gateway.robots_service.is_allowed = AsyncMock(return_value=False)

        artifact = await gateway.fetch(DiscoverySeed(url="https://example.com/allowed-anyway"), enforce_robots=False)

        assert artifact.status_code == 200
        gateway.robots_service.is_allowed.assert_not_called()

    async def test_robots_bypassed_when_rate_policy_respect_robots_is_false(self, gateway, net):
        net.routes["example.com/policy-bypassed"] = html("OK")
        policy = RateLimitPolicy(respect_robots_txt=False, requests_per_minute=45)

        artifact = await gateway.fetch(DiscoverySeed(url="https://example.com/policy-bypassed"), rate_policy=policy)

        assert artifact.status_code == 200
        gateway.robots_service.is_allowed.assert_not_called()
        gateway.rate_limiter.acquire.assert_called_once_with(
            domain="example.com", requests_per_minute=45, timeout=2.0
        )

    async def test_robots_bypassed_when_seed_rate_policy_respect_robots_is_false(self, gateway, net):
        net.routes["example.com/seed-policy-bypassed"] = html("OK")
        policy = RateLimitPolicy(respect_robots_txt=False, requests_per_minute=50)
        seed = DiscoverySeed(url="https://example.com/seed-policy-bypassed", rate_policy=policy)

        artifact = await gateway.fetch(seed)

        assert artifact.status_code == 200
        gateway.robots_service.is_allowed.assert_not_called()
        gateway.rate_limiter.acquire.assert_called_once_with(
            domain="example.com", requests_per_minute=50, timeout=2.0
        )

    async def test_rate_limit_exceeded_raises_error(self, gateway):
        gateway.rate_limiter.acquire = AsyncMock(return_value=False)

        with pytest.raises(RateLimitExceededError) as exc_info:
            await gateway.fetch(DiscoverySeed(url="https://example.com/rate-limited"))

        assert exc_info.value.domain == "example.com"
        assert exc_info.value.requests_per_minute == 30
        assert exc_info.value.timeout == 2.0
        assert "Rate limit exceeded or timed out" in str(exc_info.value)

    async def test_crawl_delay_adjusts_effective_rpm(self, gateway, net):
        net.routes["example.com/slow-crawl"] = html("Slow")
        # 5 seconds delay => max 12 requests per minute
        gateway.robots_service.get_crawl_delay = AsyncMock(return_value=5.0)

        await gateway.fetch(DiscoverySeed(url="https://example.com/slow-crawl"), rate_policy=RateLimitPolicy(requests_per_minute=60))

        gateway.rate_limiter.acquire.assert_called_once_with(
            domain="example.com", requests_per_minute=12, timeout=2.0
        )

    async def test_ssrf_initial_url_blocked(self, gateway):
        seed = DiscoverySeed(url="http://169.254.169.254/latest/meta-data")

        with pytest.raises(SSRFValidationError):
            await gateway.fetch(seed, enforce_robots=False, enforce_rate_limit=False)

    async def test_ssrf_redirect_hop_blocked(self, gateway, net):
        net.routes["example.com/open-redirect"] = httpx.Response(302, headers={"location": "http://127.0.0.1:80/internal"})

        with pytest.raises(SSRFValidationError):
            await gateway.fetch(DiscoverySeed(url="https://example.com/open-redirect"), enforce_robots=False, enforce_rate_limit=False)

        assert all("127.0.0.1" not in url for url, _, _ in net.seen)

    async def test_dns_rebinding_blocked_at_connect_time(self, gateway, net, monkeypatch):
        """Pre-flight check sees a public IP; the connect-time lookup returns loopback."""
        monkeypatch.setattr(gateway_module, "validate_outbound_url", lambda url, *a, **k: url)
        net.dns["rebind.example.com"] = ["127.0.0.1"]
        net.routes["rebind.example.com/"] = html("internal secrets")

        with pytest.raises(SSRFValidationError):
            await gateway.fetch(DiscoverySeed(url="http://rebind.example.com/"), enforce_robots=False, enforce_rate_limit=False)

        assert net.seen == []  # never connected

    async def test_mixed_dns_answer_with_internal_address_blocked(self, gateway, net):
        net.dns["mixed.example.com"] = ["151.101.1.1", "10.0.0.5"]

        with pytest.raises(SSRFValidationError):
            await gateway.fetch(DiscoverySeed(url="https://mixed.example.com/"), enforce_robots=False, enforce_rate_limit=False)

    async def test_ipv4_mapped_ipv6_loopback_blocked(self, gateway, net):
        net.dns["mapped.example.com"] = ["::ffff:127.0.0.1"]

        with pytest.raises(SSRFValidationError):
            await gateway.fetch(DiscoverySeed(url="https://mapped.example.com/"), enforce_robots=False, enforce_rate_limit=False)

    async def test_safe_redirect_is_followed(self, gateway, net):
        net.routes["example.com/old"] = httpx.Response(301, headers={"location": "https://cdn.example.net/new"})
        net.routes["cdn.example.net/new"] = html("moved here")

        artifact = await gateway.fetch(DiscoverySeed(url="https://example.com/old"), enforce_robots=False, enforce_rate_limit=False)

        assert artifact.final_url == "https://cdn.example.net/new"
        assert artifact.body_text == "moved here"

    async def test_response_over_size_limit_rejected(self, gateway, net):
        net.routes["example.com/huge"] = html("x" * 50_000)

        with pytest.raises(FetchError, match="byte limit"):
            await gateway.fetch(DiscoverySeed(url="https://example.com/huge"), enforce_robots=False, enforce_rate_limit=False)

    async def test_binary_content_type_rejected(self, gateway, net):
        net.routes["example.com/file.zip"] = httpx.Response(200, content=b"PK\x03\x04", headers={"content-type": "application/zip"})

        with pytest.raises(FetchError, match="content type"):
            await gateway.fetch(DiscoverySeed(url="https://example.com/file.zip"), enforce_robots=False, enforce_rate_limit=False)

    async def test_fetch_rendered_fallback_to_http(self, gateway, net):
        net.routes["example.com/js-rendered"] = html("Fallback text")
        seed = DiscoverySeed(url="https://example.com/js-rendered", requires_js=True)

        # Force Playwright import failure to trigger HTTP fallback
        with patch.dict("sys.modules", {"playwright.async_api": None}):
            artifact = await gateway.fetch(seed)

        assert artifact.body_text == "Fallback text"

    async def test_close_cleans_up_resources(self, gateway):
        await gateway.close()
        gateway.robots_service.close.assert_called_once()
        gateway.rate_limiter.close.assert_called_once()
