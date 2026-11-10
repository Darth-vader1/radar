import hashlib
import json
import logging
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, cast

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult

from app.core.logging import bind_context, log_context
from app.database.session import AsyncSessionLocal
from app.models.source import (
    DeadLetterTask,
    ExtractedRecord,
    RunStatus,
    ScrapingTask,
    Source,
    SourceRun,
    TaskStatus,
)
from app.modules.scraping.adapter_base import (
    DiscoverySeed,
    ExtractedItem,
    RateLimitPolicy,
    SourceAdapter,
)
from app.modules.scraping.gateway import FetcherGateway, RobotsDisallowedError
from app.modules.scraping.politeness import RobotsPolicyService, TokenBucketRateLimiter
from app.modules.scraping.registry import AdapterRegistry

logger = logging.getLogger("radar.scraping.pipeline")

# Runs a worker may (re)start. RUNNING is included so a task redelivered after a worker
# crash (acks_late) resumes instead of being dropped.
ACTIVE_RUN_STATUSES = (RunStatus.QUEUED.value, RunStatus.RUNNING.value)

# search_params key carrying serialized seeds for a dead-letter retry run.
RETRY_SEEDS_KEY = "__retry_seeds"

_SENSITIVE_HEADER_HINTS = ("authorization", "cookie", "key", "token", "secret", "password", "signature")


def seed_to_snapshot(seed: DiscoverySeed) -> dict[str, Any]:
    """
    JSON-safe copy of a seed for the dead-letter queue. Credential-bearing headers are
    dropped: DLQ rows are visible to admins via the API and must never hold secrets.
    """
    safe_headers = {
        k: v for k, v in (seed.headers or {}).items()
        if not any(hint in k.lower() for hint in _SENSITIVE_HEADER_HINTS)
    }
    return json.loads(json.dumps({
        "url": seed.url,
        "method": seed.method,
        "params": seed.params,
        "headers": safe_headers,
        "body": seed.body,
        "requires_js": seed.requires_js,
        "cursor_metadata": seed.cursor_metadata,
        "headers_redacted": len(safe_headers) != len(seed.headers or {}),
    }, default=str))


def seed_from_snapshot(snapshot: dict[str, Any]) -> DiscoverySeed:
    return DiscoverySeed(
        url=snapshot["url"],
        method=snapshot.get("method", "GET"),
        params=snapshot.get("params") or {},
        headers=snapshot.get("headers") or {},
        body=snapshot.get("body"),
        requires_js=bool(snapshot.get("requires_js", False)),
        cursor_metadata=snapshot.get("cursor_metadata") or {},
    )


def _seed_key(method: str, url: str, body: Any) -> tuple[str, str, str]:
    return (method.upper(), url, json.dumps(body, sort_keys=True, default=str))


class PipelineOrchestrator:
    """
    Executes the 11-stage ingestion & verification pipeline for a given SourceRun.
    Stages:
      1. DISCOVER -> 2. FETCH -> 3. EXTRACT -> 4. NORMALIZE -> 5. VALIDATE ->
      6. DEDUPLICATE -> 7. ENRICH -> 8. AI_CLASSIFY -> 9. STORE -> 10. INDEX -> 11. DISPLAY
    """

    def __init__(
        self,
        gateway: Optional[FetcherGateway] = None,
        rate_limiter: Optional[TokenBucketRateLimiter] = None,
        robots_service: Optional[RobotsPolicyService] = None,
    ):
        self.rate_limiter = rate_limiter or TokenBucketRateLimiter()
        self.robots_service = robots_service or RobotsPolicyService()
        self.gateway = gateway or FetcherGateway(
            robots_service=self.robots_service,
            rate_limiter=self.rate_limiter,
        )

    async def execute_run(self, source_run_id: uuid.UUID) -> None:
        # Every log line emitted during this run (ours and libraries') carries the run id.
        with log_context(run_id=source_run_id):
            try:
                await self._execute_run(source_run_id)
            finally:
                # Release Redis connections held by robots/rate-limit services.
                await self.gateway.close()

    async def _execute_run(self, source_run_id: uuid.UUID) -> None:
        async with AsyncSessionLocal() as session:
            run = await session.scalar(select(SourceRun).where(SourceRun.id == source_run_id))
            if not run:
                logger.error("SourceRun %s not found.", source_run_id)
                return
            if run.status not in ACTIVE_RUN_STATUSES:
                # Cancelled before a worker picked it up, already finished, or reaped.
                logger.info("SourceRun %s is %s; skipping execution.", source_run_id, run.status)
                return

            source = await session.scalar(select(Source).where(Source.id == run.source_id))
            if not source:
                logger.error("Source %s not found for run %s", run.source_id, source_run_id)
                return

            bind_context(source=source.slug)  # scoped by the run's log_context
            adapter_cls = AdapterRegistry.get(source.adapter_key)
            if not adapter_cls:
                err_msg = f"No adapter registered with key '{source.adapter_key}'"
                logger.error(err_msg)
                run.status = RunStatus.FAILED.value
                run.error_summary = err_msg
                run.finished_at = datetime.now(timezone.utc)
                await session.commit()
                return

            rate_policy = RateLimitPolicy(
                requests_per_minute=source.rate_limit_rpm,
                max_concurrency=source.max_concurrency,
                respect_robots_txt=source.respect_robots_txt,
                crawl_budget_pages=source.crawl_budget_pages,
            )
            adapter = adapter_cls(source_config=source.adapter_config, rate_policy=rate_policy)

            # Atomic claim: only a QUEUED run (or a RUNNING one being redelivered after a
            # worker crash) can be started; a concurrent cancel wins the race.
            claimed = await session.execute(
                update(SourceRun)
                .where(SourceRun.id == source_run_id, SourceRun.status.in_(ACTIVE_RUN_STATUSES))
                .values(status=RunStatus.RUNNING.value, started_at=datetime.now(timezone.utc))
                .returning(SourceRun.id)
            )
            if claimed.first() is None:
                await session.rollback()
                logger.info("SourceRun %s was cancelled or finished before it started.", source_run_id)
                return
            await session.commit()

        # Execute discovery loop
        try:
            await self._run_stages(source_run_id, source, adapter, run.search_params or {}, rate_policy)
        except Exception as e:
            logger.exception("Critical failure executing run %s: %s", source_run_id, e)
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(SourceRun)
                    .where(SourceRun.id == source_run_id, SourceRun.status == RunStatus.RUNNING.value)
                    .values(
                        status=RunStatus.FAILED.value,
                        error_summary=str(e),
                        finished_at=datetime.now(timezone.utc),
                    )
                )
                await session.commit()

    async def _run_stages(
        self,
        source_run_id: uuid.UUID,
        source: Source,
        adapter: SourceAdapter,
        search_params: dict[str, Any],
        rate_policy: RateLimitPolicy,
    ) -> None:
        seeds_queue: List[DiscoverySeed] = []
        pages_fetched_count = 0
        records_extracted_count = 0
        records_created_count = 0
        records_updated_count = 0
        records_dedup_count = 0
        errors_count = 0
        robots_skipped_count = 0

        cancelled = False
        retry_snapshots = search_params.get(RETRY_SEEDS_KEY)
        original_params = {k: v for k, v in search_params.items() if k != RETRY_SEEDS_KEY}

        # --- STAGE 1: DISCOVER ---
        if retry_snapshots:
            # Dead-letter retry: re-process only the seeds that failed previously.
            logger.info("[Stage 1: DISCOVER] Retrying %d dead-lettered seed(s) for %s", len(retry_snapshots), source.slug)
            seeds_queue = await self._resolve_retry_seeds(adapter, original_params, retry_snapshots)
        else:
            logger.info("[Stage 1: DISCOVER] Initiating discovery for source %s", source.slug)
            try:
                async for seed in adapter.discover(search_params):
                    seeds_queue.append(seed)
                    if len(seeds_queue) >= source.crawl_budget_pages:
                        break
            except Exception as e:
                logger.error("Discovery error on source %s: %s", source.slug, e)
                errors_count += 1
                await self._record_task_error(
                    source_run_id, source.id, "DISCOVER", e, {"search_params": original_params}
                )

        # Process discovery seeds within crawl budget
        processed_seeds = 0
        while seeds_queue and processed_seeds < source.crawl_budget_pages:
            # Cooperative cancellation: checked before every page so a cancel takes
            # effect within one fetch instead of after the whole crawl.
            if await self._is_cancelled(source_run_id):
                logger.info("SourceRun %s cancelled; stopping after %d page(s).", source_run_id, processed_seeds)
                cancelled = True
                break

            seed = seeds_queue.pop(0)
            processed_seeds += 1

            # --- STAGE 2: FETCH (Politeness + Rate Limiting + SSRF Check) ---
            try:
                artifact = await self.gateway.fetch(seed, rate_policy=rate_policy)
                pages_fetched_count += 1
            except RobotsDisallowedError as rde:
                logger.warning("[Robots.txt Disallowed] Skipping %s: %s", seed.url, rde)
                robots_skipped_count += 1
                continue
            except Exception as fetch_exc:
                logger.warning("Fetch failed for %s: %s", seed.url, fetch_exc)
                errors_count += 1
                await self._record_task_error(
                    source_run_id, source.id, "FETCH", fetch_exc,
                    {"url": seed.url, "seed": seed_to_snapshot(seed), "search_params": original_params},
                )
                continue

            # --- STAGE 3: EXTRACT ---
            try:
                items, next_seeds = await adapter.extract(artifact)
                # Queue next pagination seeds if budget allows
                for next_seed in next_seeds:
                    if (len(seeds_queue) + processed_seeds) < source.crawl_budget_pages:
                        seeds_queue.append(next_seed)

            except Exception as extract_exc:
                logger.warning("Extract failed for %s: %s", artifact.final_url, extract_exc)
                errors_count += 1
                await self._record_task_error(
                    source_run_id, source.id, "EXTRACT", extract_exc,
                    {"url": artifact.final_url, "seed": seed_to_snapshot(seed), "search_params": original_params},
                )
                continue

            # Process extracted items through Stages 4 to 11
            for item in items:
                records_extracted_count += 1
                try:
                    outcome = await self._process_single_item(source_run_id, source, adapter, item)
                    if outcome == "CREATED":
                        records_created_count += 1
                    elif outcome == "UPDATED":
                        records_updated_count += 1
                    elif outcome == "DEDUPLICATED":
                        records_dedup_count += 1
                    elif outcome in ("STORE_FAILED", "VALIDATION_FAILED"):
                        errors_count += 1
                except Exception as item_exc:
                    logger.warning("Item pipeline processing error: %s", item_exc)
                    errors_count += 1

            # Update progress checkpoint periodically
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(SourceRun)
                    .where(SourceRun.id == source_run_id)
                    .values(
                        pages_fetched=pages_fetched_count,
                        records_extracted=records_extracted_count,
                        records_created=records_created_count,
                        records_updated=records_updated_count,
                        records_deduplicated=records_dedup_count,
                        errors_count=errors_count,
                    )
                )
                await session.commit()

        # Finalize run status
        final_status = (
            RunStatus.COMPLETED.value
            if errors_count == 0
            else (RunStatus.PARTIAL_FAILURE.value if records_extracted_count > 0 else RunStatus.FAILED.value)
        )
        summary_parts = []
        if errors_count:
            summary_parts.append(f"Processed with {errors_count} item/page errors.")
        if robots_skipped_count:
            summary_parts.append(f"{robots_skipped_count} page(s) skipped because robots.txt disallows them.")
            if pages_fetched_count == 0:
                # Nothing could be collected at all: don't report that as a success.
                final_status = RunStatus.FAILED.value
                summary_parts.append(
                    "No pages could be fetched. Check the source's robots.txt, or disable "
                    "'respect robots.txt' for this source if you are permitted to use it."
                )
        error_summary = " ".join(summary_parts) or None

        async with AsyncSessionLocal() as session:
            counters = dict(
                pages_fetched=pages_fetched_count,
                records_extracted=records_extracted_count,
                records_created=records_created_count,
                records_updated=records_updated_count,
                records_deduplicated=records_dedup_count,
                errors_count=errors_count,
            )
            if cancelled:
                # Keep the CANCELLED status and finished_at set by the cancel request.
                await session.execute(update(SourceRun).where(SourceRun.id == source_run_id).values(**counters))
            else:
                # Guarded on RUNNING: never overwrite a cancel (or a reaper) that landed mid-run.
                result = await session.execute(
                    update(SourceRun)
                    .where(SourceRun.id == source_run_id, SourceRun.status == RunStatus.RUNNING.value)
                    .values(
                        **counters,
                        status=final_status,
                        finished_at=datetime.now(timezone.utc),
                        error_summary=error_summary,
                    )
                )
                if cast(CursorResult, result).rowcount == 0:
                    cancelled = True  # status changed underneath us; treat like a cancel
                    await session.execute(update(SourceRun).where(SourceRun.id == source_run_id).values(**counters))
            # Update source stats; only touch timestamps that this run actually advances,
            # so a failed run doesn't erase the previous last_success_at (and vice versa).
            now = datetime.now(timezone.utc)
            source_values: Dict[str, Any] = {
                "total_records_collected": Source.total_records_collected + records_created_count,
            }
            if not cancelled and final_status != RunStatus.FAILED.value:
                source_values["last_success_at"] = now
            if errors_count > 0:
                source_values["last_error_at"] = now
            await session.execute(
                update(Source).where(Source.id == source.id).values(**source_values)
            )
            await session.commit()

        logger.info(
            "Pipeline completed for SourceRun %s: %s (Fetched: %d, Extracted: %d, Created: %d, Dedup: %d, Errors: %d)",
            source_run_id, final_status, pages_fetched_count, records_extracted_count, records_created_count, records_dedup_count, errors_count
        )

    async def _is_cancelled(self, source_run_id: uuid.UUID) -> bool:
        async with AsyncSessionLocal() as session:
            status = await session.scalar(select(SourceRun.status).where(SourceRun.id == source_run_id))
        return status == RunStatus.CANCELLED.value

    async def _resolve_retry_seeds(
        self,
        adapter: SourceAdapter,
        original_params: dict[str, Any],
        snapshots: list[dict[str, Any]],
    ) -> List[DiscoverySeed]:
        """
        Rebuilds the seeds to retry. Snapshots have credential headers stripped, so when the
        adapter's own discovery produces the same request (method + URL + body), that freshly
        built seed (with current credentials) is used; otherwise the snapshot is replayed.
        """
        rediscovered: dict[tuple[str, str, str], DiscoverySeed] = {}
        if any(s.get("headers_redacted") for s in snapshots):
            try:
                async for seed in adapter.discover(original_params):
                    rediscovered[_seed_key(seed.method, seed.url, seed.body)] = seed
                    if len(rediscovered) >= 200:
                        break
            except Exception as exc:
                logger.warning("Rediscovery for retry failed; replaying snapshots as-is: %s", exc)

        seeds: List[DiscoverySeed] = []
        for snap in snapshots:
            key = _seed_key(snap.get("method", "GET"), snap["url"], snap.get("body"))
            seeds.append(rediscovered.get(key) or seed_from_snapshot(snap))
        return seeds

    async def _process_single_item(
        self,
        source_run_id: uuid.UUID,
        source: Source,
        adapter: SourceAdapter,
        item: ExtractedItem,
    ) -> str:
        """
        Executes Stages 4 to 11 for an extracted item:
        NORMALIZE -> VALIDATE -> DEDUPLICATE -> ENRICH -> AI_CLASSIFY -> STORE -> INDEX -> DISPLAY
        """
        content_hash = hashlib.sha256(
            json.dumps(item.raw_data, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

        # --- STAGE 4: NORMALIZE ---
        normalized = adapter.normalize(item)

        # --- STAGE 5: VALIDATE ---
        val_outcome = adapter.validate(normalized)
        val_errors = {"errors": val_outcome.errors} if not val_outcome.is_valid else None
        proc_status = "VALIDATED" if val_outcome.is_valid else "VALIDATION_FAILED"

        # Record provenance sighting in extracted_records
        async with AsyncSessionLocal() as session:
            # Check for existing extracted record with same source & external_id or hash
            existing_rec = None
            if item.external_id:
                existing_rec = await session.scalar(
                    select(ExtractedRecord).where(
                        ExtractedRecord.source_id == source.id,
                        ExtractedRecord.external_id == item.external_id,
                    )
                )

            if not existing_rec:
                existing_rec = await session.scalar(
                    select(ExtractedRecord).where(
                        ExtractedRecord.source_id == source.id,
                        ExtractedRecord.content_hash == content_hash,
                    )
                )

            if existing_rec is not None and existing_rec.canonical_entity_id is not None:
                # Already stored as a canonical entity: just record the fresh sighting.
                existing_rec.raw_payload = item.raw_data
                existing_rec.source_run_id = source_run_id
                await session.commit()
                return "DEDUPLICATED"

            if existing_rec is not None:
                # Seen before but never stored (validation or store failure): try again,
                # which is what makes re-runs and dead-letter retries able to recover it.
                existing_rec.raw_payload = item.raw_data
                existing_rec.source_run_id = source_run_id
                existing_rec.processing_status = proc_status
                existing_rec.validation_errors = val_errors
                extracted_record_id = existing_rec.id
                await session.commit()
            else:
                # INSERT .. ON CONFLICT DO NOTHING: the unique indexes on (source_id, external_id)
                # and (source_id, content_hash) make concurrent runs unable to double-insert.
                inserted = await session.execute(
                    pg_insert(ExtractedRecord)
                    .values(
                        id=uuid.uuid4(),
                        source_id=source.id,
                        source_run_id=source_run_id,
                        entity_type=source.module_type,
                        external_id=item.external_id,
                        source_url=item.source_url,
                        content_hash=content_hash,
                        raw_payload=item.raw_data,
                        processing_status=proc_status,
                        validation_errors=val_errors,
                        discovered_at=item.discovered_at,
                    )
                    .on_conflict_do_nothing()
                    .returning(ExtractedRecord.id)
                )
                extracted_record_id = inserted.scalar()
                await session.commit()
                if extracted_record_id is None:
                    return "DEDUPLICATED"  # a concurrent run inserted the same record first

            if not val_outcome.is_valid:
                return "VALIDATION_FAILED"

        # Stages 6-11: Deduplicate against domain tables, enrich, score, and store
        if source.module_type == "BUSINESS":
            try:
                from app.modules.businesses.services.business_service import BusinessIngestionService
                biz_service = BusinessIngestionService()
                async with AsyncSessionLocal() as session:
                    biz_obj, outcome = await biz_service.ingest_business(
                        db=session,
                        normalized=normalized,
                        source_id=source.id,
                        original_source_url=item.source_url,
                    )
                    # Link canonical entity in extracted_record
                    await session.execute(
                        update(ExtractedRecord)
                        .where(ExtractedRecord.id == extracted_record_id)
                        .values(canonical_entity_id=biz_obj.id, processing_status="STORED")
                    )
                    await session.commit()
                    return outcome
            except Exception as biz_exc:
                logger.error("Error storing business entity: %s", biz_exc)
                return "STORE_FAILED"

        elif source.module_type == "JOB":
            try:
                from app.modules.jobs.services.job_service import JobIngestionService
                job_service = JobIngestionService()
                async with AsyncSessionLocal() as session:
                    job_obj, outcome = await job_service.ingest_job(
                        db=session,
                        raw_data={
                            "title": normalized.title,
                            "company_name": normalized.company_name,
                            "company_website": normalized.company_website,
                            "description": normalized.description,
                            "location_text": normalized.location_text,
                            "city": normalized.city,
                            "country": normalized.country,
                            "application_url": normalized.application_url,
                            "published_at": normalized.published_at,
                        },
                        source_id=source.id,
                        source_platform=source.name,
                        original_source_url=item.source_url,
                    )
                    await session.execute(
                        update(ExtractedRecord)
                        .where(ExtractedRecord.id == extracted_record_id)
                        .values(canonical_entity_id=job_obj.id, processing_status="STORED")
                    )
                    await session.commit()
                    return outcome
            except Exception as job_exc:
                logger.error("Error storing job entity: %s", job_exc)
                return "STORE_FAILED"

        elif source.module_type == "EVENT":
            try:
                from app.modules.events.services.event_service import EventIngestionService
                from app.schemas.event import EventCreate

                event_payload = normalized.model_dump()
                event_payload["categories"] = event_payload.pop("themes", []) or []
                event_data = EventCreate.model_validate(event_payload)

                async with AsyncSessionLocal() as session:
                    event_service = EventIngestionService(session)
                    event_obj, is_created = await event_service.ingest_event(
                        event_data, source_id=source.id
                    )
                    await session.execute(
                        update(ExtractedRecord)
                        .where(ExtractedRecord.id == extracted_record_id)
                        .values(canonical_entity_id=event_obj.id, processing_status="STORED")
                    )
                    await session.commit()
                    return "CREATED" if is_created else "UPDATED"
            except Exception as event_exc:
                logger.error("Error storing event entity: %s", event_exc)
                return "STORE_FAILED"

        logger.error("Unsupported module_type '%s' for source %s", source.module_type, source.slug)
        return "STORE_FAILED"

    async def _record_task_error(
        self,
        source_run_id: uuid.UUID,
        source_id: uuid.UUID,
        stage: str,
        exc: Exception,
        snapshot: dict[str, Any],
    ) -> None:
        async with AsyncSessionLocal() as session:
            task = ScrapingTask(
                source_run_id=source_run_id,
                source_id=source_id,
                stage=stage,
                status=TaskStatus.FAILED.value,
                retry_count=1,
                max_retries=3,
                payload_ref=snapshot,
                error_message=str(exc),
                traceback=traceback.format_exc(),
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
            session.add(task)
            await session.flush()

            # Create Dead Letter Task if fatal
            dlq = DeadLetterTask(
                scraping_task_id=task.id,
                source_id=source_id,
                stage=stage,
                input_snapshot=snapshot,
                error_type=exc.__class__.__name__,
                error_message=str(exc),
            )
            session.add(dlq)
            await session.commit()
