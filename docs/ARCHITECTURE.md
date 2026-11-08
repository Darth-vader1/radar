# RADAR — Architecture Specification

Refer to the complete technical blueprint in `architecture_and_plan.md` in the conversation artifact directory for full ERDs, source catalogs, and pipeline data flow specifications.

## Key Subsystems
1. **SSRF Guard**: Pre-connect IP resolution rejecting `127.0.0.0/8`, `169.254.169.254`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `::1`, and port limits.
2. **Politeness**: `robots.txt` caching in Redis (24h TTL) and per-domain token bucket rate limiting.
3. **Pipeline Stages**:
   - `DISCOVER` → `FETCH` → `EXTRACT` → `NORMALIZE` → `VALIDATE` → `DEDUPLICATE` → `ENRICH` → `AI_CLASSIFY` → `STORE` → `INDEX` → `DISPLAY`
4. **Source Adapters**:
   - `SourceAdapter` ABC with `discover()`, `fetch()`, `extract()`, `normalize()`, and `validate()`.
