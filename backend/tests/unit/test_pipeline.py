from datetime import datetime, timezone
import hashlib
import json
import pytest
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


class SampleNormalized(BaseModel):
    name: str
    url: str


class MockJobAdapter(SourceAdapter[SampleNormalized]):
    adapter_key = "mock_job_adapter"
    module_type = "JOB"
    collection_method = CollectionMethod.OFFICIAL_API

    async def discover(self, query_params):
        yield DiscoverySeed(url="https://example.com/api/jobs")

    async def extract(self, artifact):
        return [
            ExtractedItem(
                external_id="job_123",
                source_url="https://example.com/jobs/123",
                raw_data={"title": "Backend Python Engineer", "url": "https://example.com/apply/123"},
                discovered_at=datetime.now(timezone.utc),
            )
        ], []

    def normalize(self, item: ExtractedItem) -> SampleNormalized:
        return SampleNormalized(
            name=item.raw_data.get("title", ""),
            url=item.raw_data.get("url", ""),
        )

    def validate(self, normalized: SampleNormalized) -> ValidationOutcome[SampleNormalized]:
        is_valid = bool(normalized.name and normalized.url)
        return ValidationOutcome(
            is_valid=is_valid,
            record=normalized,
            errors=[] if is_valid else ["Missing title or application URL"]
        )


def test_adapter_pipeline_flow():
    adapter = MockJobAdapter(
        source_config={},
        rate_policy=RateLimitPolicy()
    )

    item = ExtractedItem(
        external_id="ext_99",
        source_url="https://example.com/item/99",
        raw_data={"title": "Lead DevOps Architect", "url": "https://example.com/apply/99"},
        discovered_at=datetime.now(timezone.utc),
    )

    # 1. Normalize
    normalized = adapter.normalize(item)
    assert normalized.name == "Lead DevOps Architect"
    assert normalized.url == "https://example.com/apply/99"

    # 2. Validate
    outcome = adapter.validate(normalized)
    assert outcome.is_valid is True
    assert len(outcome.errors) == 0

    # 3. Content hash generation
    content_hash = hashlib.sha256(
        json.dumps(item.raw_data, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    assert len(content_hash) == 64
