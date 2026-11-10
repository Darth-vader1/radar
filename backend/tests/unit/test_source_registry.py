from typing import Any, AsyncIterator, Tuple

from pydantic import BaseModel

from app.modules.scraping.adapter_base import (
    CollectionMethod,
    DiscoverySeed,
    ExtractedItem,
    RateLimitPolicy,
    RawFetchArtifact,
    SourceAdapter,
    ValidationOutcome,
)
from app.modules.scraping.registry import AdapterRegistry, register_adapter


class DummyNormalized(BaseModel):
    title: str


@register_adapter("test_dummy_adapter")
class DummySourceAdapter(SourceAdapter[DummyNormalized]):
    module_type = "JOB"
    collection_method = CollectionMethod.OFFICIAL_API
    required_env_vars = ("TEST_API_KEY", "TEST_SECRET")

    async def discover(self, query_params: dict[str, Any]) -> AsyncIterator[DiscoverySeed]:
        yield DiscoverySeed(url="https://example.com/api/jobs")

    async def extract(self, artifact: RawFetchArtifact) -> Tuple[list[ExtractedItem], list[DiscoverySeed]]:
        return [], []

    def normalize(self, item: ExtractedItem) -> DummyNormalized:
        return DummyNormalized(title=item.raw_data.get("title", ""))

    def validate(self, normalized: DummyNormalized) -> ValidationOutcome[DummyNormalized]:
        return ValidationOutcome(is_valid=bool(normalized.title), record=normalized)


def test_registry_lookup():
    adapter_cls = AdapterRegistry.get("test_dummy_adapter")
    assert adapter_cls is DummySourceAdapter
    assert "test_dummy_adapter" in AdapterRegistry.list_keys()


def test_configuration_check():
    adapter = DummySourceAdapter(
        source_config={},
        rate_policy=RateLimitPolicy(requests_per_minute=30)
    )

    # Missing both
    is_ready, missing = adapter.check_configuration({})
    assert is_ready is False
    assert set(missing) == {"TEST_API_KEY", "TEST_SECRET"}

    # Provided only one
    is_ready, missing = adapter.check_configuration({"TEST_API_KEY": "val"})
    assert is_ready is False
    assert missing == ["TEST_SECRET"]

    # Provided all
    is_ready, missing = adapter.check_configuration({"TEST_API_KEY": "val", "TEST_SECRET": "sec"})
    assert is_ready is True
    assert len(missing) == 0
