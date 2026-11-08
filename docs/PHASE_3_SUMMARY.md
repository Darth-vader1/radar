# RADAR — Phase 3 BusinessRadar Summary

## 1. Completed Functionality

### 1.1 Database Architecture & Schema Migrations
- **Models & Migration (`002_phase3_business_radar.py`)**:
  - `businesses`: Normalized table with fields for business name, description, category, subcategory, phone number, public email, website URL, website status, online ordering status, address, city, state, country, coordinates, lead score, score explanation, and timestamps.
  - `business_contacts`: Tracks discovered emails, phone numbers, and WhatsApp contacts with source attribution, verification status, and confidence scores.
  - `business_social_profiles`: Stores Instagram, Facebook, LinkedIn, Twitter/X, and TikTok profile handles.
  - `email_verifications`: Audit log for syntax validation, domain MX records, disposable domain flags, and verification status.
  - `lead_scoring_rules`: Configurable scoring weights and rules table seeded with default weights.
  - `lead_scores`: Historic audit snapshots of calculated scores with itemized breakdowns.

### 1.2 Multi-Step Website Availability Classifier
- **`WebsiteCheckerService` (`backend/app/modules/businesses/services/website_checker.py`)**:
  - Enforces the core requirement: **An absent website field in a directory must NOT automatically mean that a business has no website.**
  - Identifies social media links (Instagram, Facebook) mistakenly listed as websites and redirects them to `business_social_profiles`.
  - Probes live web targets through SSRF-safe HTTP client with redirect checks and WAF challenge detection.
  - Categorizes status into:
    1. `HAS_WEBSITE` (2xx with active content).
    2. `NO_WEBSITE_FOUND` (confirmed only after directory and secondary checks return zero candidate domains).
    3. `WEBSITE_UNREACHABLE` (DNS NXDOMAIN or timeout).
    4. `WEBSITE_BROKEN` (5xx server errors, HTTP client errors).
    5. `WEBSITE_REDIRECTS_INCORRECTLY` (Redirects to parked/for-sale domain pages).
    6. `WEBSITE_REQUIRES_MANUAL_VERIFICATION` (Cloudflare Turnstile/WAF challenges or unverified single-source absence).

### 1.3 Email Enrichment & Verification Pipeline
- **`EmailVerifierService` (`backend/app/modules/businesses/services/email_verifier.py`)**:
  - RFC 5322 syntax validation via `email-validator`.
  - Disposable email domain blocking against known temporary email providers.
  - DNS MX and fallback A record lookup via `dnspython`.
  - Distinguishes between `VERIFIED`, `UNVERIFIED`, `INVALID`, `CATCH_ALL`, `UNKNOWN`.
  - **Zero fabrication**: Never invents email addresses; extracts only from verified public channels.

### 1.4 Business Website Contact & Metadata Enricher
- **`BusinessSiteEnricher` (`backend/app/modules/businesses/adapters/site_enricher.py`)**:
  - Automatically crawls operational business homepages and contact pages within a 2-page budget.
  - Extracts direct `mailto:` and text email addresses.
  - Extracts `tel:` phone numbers.
  - Detects active social profiles (Instagram, Facebook, LinkedIn, Twitter/X).
  - Identifies online ordering integrations (Chowdeck, Glovo, Paystack Storefront, Shopify, WooCommerce).

### 1.5 Configurable Sales Lead Scoring Engine
- **`LeadScoringEngine` (`backend/app/modules/businesses/services/lead_scorer.py`)**:
  - Dynamically calculates a 0-100 opportunity score:
    - No website found: `+30 pts`
    - Website unreachable / broken: `+25 pts`
    - No online ordering system: `+20 pts`
    - Active social media presence: `+15 pts`
    - Public business email present: `+15 pts`
    - High commercial intent category: `+10 pts`
    - Recently discovered: `+5 pts`
  - Generates transparent, human-readable explanations and structured breakdown lists.
  - Administrators can adjust rule weights and toggles dynamically via API and UI.

### 1.6 Business Discovery Adapters
- **OpenStreetMap Overpass (`osm_overpass`)**:
  - Official API integration querying POIs across Nigeria (Lagos, Ikeja, Abuja, Port Harcourt, Ibadan) and global cities.
  - Extracts amenity/shop tags, street addresses, phone numbers, websites, and coordinates.
- **Google Places API (New) (`google_places_api`)**:
  - Pre-wired adapter ready for commercial high-density POI queries; reports `AWAITING_CONFIGURATION` until `GOOGLE_PLACES_API_KEY` is provided.

### 1.7 BusinessRadar Frontend Experience
- **`frontend/app/(dashboard)/businesses/page.tsx`**:
  - Multi-faceted filter bar: City (Ikeja, Lagos, Abuja, etc.), Category, Website Status, Min Lead Score slider, and Keyword search.
  - Interactive table displaying Business Name, Category, Location, Website Availability pill, Email/Phone indicator, and Lead Score badge.
  - Slide-over Detail Drawer:
    - Overview, full address, verified contact list.
    - Sales Opportunity Score card with point-by-point breakdown.
    - Online presence indicators and original source attribution.
  - Admin Scoring Configuration modal allowing point adjustments.

### 1.8 Unit Test Suite
- `backend/tests/unit/test_business_radar.py`: Verifies social URL detection, absent website verification rules, email syntax and disposable checks, lead score calculation, and OSM Overpass normalization.

---

## 2. Known Limitations (Phase 3)
- Secondary search fallback using Google Custom Search API / Brave Search API activates when `WEB_SEARCH_API_KEY` is configured; otherwise, sparse records without websites remain flagged as `WEBSITE_REQUIRES_MANUAL_VERIFICATION`.
- CAC corporate identity verification requires CAC accredited agent credentials and is not queried directly.

---

## 3. Outstanding Configuration
- **Zero-Key Sources**: OpenStreetMap Overpass operates immediately with no API key required.
- **Optional Credentials**:
  - `GOOGLE_PLACES_API_KEY`: Activates the Google Places adapter in the Source Registry.
  - `WEB_SEARCH_API_KEY`: Activates secondary web search queries for ambiguous missing-website businesses.

---

## 4. Next Implementation Phase: Phase 4 — JobRadar
In Phase 4, we will build:
1. **Domain Models & Migrations**: `jobs` and `job_skills`.
2. **Adapters**:
   - `Greenhouse Public Job Boards` (`greenhouse_boards`): Pre-configured with major Nigerian & global remote tech employers (Paystack, Moniepoint, Andela, GitLab, Cloudflare, etc.).
   - `Lever Public Postings API` (`lever_postings`).
   - `Remotive Remote Developer Jobs` (`remotive_jobs`).
   - `Arbeitnow API` (`arbeitnow_api`).
3. **Cross-Platform Job Deduplication**: Deterministic matching on normalized company name, job title, and application domain to prevent identical postings across multiple boards.
4. **Skill Extraction & Category Normalization**: Software Engineering, Frontend, Backend, Cloud, DevOps, Data Science, AI/ML, Cybersecurity, Product Design, Product Management.
5. **JobRadar Frontend UI**: Listing cards/table toggle, filter controls (category, employment type, remote eligibility, experience level), job detail drawer, and application links.
