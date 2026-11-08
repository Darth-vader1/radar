# Deploying RADAR

Production runs with `docker-compose.prod.yml` on a single Docker host. Caddy terminates TLS
(automatic Let's Encrypt certificates) and is the only service with published ports.

```
internet ──443──> proxy (Caddy) ──/api/*──> backend (FastAPI, uvicorn workers)
                                └─ else ──> frontend (Next.js standalone)
backend / worker / beat / migrate ──> postgres, redis   (internal network only)
```

| Service    | Role                                                                      |
|------------|---------------------------------------------------------------------------|
| `migrate`  | One-off: `alembic upgrade head` + `python -m app.cli seed`, then exits     |
| `backend`  | API. Starts only after `migrate` succeeds                                  |
| `worker`   | Celery worker that executes scrape runs                                    |
| `beat`     | Celery beat: cron-scheduled runs, stale-run reaper, event status refresh. **Run exactly one.** |
| `frontend` | Next.js server                                                            |
| `proxy`    | Caddy: TLS, routing, security headers; hides `/docs` and `/openapi.json`  |

## First deployment

1. Point your domain's DNS at the host. Open ports 80 and 443.
2. Create the environment file and fill in real values:
   ```bash
   cp .env.production.example .env.production
   python -c "import secrets; print(secrets.token_urlsafe(48))"   # run once per secret
   ```
   `SECRET_KEY`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `SITE_ADDRESS`, `PUBLIC_ORIGIN`
   and `TLS_MODE` (your e-mail for Let's Encrypt) are required. The stack refuses to start
   without them, and the API refuses to start with unsafe values such as the default
   secret key, DEBUG on, or localhost CORS origins.
3. Build and start:
   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build --wait
   ```
4. Create the first administrator. The password is read from the environment, never from
   the command line:
   ```bash
   export RADAR_ADMIN_PASSWORD='...'   # at least 12 characters
   docker compose -f docker-compose.prod.yml --env-file .env.production run --rm \
       -e RADAR_ADMIN_PASSWORD backend python -m app.cli create-admin --email you@example.com
   ```
5. Check health: `https://<your-domain>/api/v1/health/ready` should report
   `"ready": true` and `"environment": "production"`.

## Updating

```bash
git pull
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build --wait
```

`migrate` runs again first. Migrations are applied once, before new API and worker
containers start. Running scrapes are re-queued if a worker is replaced mid-run, because
tasks are acknowledged only after they finish.

## Notes

- **Seeding** only creates missing roles, permissions and sources. It never creates users,
  changes passwords, or inserts sample data.
- **Self-service registration** is off in production unless `ALLOW_PUBLIC_REGISTRATION=true`.
  Accounts created that way are always `standard_user`.
- **Rebuild the frontend if the backend's internal address changes.** The Next.js proxy
  target is fixed at build time (`BACKEND_INTERNAL_URL`, default `http://backend:8000`).
  Browsers normally reach the API through Caddy's `/api/*` route anyway.
- **Local smoke test without a domain:** set `SITE_ADDRESS=radar.test`,
  `PUBLIC_ORIGIN=https://radar.test:8443`, `TLS_MODE=internal`, `HTTP_PORT=8080` and
  `HTTPS_PORT=8443`, then use `curl -k --resolve radar.test:8443:127.0.0.1 https://radar.test:8443/`.
- Backups, monitoring and log shipping are covered in later phases of
  `docs/PRODUCTION_READINESS_PLAN.md`.
