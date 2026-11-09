# RADAR — Production Readiness Plan

_Assessed 2026-11-08. Scope: `backend/` (FastAPI, Celery, Alembic), `frontend/` (Next.js 14), `infrastructure/`, `docker-compose.yml`._

## 1. Current state in brief

| Area | State |
|---|---|
| Backend tests | 49 unit tests, all pass. They mock the network and database, so they miss the blockers below. No integration tests against Postgres or Redis. |
| Ingestion pipeline | **Broken end to end.** No scrape run can produce data today (see B1, B2). |
| Modules | BusinessRadar and JobRadar have APIs and UI. EventRadar has adapters, a classifier and a migration, but no API route, no pipeline storage and only a stub page. |
| Frontend | Businesses, Jobs, Sources, Tasks and Settings pages are built. Analytics, Events, Intelligence and Saved are placeholders. Production build has not been verified. |
| Infra | Only a dev compose setup: `--reload`, `next dev`, source bind-mounts, default secrets, DB and Redis ports open to the host. |
| Repo hygiene | Not a git repository. `venv/`, `__pycache__/` and two `.env` files sit in the tree. |

## 2. Findings

### Blockers: nothing works in production until these are fixed

| # | Finding | Location |
|---|---|---|
| B1 | `_run_stages` uses `rate_policy`, which is only defined in `execute_run`. Every fetch raises `NameError`, gets caught as a fetch error and goes to the DLQ, so runs always end `FAILED`. | `backend/app/modules/scraping/pipeline.py` (`self.gateway.fetch(seed, rate_policy=rate_policy)`) |
| B2 | Adapters register themselves with `@register_adapter`, but no module ever imports them. In the API process and the Celery worker the `AdapterRegistry` is empty, so every run fails with "No adapter registered". | `app/modules/*/adapters/*.py`, `app/modules/scraping/registry.py` |
| B3 | The compose backend command runs `python -m app.infrastructure.scripts.seed_roles_and_sources`, but that module doesn't exist (the script is at the repo root, `infrastructure/scripts/`, and isn't copied into the image). The container exits before uvicorn starts. | `docker-compose.yml` |
| B4 | Insecure defaults: a hard-coded `SECRET_KEY` in `config.py`, `.env.example` and compose; `DEBUG=True` by default; DB credentials in `alembic.ini`. If the env var is missing, nothing stops the app from booting. | `app/core/config.py`, `docker-compose.yml`, `alembic.ini` |
| B5 | Open registration plus "first user becomes `super_admin`". On a fresh deploy, whoever registers first owns the system. The user count and insert also race. | `app/api/v1/auth.py::register` |
| B6 | EventRadar isn't connected: `_process_single_item` returns `"CREATED"` for EVENT sources without storing anything, and there's no `/events` router. | `pipeline.py`, `api/v1/router.py` |

### Security

| # | Finding | Location |
|---|---|---|
| S1 | SSRF guard bypasses: (a) robots.txt fetch and site enricher use `follow_redirects=True`, so a redirect to an internal IP skips validation; (b) DNS rebinding TOCTOU, because the URL is validated with `getaddrinfo` and then httpx resolves it again. | `politeness.py::get_policy`, `site_enricher.py`, `gateway.py` |
| S2 | Response bodies are read in full (`resp.text`) with no size cap or content-type allowlist, which allows memory exhaustion from a hostile page. | `gateway.py`, `site_enricher.py` |
| S3 | No rate limiting or lockout on `/auth/login` and `/auth/register`. | `api/v1/auth.py` |
| S4 | Refresh tokens are stateless, never rotated or revoked, and sent as a **query parameter**, so they end up in access logs. No logout. Deactivating a user doesn't kill outstanding access tokens until they expire. | `auth.py::refresh_token`, `core/security.py` |
| S5 | API key `scopes` and `rate_limit_per_minute` are stored but never enforced. | `api/deps.py` |
| S6 | Tokens are stored in `localStorage` (readable by XSS). No CSP or security headers on the frontend or the API. | `frontend/lib/auth.ts`, `next.config.mjs` |
| S7 | `datetime` fields are stored as ISO strings (`last_login_at`, `revoked_at`). That isn't a vulnerability, but it breaks ordering and comparisons in audit queries. | `models/auth.py` |
| S8 | Postgres (5432) and Redis (6379, no password) are published to the host in compose. | `docker-compose.yml` |
| S9 | The SSRF error handler echoes internal resolution details (resolved IPs) to clients. | `app/main.py` |
| S10 | `sources.update_source` applies arbitrary `setattr` from the payload. The schema limits the fields, but there's no check that a changed `base_url` or `adapter_config` is safe. | `api/v1/sources.py` |

### Correctness and reliability

| # | Finding | Location |
|---|---|---|
| R1 | Cancelling a run only changes its DB status. The running pipeline never checks, so it keeps fetching and then overwrites the status with `COMPLETED`/`FAILED`. | `tasks.py::cancel_run`, `pipeline.py` |
| R2 | DLQ "retry" marks the item resolved but never re-enqueues anything. | `tasks.py::retry_dead_letter_task` |
| R3 | Celery fallback: if the broker is down, `.delay()` can block on connection retries; then `asyncio.create_task` fires an untracked task in the API process (no reference kept, lost on restart, and it competes with request handling). | `tasks.py::trigger_source_run` |
| R4 | Celery beat runs, but there's no `beat_schedule`. `Source.schedule_cron` is stored and never read. | `workers/celery_app.py` |
| R5 | No Celery retries or `acks_late`, and no stale-run reaper. A worker crash leaves runs stuck in `RUNNING` forever. | `workers/` |
| R6 | `last_success_at` is set to `NULL` on a failed run and `last_error_at` to `NULL` on a clean one, so history is erased. | `pipeline.py` finalize block |
| R7 | `max_concurrency` is ignored: seeds are fetched one at a time from a list with `pop(0)`. Items open 2–3 DB sessions each. Throughput will be poor. | `pipeline.py` |
| R8 | Dedup does a check-then-insert with no unique constraint or `ON CONFLICT`, so concurrent runs create duplicates. | `pipeline.py::_process_single_item`, domain services |
| R9 | `STORE_FAILED` outcomes are dropped from the error count, so runs report `COMPLETED` while losing records. | `pipeline.py` |
| R10 | Playwright isn't in `requirements.txt` or the image. `requires_js` seeds quietly fall back to plain HTTP. A browser is launched per page (expensive) if it's ever installed. | `gateway.py`, Dockerfiles |
| R11 | Each `PipelineOrchestrator` opens Redis clients that are never closed (`gateway.close()` is never called). | `pipeline.py`, `workers/tasks.py` |
| R12 | `get_db` is duplicated in `database/session.py` and `api/deps.py`, and it auto-commits even though handlers already commit. | |
| R13 | List endpoints use `lower(col) LIKE '%x%'`, which can't use an index and does full scans. The README promises trigram/FTS. | `businesses.py`, `jobs.py` |
| R14 | `list_businesses` defaults `country="Nigeria"`, a hidden filter that surprises API consumers. | `businesses.py` |
| R15 | Dead code (a duplicate dispatch block after `return` in `gateway.fetch`). `worker.Dockerfile` is unused. Several `except Exception: pass` blocks hide parse errors. | |

### Operations

| # | Finding |
|---|---|
| O1 | Plain-text logs with no request ID or run ID correlation, so they can't be searched in a log aggregator. |
| O2 | No metrics (request latency, run outcomes, fetch errors per domain, queue depth), no error tracking (Sentry), no tracing. |
| O3 | Dependencies are ranges, not pinned. There's no lockfile, so builds aren't reproducible. Unused heavy dependencies are installed (`google-genai`, `openai`, `psycopg2-binary`, and the README lists Scrapy). Test dependencies ship in the prod image. |
| O4 | Images run as root, are single-stage, and have no `HEALTHCHECK`. The frontend image runs `next dev`. |
| O5 | Migrations run inside the API container's start command, so every replica races to migrate. |
| O6 | No CI: no lint, type check, test, build or image scan. |
| O7 | No backup/restore plan for Postgres, no retention policy for `extracted_records` or audit logs, and no data-retention or PII policy, even though BusinessRadar stores emails and phones of real businesses. |

## 3. Implementation plan

Phases are ordered by dependency. Each phase ends in something deployable and testable.

### Phase 0: Repository baseline (½ day)
1. `git init`, confirm `.gitignore` covers `venv/`, `.env`, `__pycache__/` and `.pytest_cache/`, then make the first commit without secrets. **Rotate any real keys in `.env` / `backend/.env` before the code goes anywhere.**
2. Delete committed caches and the unused `worker.Dockerfile` (or make it the worker image in Phase 5).
3. Add `pyproject.toml` with ruff + mypy config, and pin dependencies with `uv`/`pip-tools` into `requirements.lock`. Split dev and prod dependencies.
4. Frontend: add ESLint config and a `typecheck` script. Run `npm run build` once and fix any errors.

### Phase 1: Make the pipeline actually work (1–2 days). Fixes B1, B2, B6, R6, R9, R11, R15

> **Status: done (2026-11-08).** All items below are implemented. `tests/integration/test_pipeline_e2e.py` runs the job, business and event pipelines against a throwaway `<db>_test` database. It also caught and fixed a further bug: new businesses with a phone number failed to store (`MissingGreenlet` in `business_service.py`).
1. Pass `rate_policy` into `_run_stages` (or build it there from `source`).
2. Add `app/modules/adapters_loader.py` that imports every adapter package. Call it from `app/main.py` lifespan and `workers/celery_app.py` (Celery `imports=`). Add a test that asserts every `adapter_key` in the seed script resolves in the registry.
3. Wire EVENT ingestion: call `EventIngestionService` in `_process_single_item`, add `api/v1/events.py` (list/detail/filter by deadline, type, eligibility) and its schemas, and register the router.
4. Count `STORE_FAILED` and `VALIDATION_FAILED` toward run stats. Only update `last_success_at` / `last_error_at` when they apply.
5. Close the gateway in a `finally` block in `execute_run`. Remove the dead dispatch block.
6. **Integration test**: spin up Postgres + Redis (testcontainers or compose service in CI), seed a source, point an adapter at a local fixture server, run `execute_run`, and assert that rows land in domain tables. That test would have caught B1/B2.

### Phase 2: Security hardening (2–3 days). Fixes B4, B5, S1–S10

> **Status: done (2026-11-08).**
> - **Implemented**: everything below, plus migration `005_auth_hardening`, the `app/core/http.py` SSRF-pinned client, `app/core/rate_limit.py`, `app/cli.py`, and the frontend `middleware.ts`. The hard-coded "demo administrator" credentials were also removed from the login page.
> - **Tests**: `tests/integration/test_auth_api.py`, `test_cli.py`, `tests/unit/test_config_hardening.py`, and the rewritten gateway tests (rebinding, mixed DNS answers, IPv4-mapped IPv6, size and content-type limits).
> - **Deferred**: the frontend CSP still allows `'unsafe-inline'` scripts, because Next.js bootstrap needs it without nonces. Moving to a nonce-based CSP is a later improvement. S10 (validating `base_url` and `adapter_config` changes) is left for Phase 8.
1. **Config**: add a `model_validator` that refuses to start when `ENVIRONMENT=production` and `SECRET_KEY` is the default or shorter than 32 bytes, `DEBUG` is true, or CORS includes localhost. Default `DEBUG=False`. Remove the URL from `alembic.ini` (env.py already reads settings).
2. **Bootstrap admin**: remove the first-user-gets-super-admin rule. Add a CLI command `python -m app.cli create-admin` and an `ALLOW_PUBLIC_REGISTRATION` flag (default off in prod).
3. **SSRF**: build one shared `SafeAsyncClient`, a custom httpx transport that resolves the host once, validates every resolved IP, and connects to that validated IP with SNI/Host preserved. Use it everywhere (gateway, robots, site enricher, adapters). Turn off `follow_redirects` globally and use the gateway's manual hop validation. Add tests for redirect-to-127.0.0.1 and a rebinding resolver.
4. **Response limits**: stream responses, abort over `MAX_RESPONSE_BYTES` (for example 5 MB), and allowlist content types per adapter.
5. **Auth**:
   - Move the refresh token to the JSON body or an httpOnly cookie.
   - Store refresh token `jti`s in Redis or a table; rotate on every use, detect reuse, and add `/auth/logout`.
   - Add a `token_version` column on `User`, bumped on deactivation or password change and checked in `get_current_user`.
6. **Rate limiting** (`slowapi` or a Redis limiter): login 5/min per IP+email, register 3/hour per IP, plus per-API-key `rate_limit_per_minute`. Enforce API-key `scopes` with a `require_scope()` dependency.
7. **Frontend session**: switch to an httpOnly, `Secure`, `SameSite=Lax` cookie set by the API (or a Next.js route handler) and drop `localStorage`. Add Next.js `middleware.ts` route protection, plus CSP, HSTS, `X-Content-Type-Options` and `Referrer-Policy` headers in `next.config.mjs` and on the API via middleware.
8. Change `last_login_at` / `revoked_at` to `DateTime(timezone=True)` with a migration.
9. Make the SSRF error message generic to clients and keep the details in logs.

### Phase 3: Reliable job execution (2–3 days). Fixes R1–R5, R8

> **Status: done (2026-11-08).**
> - **Implemented**: all items below, plus migration `006_run_reliability`, `app/modules/scraping/runs.py` and `scheduling.py`, and `app/database/locks.py`.
> - **Extra fixes**: records that previously failed validation or storage are now retried instead of being counted as duplicates. Runs blocked entirely by robots.txt now end as FAILED, not COMPLETED.
> - **Tests**: `tests/integration/test_run_lifecycle.py`.
> - **Verified by hand**: a real Celery worker processed two live Devpost runs back to back (the second run was fully deduplicated), and dispatch with the broker down fails in about 5 seconds with the run marked FAILED.
> - **Finding**: Remotive's and Overpass's robots.txt disallow their API paths, so those sources return nothing while `respect_robots_txt` is on.
1. **Dispatch**: drop the in-process `asyncio.create_task` fallback. If the broker is unreachable (short `broker_connection_timeout`), mark the run `FAILED` with a clear error and return 503.
2. **Celery config**: `acks_late=True`, `task_reject_on_worker_lost=True`, `visibility_timeout` > hard time limit, and autoretry for transient errors with backoff. Use a single event loop per worker process (`asyncio.run` per task is fine; avoid leaking loops).
3. **Cancellation**: the pipeline checks run status (or a Redis flag `run:{id}:cancel`) between seeds and stops cleanly as `CANCELLED`. The final status update must not overwrite `CANCELLED` (`WHERE status = 'RUNNING'`).
4. **DLQ retry** re-enqueues a targeted task (fetch one seed URL with the stored snapshot) and links the new `ScrapingTask`.
5. **Scheduling**: a beat task every minute reads enabled sources with `schedule_cron` (use `croniter`), skips sources that already have a QUEUED or RUNNING run, and enqueues the due ones. Alternatively use `celery-redbeat` for a DB/Redis-driven schedule.
6. **Reaper**: a periodic task marks runs stuck in `RUNNING` longer than the hard time limit as `FAILED`.
7. **Idempotency**: add unique indexes (`extracted_records(source_id, external_id)`, `(source_id, content_hash)`, plus the domain dedup keys) and use `INSERT … ON CONFLICT` upserts.

### Phase 4: Performance and data layer (2 days). Fixes R7, R10, R12, R13, R14
1. Process seeds with a bounded `asyncio.Semaphore(max_concurrency)` and a `deque`. Reuse one `SafeAsyncClient` per run. Batch item writes into one session per page.
2. Merge the two `get_db` functions into one with no auto-commit; handlers own their transactions.
3. Search: add `pg_trgm` GIN indexes, or `tsvector` columns with GIN, on business name/category/address and job title/company/description. Use `ILIKE` or `websearch_to_tsquery`. Return total counts and a pagination envelope from list endpoints.
4. Remove the `country="Nigeria"` default (make it an explicit frontend default instead).
5. Decide on Playwright. Either add it with a dedicated worker image and queue (`-Q js_render`), reusing a browser across pages, or remove `requires_js` support and the dead fallback.
6. Tune the DB pool for API and worker separately (the worker needs a small pool; consider `NullPool` with pgbouncer).

### Phase 5: Production infrastructure (2–3 days). Fixes B3, S8, O3–O5

> **Status: done (2026-11-08).**
> - **Implemented**: `docker-compose.prod.yml`, `infrastructure/caddy/Caddyfile`, multi-stage non-root images, `python -m app.cli seed`, `requirements-dev.txt`, and `docs/DEPLOYMENT.md`.
> - **Verified by hand**: the full stack ran locally with self-signed TLS. All services were healthy, only the proxy was published, cookies were Secure over HTTPS, and a live Devpost run went through the containerised worker.
> - **Seed script**: the old `infrastructure/scripts/seed_roles_and_sources.py` reset every user's password to a hard-coded value, made every user super_admin, and inserted invented "VERIFIED" events. It is now a wrapper around the safe seed.
> - **Bug fixed**: list settings such as `BACKEND_CORS_ORIGINS=a,b` crashed startup, because pydantic-settings JSON-decoded them.
> - **Not done**: dependency lockfile (O3, moves to Phase 7 with CI).
1. **Backend image**: multi-stage build, non-root user, prod dependencies only, `HEALTHCHECK` on `/api/v1/health/live`, and `gunicorn -k uvicorn.workers.UvicornWorker` (or uvicorn `--workers`) with no `--reload`.
2. **Frontend image**: `output: "standalone"` in `next.config.mjs`, multi-stage `npm ci && npm run build`, non-root `node server.js`. Make the API URL configurable at build or runtime and remove the hard-coded `localhost:8000` rewrite.
3. Move seeding into `backend/app/cli/seed.py` (inside the image). Run migrations and seeding as a **one-off job** (`migrate` compose service or a k8s Job), not in the API start command.
4. Add a `docker-compose.prod.yml`: no bind mounts, no published DB/Redis ports, a Redis password, secrets from env/secret store, `restart: always`, resource limits, and a reverse proxy (Caddy or Traefik) with TLS in front of frontend and API.
5. Give the worker and beat full environment parity (beat currently lacks `DATABASE_URL`, which the scheduler from Phase 3 needs), and run exactly one beat instance.

### Phase 6: Observability (1–2 days). Fixes O1, O2

> **Status: done (2026-11-08).**
> - **Implemented**:
>   - JSON logs with `request_id`, `run_id`, `source` and `task_id`, plus an access log, in `app/core/logging.py`.
>   - Prometheus `/metrics`: multiprocess HTTP metrics plus database- and broker-derived pipeline and queue metrics, in `app/core/metrics.py`.
>   - Opt-in, scrubbed Sentry in `app/core/observability.py`.
>   - Redis worker heartbeats in `app/core/heartbeat.py`.
>   - A readiness check that covers the broker and worker count and returns no error text.
> - **Tests**: `tests/unit/test_logging.py` and `tests/integration/test_observability.py`.
> - **Verified by hand**: in the production stack, every log line is JSON (the Celery banners are silenced with `--quiet`), a request ID set at the proxy appears in the API access log, the worker shows the run's `run_id` and `source`, `/metrics` is internal only, and readiness reports 1 live worker.
> - **Bug fixed**: the backend image's `PROMETHEUS_MULTIPROC_DIR` was not set, which crash-looped the API. The test stack caught it.
> - **Deferred**: frontend Sentry (`@sentry/nextjs`) is left out for now. It needs extra build configuration and CSP `connect-src` changes. Frontend failures still show up as API errors in Sentry and as 5xx in metrics.
1. Structured JSON logging (`structlog` or a `python-json-logger` formatter) with a request ID middleware, plus `run_id` and `source` bound in pipeline and worker logs.
2. Prometheus metrics: HTTP latency and status (`prometheus-fastapi-instrumentator`); custom counters for runs by status, fetches by domain and outcome, records created/deduped, and DLQ size; Celery queue depth (via `celery-exporter`).
3. Sentry (backend + frontend) with environment tagging.
4. Make readiness check the Celery broker too, and add a worker heartbeat check. Don't echo raw exception strings in `/health/ready`.

### Phase 7: CI/CD and quality gates (1–2 days). Fixes O6
1. GitHub Actions workflow:
   - backend: ruff, mypy, pytest (unit + integration with Postgres/Redis service containers), and `alembic upgrade head` → `alembic check` for model drift
   - frontend: lint, typecheck, `next build`
   - security: `pip-audit`, `npm audit`, image build + Trivy scan
2. Coverage gate on `app/modules/scraping` and `app/api`.
3. Add API tests with `httpx.AsyncClient(app=…)` covering auth flows, RBAC on every mutating route, and the trigger → run → records path.
4. Build and push images on tag, deploy to staging, smoke test `/health/ready`, then promote.

### Phase 8: Product completeness and compliance (ongoing)
1. Frontend: build the Events page against the new `/events` API. Either build out or hide Analytics, Intelligence and Saved; don't ship placeholder nav items. Wire the Jobs page to `/jobs` (it currently makes no `fetchApi` calls).
2. Decide on the AI stage. `AI_ENABLED` and provider keys exist, but there's no implementation. Either build the provider abstraction behind the flag or remove the config and dependencies.
3. **Data compliance** (BusinessRadar collects contact data): document a lawful basis and retention period; add retention jobs for `extracted_records` and `audit_logs`; add a suppression or opt-out list checked at ingest; honour the ToS of each source (Google Places terms forbid caching beyond limits).
4. Set the bot `User-Agent` contact URL and email to real, reachable addresses. `radar-intel.local` isn't reachable.
5. Backups: automated `pg_dump` or managed snapshots, with a tested restore runbook.
6. Write a `docs/RUNBOOK.md` covering deploy, rollback, rotating secrets, draining workers, replaying the DLQ and restoring the DB.

## 4. Suggested order and effort

| Order | Phase | Effort | Gate to move on |
|---|---|---|---|
| 1 | 0 Baseline | ½ d | Repo committed, deps locked |
| 2 | 1 Pipeline works | 1–2 d | Integration test: run → rows in all 3 domains |
| 3 | 2 Security | 2–3 d | Prod config refuses unsafe defaults; SSRF redirect and rebinding tests pass |
| 4 | 3 Job reliability | 2–3 d | Cancel, retry, schedule and reaper covered by tests |
| 5 | 5 Infra | 2–3 d | `docker compose -f docker-compose.prod.yml up` serves over TLS with no dev tooling |
| 6 | 6 Observability | 1–2 d | Logs are JSON with request/run IDs; metrics are scraped |
| 7 | 7 CI/CD | 1–2 d | Green pipeline required to merge |
| 8 | 4 Performance | 2 d | Load test: N concurrent runs without DB pool exhaustion |
| 9 | 8 Product/compliance | ongoing | — |

**Total to a defensible first production release (Phases 0–7): about 2.5–3.5 engineer-weeks.**
