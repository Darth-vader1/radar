# RADAR — Unified Web Intelligence & Discovery Platform

Production-oriented, AI-powered web intelligence and discovery platform combining:
1. **BusinessRadar** — Discover businesses, contact info, online presence, website health, and lead scoring.
2. **JobRadar** — Discover tech vacancies, internships, remote roles, and required skills with cross-platform deduplication.
3. **EventRadar** — Discover hackathons, competitions, grants, and tech events with deadline tracking and eligibility filtering.

---

## Architecture Overview
- **Backend**: FastAPI (Python 3.12+), SQLAlchemy 2.0 (async), Pydantic v2, Alembic
- **Workers & Queues**: Celery, Celery Beat, Redis
- **Scraping Engine**: HTTPX (async), Scrapy, Playwright, BeautifulSoup4
- **Database**: PostgreSQL 16 (Full-text search, trigram matching, JSONB)
- **Frontend**: Next.js 14+ (App Router), TypeScript, Tailwind CSS, shadcn/ui, Framer Motion, Recharts, Lucide Icons
- **AI Abstraction**: Provider-independent (Google Gemini, OpenAI, Local Ollama/vLLM)
