import httpx
import pytest

from app.core.security import SSRFValidationError
from app.modules.scraping import gateway as gateway_module
from app.modules.scraping.adapter_base import DiscoverySeed
from app.modules.scraping.gateway import FetcherGateway


async def test_gateway_fetch_http_mock(monkeypatch):
    mock_html = "<html><body><h1>Radar Test</h1></body></html>"

    def handler(request: httpx.Request):
        return httpx.Response(200, text=mock_html, headers={"Content-Type": "text/html; charset=utf-8"})

    async def resolver(host, port):
        return ["93.184.216.34"]

    monkeypatch.setattr(gateway_module, "validate_outbound_url", lambda url, *a, **k: url)
    gateway = FetcherGateway(transport=httpx.MockTransport(handler), resolver=resolver)

    artifact = await gateway.fetch_http(DiscoverySeed(url="https://example.com/test"))

    assert artifact.status_code == 200
    assert artifact.body_text == mock_html
    assert "html" in artifact.content_type
    assert artifact.final_url == "https://example.com/test"


async def test_gateway_blocks_ssrf_direct():
    gateway = FetcherGateway()
    seed = DiscoverySeed(url="http://169.254.169.254/latest/meta-data")

    with pytest.raises(SSRFValidationError):
        await gateway.fetch_http(seed)
