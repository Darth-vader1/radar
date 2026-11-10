from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, AsyncIterator, Generic, Optional, Tuple, TypeVar

from pydantic import BaseModel

NormalizedT = TypeVar("NormalizedT", bound=BaseModel)


class CollectionMethod(StrEnum):
    OFFICIAL_API = "OFFICIAL_API"
    RSS_FEED = "RSS_FEED"
    STRUCTURED_DATA = "STRUCTURED_DATA"
    DIRECTORY_INTEGRATION = "DIRECTORY_INTEGRATION"
    HTML_SCRAPE = "HTML_SCRAPE"
    JS_RENDERED = "JS_RENDERED"


@dataclass(frozen=True)
class RateLimitPolicy:
    requests_per_minute: int = 30
    max_concurrency: int = 2
    respect_robots_txt: bool = True
    crawl_budget_pages: int = 100
    request_timeout_seconds: float = 20.0


@dataclass(frozen=True)
class DiscoverySeed:
    url: str
    method: str = "GET"
    params: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    body: Any = None
    requires_js: bool = False
    cursor_metadata: dict[str, Any] = field(default_factory=dict)
    rate_policy: Optional[RateLimitPolicy] = None


@dataclass
class RawFetchArtifact:
    seed: DiscoverySeed
    final_url: str
    status_code: int
    content_type: str
    body_text: str
    fetched_at: datetime
    response_headers: dict[str, str] = field(default_factory=dict)


@dataclass
class ExtractedItem:
    external_id: Optional[str]
    source_url: str
    raw_data: dict[str, Any]
    discovered_at: datetime


@dataclass
class ValidationOutcome(Generic[NormalizedT]):
    is_valid: bool
    record: Optional[NormalizedT] = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class SourceAdapter(ABC, Generic[NormalizedT]):
    """
    Standard interface that every discovery source adapter MUST implement.
    Never hardcode source-specific extraction logic into the core discovery engine.
    """

    adapter_key: str
    module_type: str  # "BUSINESS" | "JOB" | "EVENT"
    collection_method: CollectionMethod
    required_env_vars: Tuple[str, ...] = ()

    def __init__(self, source_config: dict[str, Any], rate_policy: RateLimitPolicy) -> None:
        self.source_config = source_config
        self.rate_policy = rate_policy

    def check_configuration(self, env: dict[str, str]) -> Tuple[bool, list[str]]:
        """Returns (is_configured, missing_env_vars)."""
        missing = [k for k in self.required_env_vars if not env.get(k)]
        return (len(missing) == 0, missing)

    @abstractmethod
    def discover(self, query_params: dict[str, Any]) -> AsyncIterator[DiscoverySeed]:
        """Implemented as an async generator (`async def ... yield`). Yields initial API requests, feed URLs, or paginated listing URLs within crawl budget."""
        pass

    @abstractmethod
    async def extract(self, artifact: RawFetchArtifact) -> Tuple[list[ExtractedItem], list[DiscoverySeed]]:
        """Extracts raw structured records AND optional next-page DiscoverySeeds."""
        pass

    @abstractmethod
    def normalize(self, item: ExtractedItem) -> NormalizedT:
        """Maps source-specific keys into canonical domain schemas."""
        pass

    @abstractmethod
    def validate(self, normalized: NormalizedT) -> ValidationOutcome[NormalizedT]:
        """Enforces domain invariants (non-empty fields, valid URLs, non-fabricated data)."""
        pass
