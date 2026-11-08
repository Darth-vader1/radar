"""
SSRF-safe outbound HTTP for every crawler/enricher request.

Why a transport and not just validate_outbound_url():
  * validate-then-connect is a TOCTOU race. A DNS-rebinding host can resolve to a public IP
    during validation and to 127.0.0.1 / 169.254.169.254 when httpx connects. This transport
    resolves once, validates every address, and connects to that exact IP (Host header and
    TLS SNI/certificate checks still use the real hostname).
  * It runs for every request the client sends, including each redirect hop, so
    `follow_redirects=True` can no longer be used to bounce into the internal network.

Use `safe_async_client()` instead of `httpx.AsyncClient()` for anything that fetches
URLs that come from the internet, adapters, or users.
"""
import asyncio
import socket
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

import httpx

from app.core.config import settings
from app.core.security import SSRFValidationError, check_resolved_ip, validate_url_shape

Resolver = Callable[[str, int], Awaitable[list[str]]]


class ResponseTooLargeError(Exception):
    """Raised when a response body exceeds the configured byte limit."""

    def __init__(self, url: str, limit: int):
        self.url = url
        self.limit = limit
        super().__init__(f"Response from {url} exceeded the {limit} byte limit")


async def system_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SSRFValidationError(f"Could not resolve host '{host}': {exc}") from exc
    # Preserve resolver order, drop duplicates.
    return list(dict.fromkeys(info[4][0] for info in infos))


class SSRFSafeTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        inner: Optional[httpx.AsyncBaseTransport] = None,
        resolver: Optional[Resolver] = None,
    ) -> None:
        self._inner = inner or httpx.AsyncHTTPTransport(retries=0)
        self._resolver = resolver or system_resolver

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if not settings.ENFORCE_SSRF_PROTECTION:
            return await self._inner.handle_async_request(request)

        _, host, port = validate_url_shape(str(request.url))
        addresses = await self._resolver(host, port)
        if not addresses:
            raise SSRFValidationError(f"Host '{host}' did not resolve to any address.")
        # Every address must be public: rejecting mixed answers stops "one good, one internal" tricks.
        for ip in addresses:
            check_resolved_ip(host, ip)

        pinned_ip = addresses[0].split("%", 1)[0]
        extensions = dict(request.extensions)
        if request.url.scheme == "https":
            extensions["sni_hostname"] = host

        pinned = httpx.Request(
            method=request.method,
            url=request.url.copy_with(host=pinned_ip),
            headers=request.headers,  # keeps the original Host header
            stream=request.stream,
            extensions=extensions,
        )
        return await self._inner.handle_async_request(pinned)

    async def aclose(self) -> None:
        await self._inner.aclose()


def safe_async_client(
    *,
    transport: Optional[httpx.AsyncBaseTransport] = None,
    resolver: Optional[Resolver] = None,
    **kwargs,
) -> httpx.AsyncClient:
    """
    httpx.AsyncClient whose every request (including redirects) is SSRF-checked and IP-pinned.
    `transport` replaces the network layer (used by tests); the SSRF layer always wraps it.
    """
    kwargs.setdefault("timeout", settings.DEFAULT_REQUEST_TIMEOUT)
    kwargs.setdefault("headers", {"User-Agent": settings.HTTP_USER_AGENT})
    kwargs.setdefault("max_redirects", settings.MAX_REDIRECT_HOPS)
    kwargs.pop("verify", None)  # TLS verification is never optional here
    return httpx.AsyncClient(transport=SSRFSafeTransport(inner=transport, resolver=resolver), **kwargs)


@dataclass
class LimitedResponse:
    status_code: int
    url: str
    headers: httpx.Headers
    content: bytes
    encoding: str
    truncated: bool = False

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding, errors="replace")

    @property
    def is_redirect(self) -> bool:
        return self.status_code in (301, 302, 303, 307, 308) and "location" in self.headers


async def read_limited(response: httpx.Response, max_bytes: int, truncate: bool = False) -> LimitedResponse:
    """
    Reads a *streamed* response body up to max_bytes. Raises ResponseTooLargeError when the
    body is larger, unless truncate=True (then the first max_bytes are kept).
    """
    declared = response.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes and not truncate:
        raise ResponseTooLargeError(str(response.url), max_bytes)

    chunks: list[bytes] = []
    size = 0
    truncated = False
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > max_bytes:
            if not truncate:
                raise ResponseTooLargeError(str(response.url), max_bytes)
            chunks.append(chunk[: max_bytes - (size - len(chunk))])
            truncated = True
            break
        chunks.append(chunk)

    return LimitedResponse(
        status_code=response.status_code,
        url=str(response.url),
        headers=response.headers,
        content=b"".join(chunks),
        encoding=response.charset_encoding or "utf-8",
        truncated=truncated,
    )


async def get_limited(
    client: httpx.AsyncClient,
    url: str,
    max_bytes: Optional[int] = None,
    truncate: bool = False,
    **kwargs,
) -> LimitedResponse:
    """GET url through client, streaming the body with a size cap."""
    async with client.stream("GET", url, **kwargs) as response:
        return await read_limited(response, max_bytes or settings.MAX_RESPONSE_BYTES, truncate=truncate)
