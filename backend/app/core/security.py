import hashlib
import ipaddress
import secrets
import socket
import time
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional
from urllib.parse import urlparse

import bcrypt
import jwt

from app.core.config import settings


class SSRFValidationError(Exception):
    """Raised when an outbound URL violates SSRF security boundaries."""
    pass


class HostResolutionError(SSRFValidationError):
    """The host name could not be resolved (usually transient: DNS hiccup, network blip)."""


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8")[:72], hashed_password.encode("utf-8"))
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    # Truncate to 72 bytes as per bcrypt specification
    pw_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pw_bytes, salt).decode("utf-8")


def create_access_token(
    subject: str | Any,
    expires_delta: Optional[timedelta] = None,
    token_version: int = 0,
) -> str:
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode = {
        "exp": expire,
        "iat": now,
        "sub": str(subject),
        "type": "access",
        # Compared with users.token_version on every request; bumping it revokes this token.
        "ver": token_version,
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(
    subject: str | Any,
    expires_delta: Optional[timedelta] = None,
    jti: Optional[str] = None,
    family_id: Optional[str] = None,
) -> str:
    """
    Refresh tokens carry a `jti` (row id in refresh_tokens) and a `fam` (rotation family).
    The server-side row is what makes them revocable; the JWT alone is not trusted.
    """
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))
    to_encode = {
        "exp": expire,
        "iat": now,
        "sub": str(subject),
        "type": "refresh",
        "jti": jti or secrets.token_hex(16),
        "fam": family_id or secrets.token_hex(16),
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return {}


def generate_api_key(prefix: str = "radar_live_") -> tuple[str, str, str]:
    """
    Generates a secure API key.
    Returns: (raw_key, key_prefix, sha256_hash)
    The raw_key is returned once to the user; only sha256_hash is stored in DB.
    """
    random_part = secrets.token_urlsafe(32)
    raw_key = f"{prefix}{random_part}"
    key_prefix = raw_key[:12]
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return raw_key, key_prefix, key_hash


def verify_api_key(raw_key: str, stored_hash: str) -> bool:
    candidate_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return secrets.compare_digest(candidate_hash, stored_hash)


# --- SSRF & Network Security Guard ---

PROHIBITED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),   # Link-local & cloud metadata
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def validate_url_shape(url: str, allowed_ports: Optional[List[int]] = None) -> tuple[str, str, int]:
    """
    Checks scheme, hostname, embedded credentials and port without touching the network.
    Returns (scheme, hostname, port).
    """
    if allowed_ports is None:
        allowed_ports = settings.ALLOWED_OUTBOUND_PORTS

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise SSRFValidationError(f"Invalid URL scheme: '{scheme}'. Only HTTP and HTTPS are permitted.")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFValidationError("URL lacks a valid hostname.")

    # Reject URLs with userinfo (e.g. http://user:pass@host)
    if parsed.username or parsed.password:
        raise SSRFValidationError("URLs with embedded authentication credentials are prohibited.")

    try:
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError:
        raise SSRFValidationError("URL has an invalid port.")
    if port not in allowed_ports:
        raise SSRFValidationError(f"Port {port} is not in allowed outbound ports {allowed_ports}.")

    return scheme, hostname, port


def check_resolved_ip(hostname: str, ip_str: str) -> None:
    """Raises SSRFValidationError if ip_str is loopback, private, link-local, metadata, etc."""
    try:
        ip = ipaddress.ip_address(ip_str.split("%", 1)[0])  # strip IPv6 zone id
    except ValueError:
        raise SSRFValidationError(f"Invalid IP address resolved: '{ip_str}'")

    # Unwrap IPv4-mapped IPv6 (::ffff:127.0.0.1) so it is judged as the IPv4 it really is.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped

    if (
        ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast
        or ip.is_reserved or ip.is_unspecified
    ):
        raise SSRFValidationError(
            f"Host '{hostname}' resolved to prohibited address '{ip_str}' (private/loopback/metadata)."
        )

    for prohibited in PROHIBITED_NETWORKS:
        if ip.version == prohibited.version and ip in prohibited:
            raise SSRFValidationError(
                f"Host '{hostname}' resolved to prohibited network block '{prohibited}': {ip_str}"
            )


# --- Short-lived DNS cache --------------------------------------------------------------
# Every outbound request resolves its host twice (pre-flight check here, then the pinned
# connection in app.core.http), and enrichment makes several requests per site. On slow
# resolvers (seconds per lookup) that dominates crawl time. Answers are cached briefly; this
# stays SSRF-safe because every cached address is re-validated on each use and connections
# are pinned to exactly the address that was validated.
DNS_CACHE_TTL_SECONDS = 60.0
_DNS_CACHE_MAX = 2048
_dns_cache: dict[tuple[str, int], tuple[float, list[str]]] = {}


def _dns_cache_get(host: str, port: int) -> Optional[list[str]]:
    hit = _dns_cache.get((host.lower(), port))
    if hit and hit[0] > time.monotonic():
        return hit[1]
    return None


def _dns_cache_put(host: str, port: int, addresses: list[str]) -> None:
    if len(_dns_cache) >= _DNS_CACHE_MAX:
        _dns_cache.clear()
    _dns_cache[(host.lower(), port)] = (time.monotonic() + DNS_CACHE_TTL_SECONDS, addresses)


def clear_dns_cache() -> None:
    _dns_cache.clear()


def resolve_host(hostname: str, port: int) -> list[str]:
    """Resolves (with the short-lived cache) to a de-duplicated list of IP strings."""
    cached = _dns_cache_get(hostname, port)
    if cached is not None:
        return cached
    try:
        infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise HostResolutionError(f"Could not resolve host '{hostname}': {e}")
    addresses = list(dict.fromkeys(str(info[4][0]) for info in infos))
    _dns_cache_put(hostname, port, addresses)
    return addresses


def validate_outbound_url(url: str, allowed_ports: Optional[List[int]] = None) -> str:
    """
    Strictly validates that an outbound URL does not resolve to private,
    loopback, link-local, or cloud metadata IP addresses.

    NOTE: this is a pre-flight check only. The connection itself must go through
    app.core.http.SSRFSafeTransport, which pins the connection to the validated IP;
    otherwise a DNS-rebinding host can resolve differently at connect time.
    """
    if not settings.ENFORCE_SSRF_PROTECTION:
        return url

    _, hostname, port = validate_url_shape(url, allowed_ports)

    # DNS resolution and IP range validation
    for ip in resolve_host(hostname, port):
        check_resolved_ip(hostname, ip)

    return url
