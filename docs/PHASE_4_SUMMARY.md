# RADAR — Phase 4 JobRadar Summary

## 1. Completed Functionality

### 1.1 Database Architecture & Schema Migrations
- **Models & Migration (`003_phase4_job_radar.py`)**:
  - `jobs`: Stores job title, normalized title, company name, normalized company, company website, HTML description, requirements, education requirements, technology category (`SOFTWARE_ENGINEERING`, `FRONTEND`, `BACKEND`, `CLOUD`, `DEVOPS`, `DATA_SCIENCE`, `AI_ML`, `CYBERSECURITY`, `PRODUCT_DESIGN`, `PRODUCT_MANAGEMENT`), employment type (`FULL_TIME`, `PART_TIME`, `INTERNSHIP`, `GRADUATE_TRAINEE`, `CONTRACT`, `FREELANCE`), remote status (`REMOTE`, `HYBRID`, `ONSITE`), seniority level, salary ranges, location, application deadline, application URL, source platform, and cross-platform duplicate cluster tracking.
  - `job_skills`: Links recognized technical skills to jobs with normalized skill names and extraction provenance.

### 1.2 Cross-Platform Job Deduplication
- **`JobIngestionService` (`backend/app/modules/jobs/services/job_service.py`)**:
  - Eliminates the problem where the same vacancy posted on multiple platforms appears as duplicate unrelated listings.
  - Normalizes company names (stripping legal suffixes like `Ltd`, `Inc`, `PLC`) and job titles (stripping brackets, locations, levels).
  - Matches across platforms; when an existing vacancy is observed again on a different board, it increments `other_sources_count`, enriches missing fields without overwriting verified data, and records provenance in `extracted_records`.

### 1.3 Tech Skill Extraction & Category Normalization
- **`skill_extractor.py` (`backend/app/modules/jobs/services/skill_extractor.py`)**:
  - Regex taxonomy extracting over 50 technology skills (Python, TypeScript, React, Go, Rust, AWS, Docker, Kubernetes, PostgreSQL, PyTorch, etc.).
  - Classifies tech categories based on title and keyword patterns.
  - Identifies seniority levels (`INTERN`, `ENTRY`, `MID`, `SENIOR`, `STAFF_PRINCIPAL`, `LEAD_MANAGER`).
  - Identifies remote eligibility (`REMOTE`, `HYBRID`, `ONSITE`).

### 1.4 Job Discovery Adapters
- **Greenhouse Public Boards (`greenhouse_boards`)**:
  - Official public API integration (`boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true`).
  - Pre-seeded with prominent Nigerian & remote employers: `paystack`, `moniepoint`, `andela`, `wave`, `gitlab`, `cloudflare`.
  - Zero API key required.
- **Remotive Remote Developer Jobs (`remotive_jobs`)**:
  - Official public API integration (`remotive.com/api/remote-jobs`).
  - Fetches worldwide remote software, devops, data, and QA listings.
  - Zero API key required.

### 1.5 Pipeline Integration
- Direct integration in `PipelineOrchestrator` (`backend/app/modules/scraping/pipeline.py`):
  - When `source.module_type == "JOB"`, records flow through deduplication, skill extraction, and persistence into `jobs` and `job_skills`.

### 1.6 JobRadar Frontend Interface
- **`frontend/app/(dashboard)/jobs/page.tsx`**:
  - **Category Pills**: Software Engineering, Frontend, Backend, Cloud, DevOps, AI/ML, Data Science, Cybersecurity, Product Design, Product Management.
  - **Filters**: Workplace Type (Remote Only, Hybrid, Onsite), Employment Type (Full-time, Internship, Graduate Trainee), Seniority, and Search.
  - **Cards & Table View Toggle**: Seamlessly switch between rich visual cards and compact data table.
  - **Slide-over Job Detail Drawer**:
    - Complete formatted job description.
    - Key metrics (Category, Seniority, Workplace Type).
    - Required technical skill badges.
    - Unified cross-platform sighting count indicator.
    - One-click "Apply on Company Site" button.

### 1.7 Unit Test Suite
- `backend/tests/unit/test_job_radar.py`: Verifies title and company normalization, skill extraction, category/seniority classification, and Greenhouse adapter normalization.

---

## 2. Known Limitations (Phase 4)
- Salary ranges are only populated when explicitly published by the employer; RADAR never fabricates unstated salaries.
- Certain custom private ATS portals lacking public JSON APIs require dedicated HTML scraping adapters in subsequent sprints.

---

## 3. Outstanding Configuration
- **Zero-Key Sources**: Both `greenhouse_tech_boards` and `remotive_tech_jobs` operate immediately with zero API keys required. Additional Greenhouse board tokens can be added dynamically in the Source Registry UI under `adapter_config`.

---

## 4. Next Implementation Phase: Phase 5 — EventRadar
In Phase 5, we will build:
1. **Domain Models & Migrations**: `events`, `event_categories`, and `event_category_links`.
2. **Adapters**:
   - `Devpost Public Hackathons` (`devpost_hackathons`): Global & student hackathons with prize pools and submission deadlines.
   - `Zindi Africa Competitions` (`zindi_competitions`): Pan-African AI, Machine Learning, and Data Science competitions with USD cash prizes.
   - `MLH (Major League Hacking)` (`mlh_events`): Verified student hackathons.
   - `Kaggle Competitions` (`kaggle_competitions`): Credential-gated official ML competitions.
3. **Event Registration State Machine & Deadline Classifier**:
   - `OPEN_REGISTRATION`, `REGISTRATION_CLOSING_SOON`, `REGISTRATION_CLOSED`, `UPCOMING`, `ONGOING`, `COMPLETED`.
4. **Prize & Eligibility Engine**: Filters for cash prizes, free participation, remote/online participation, student eligibility, and international eligibility.
5. **EventRadar Frontend UI**: Discovery grid, registration deadline countdowns, eligibility badges, prize pool highlights, and event calendar view.
