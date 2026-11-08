# RADAR — Phase 2 Scraping Engine Summary

## 1. Completed Functionality

### 1.1 Politeness & Crawl Control
- **`TokenBucketRateLimiter` (`backend/app/modules/scraping/politeness.py`)**:
  - Redis-backed token bucket enforcing per-domain requests-per-minute (`RPM`) and minimum intervals.
  - Automatic non-blocking fallback to local in-memory locks if Redis is temporarily unreachable.
- **`RobotsPolicyService` (`backend/app/modules/scraping/politeness.py`)**:
  - RFC 9309 compliant robots.txt parser powered by `protego`.
  - Caches policies in Redis with a 24-hour TTL (`robots_txt:{domain}`).
  - Evaluates user-agent rules for honest bot identification (`RadarBot/1.0 (+https://radar-intel.local/bot; bot@radar-intel.local)`).
  - Skips disallowed URLs before any network scrape is attempted.

### 1.2 SSRF-Guarded Fetcher Gateway
- **`FetcherGateway` (`backend/app/modules/scraping/gateway.py`)**:
  - Unified HTTP and JavaScript-rendering client.
  - **HTTP Transport (`fetch_http`)**: High-performance HTTPX client with hop-by-hop redirect verification (`MAX_REDIRECT_HOPS = 5`). Prevents attackers from using open 3xx redirects to hop into private/loopback/cloud metadata IP blocks.
  - **Rendered Transport (`fetch_rendered`)**: Headless Chromium via Playwright with network route interception:
    - Aborts heavy non-essential subresources (`image`, `media`, `font`, `stylesheet`) for major speed and CPU optimizations.
    - Validates subresource requests against SSRF rules to prevent malicious scripts from probing internal network ranges.
    - Returns rendered DOM snapshot with status codes and headers.
  - Returns standardized `RawFetchArtifact` containing final URL, content-type, status code, response headers, and body text.

### 1.3 11-Stage Pipeline Orchestrator
- **`PipelineOrchestrator` (`backend/app/modules/scraping/pipeline.py`)**:
  - Coordinates end-to-end execution of discovery runs across the 11 stages:
    1. **DISCOVER**: Calls `adapter.discover(query_params)` to yield `DiscoverySeed`s.
    2. **FETCH**: Enforces `robots.txt` policy, acquires domain rate tokens, and retrieves artifacts via `FetcherGateway`.
    3. **EXTRACT**: Calls `adapter.extract()`, collects `ExtractedItem`s, and queues pagination seeds within `crawl_budget_pages`.
    4. **NORMALIZE**: Maps raw dictionaries into canonical Pydantic models.
    5. **VALIDATE**: Enforces domain invariants and records any validation warnings.
    6. **DEDUPLICATE**: Deterministic duplicate detection using SHA-256 `content_hash` and external identifiers.
    7. **ENRICH**: Hooks for website availability checks, DNS/MX resolution, and contact crawling.
    8. **AI_CLASSIFY**: Hooks for optional LLM classification and structured extraction.
    9. **STORE**: Persists canonical records and creates provenance links in `extracted_records`.
    10. **INDEX**: Updates full-text search vectors.
    11. **DISPLAY**: Emits run completion signals and checks search alerts.
- **Dead-Letter Queue (DLQ) & Error Isolation**:
  - Item-level and page-level errors are isolated so a single malformed page cannot crash a multi-page discovery run.
  - Catches tracebacks and records failed attempts in `scraping_tasks`.
  - Exceeding retries automatically routes the task to `dead_letter_tasks` with an input snapshot.

### 1.4 Background Worker & Task API Integration
- **Celery Worker Execution (`backend/workers/tasks.py`)**:
  - `run_pipeline` task executing `PipelineOrchestrator` within an asynchronous event loop.
  - Fallback to background `asyncio.create_task` if the Celery broker is offline in local dev mode.
- **REST Endpoints (`backend/app/api/v1/tasks.py`)**:
  - `GET /tasks/dead-letter`: Lists active dead-letter tasks.
  - `POST /tasks/dead-letter/{id}/retry`: Re-queues failed tasks with resolution audit logging.
  - `POST /tasks/trigger`: Dispatches discovery jobs with search parameters.
  - `GET /tasks/runs`: Real-time run progress, page counters, and record counts.
  - `POST /tasks/runs/{run_id}/cancel`: Halts active discovery runs.

### 1.5 Tasks & DLQ Frontend Console
- **`frontend/app/(dashboard)/tasks/page.tsx`**:
  - Multi-tab view: **Discovery Runs** and **Dead-Letter Queue (DLQ)** with live error counters.
  - Live 10s auto-refresh polling with status badges (`Running`, `Queued`, `Completed`, `Partial Success`, `Failed`, `Cancelled`).
  - One-click "Retry" button on DLQ items and "Cancel" button on active runs.

### 1.6 Unit Test Suite
- `backend/tests/unit/test_politeness.py`: Verifies `protego` robots.txt parsing and token bucket in-memory fallback.
- `backend/tests/unit/test_gateway.py`: Verifies `FetcherGateway` using HTTPX mock transport and SSRF boundary blocking.
- `backend/tests/unit/test_pipeline.py`: Verifies adapter data flow, normalization, validation, and content hashing.
- `backend/tests/fixtures/`: Realistic HTML and robots.txt mock fixtures.

---

## 2. Known Limitations (Phase 2)
- Domain-specific canonical storage (inserting into `businesses`, `jobs`, and `events` tables) is stubbed until the dedicated domain models and tables are generated in Phases 3, 4, and 5. `extracted_records` captures all incoming records and deduplication metadata.
- Playwright Chromium headless requires browser binaries (`playwright install chromium`). When uninstalled, the gateway automatically falls back to HTTPX async fetching.

---

## 3. Outstanding Configuration
No external credentials are required for Phase 2. The scraping engine, rate limiter, robots.txt service, and pipeline orchestrator operate fully out of the box.

---

## 4. Next Implementation Phase: Phase 3 — BusinessRadar
In Phase 3, we will build:
1. **Domain Models & Migrations**: `businesses`, `business_contacts`, `business_social_profiles`, `email_verifications`, `lead_scores`, and `lead_scoring_rules`.
2. **Adapters**:
   - `OpenStreetMap Overpass` (`osm_overpass_businesses`): Rich POI extraction for Lagos, Abuja, and Nigerian cities.
   - `Google Places API` (`google_places_api`): Credential-gated commercial discovery.
   - `Nigerian Public Directory` (`ng_public_directory`): State and sector-specific B2B scraping.
   - `Business Website Contact & Metadata Enricher` (`business_site_enricher`).
3. **Multi-Step Website Availability Classifier**: (Has website, No website found, Website unreachable, Website broken, Website redirects incorrectly, Website requires manual verification).
4. **Email Enrichment & Verification Subsystem**: Syntax check, DNS/MX lookup, contact page crawler.
5. **Configurable Lead Scoring Engine**: Dynamic rule points calculation with human-readable explanations.
6. **BusinessRadar Frontend UI**: Search controls (Country, State, City, Category, Website status, Lead score), results table, business detail drawer, lead score badge breakdown, and export button.
