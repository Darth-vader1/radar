"""
Unit tests for PipelineOrchestrator control flow, with the database replaced by a fake
session factory and the network replaced by a fake gateway.
"""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.scraping import pipeline as pipeline_module
from app.modules.scraping.adapter_base import (
    CollectionMethod,
    DiscoverySeed,
    RateLimitPolicy,
    RawFetchArtifact,
    SourceAdapter,
    ValidationOutcome,
)
from app.modules.scraping.pipeline import PipelineOrchestrator


class FakeSession:
    def __init__(self, scalar_result=None):
        self.scalar_result = scalar_result
        self.executed = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def scalar(self, *_args, **_kwargs):
        return self.scalar_result

    async def execute(self, stmt, *_args, **_kwargs):
        self.executed.append(stmt)
        return SimpleNamespace(rowcount=1, first=lambda: None, scalar=lambda: None)

    async def commit(self):
        pass

    async def flush(self):
        pass

    def add(self, _obj):
        pass


class TwoPageAdapter(SourceAdapter):
    adapter_key = "two_page_test"
    module_type = "JOB"
    collection_method = CollectionMethod.OFFICIAL_API

    async def discover(self, query_params):
        yield DiscoverySeed(url="https://example.com/page/1")
        yield DiscoverySeed(url="https://example.com/page/2")

    async def extract(self, artifact):
        return [], []

    def normalize(self, item):
        raise AssertionError("not reached")

    def validate(self, normalized):
        return ValidationOutcome(is_valid=True)


def _artifact(seed: DiscoverySeed) -> RawFetchArtifact:
    return RawFetchArtifact(
        seed=seed,
        final_url=seed.url,
        status_code=200,
        content_type="application/json",
        body_text="{}",
        fetched_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def fake_gateway():
    gateway = SimpleNamespace()
    gateway.fetch = AsyncMock(side_effect=lambda seed, rate_policy=None: _artifact(seed))
    gateway.close = AsyncMock()
    return gateway


async def test_run_stages_passes_source_rate_policy_to_every_fetch(monkeypatch, fake_gateway):
    monkeypatch.setattr(pipeline_module, "AsyncSessionLocal", lambda: FakeSession())
    orchestrator = PipelineOrchestrator(gateway=fake_gateway)
    policy = RateLimitPolicy(requests_per_minute=7, respect_robots_txt=False, crawl_budget_pages=10)
    source = SimpleNamespace(id=uuid.uuid4(), slug="two-page", crawl_budget_pages=10, module_type="JOB")

    await orchestrator._run_stages(uuid.uuid4(), source, TwoPageAdapter({}, policy), {}, policy)

    assert fake_gateway.fetch.await_count == 2
    for call in fake_gateway.fetch.await_args_list:
        assert call.kwargs["rate_policy"] is policy


async def test_run_stages_respects_crawl_budget(monkeypatch, fake_gateway):
    monkeypatch.setattr(pipeline_module, "AsyncSessionLocal", lambda: FakeSession())
    orchestrator = PipelineOrchestrator(gateway=fake_gateway)
    policy = RateLimitPolicy(crawl_budget_pages=1)
    source = SimpleNamespace(id=uuid.uuid4(), slug="budget", crawl_budget_pages=1, module_type="JOB")

    await orchestrator._run_stages(uuid.uuid4(), source, TwoPageAdapter({}, policy), {}, policy)

    assert fake_gateway.fetch.await_count == 1


async def test_execute_run_closes_gateway_even_when_run_missing(monkeypatch, fake_gateway):
    monkeypatch.setattr(pipeline_module, "AsyncSessionLocal", lambda: FakeSession(scalar_result=None))
    orchestrator = PipelineOrchestrator(gateway=fake_gateway)

    await orchestrator.execute_run(uuid.uuid4())

    fake_gateway.close.assert_awaited_once()
    fake_gateway.fetch.assert_not_awaited()
