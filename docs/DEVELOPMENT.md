# Development

## Setup

```bash
# Backend (Python 3.12)
cd backend
python -m venv venv
./venv/Scripts/pip install -r requirements-dev.lock   # Linux/macOS: ./venv/bin/pip
./venv/Scripts/python -m alembic upgrade head
./venv/Scripts/python -m app.cli seed
./venv/Scripts/python -m app.cli create-admin --email you@example.com

# Frontend (Node 20)
cd frontend
npm ci
```

PostgreSQL and Redis come from Docker (`radar_postgres` on port 5433 and `radar_redis` on
port 6379, as configured in `.env`).

## Running everything (Windows)

```bash
scripts\dev.cmd        # start the whole stack (or double-click it)
scripts\dev-stop.cmd   # stop it again (add -IncludeDatabase to also stop Postgres/Redis)
```

`dev.cmd` does the following:

- Starts Docker Desktop and the database containers if they aren't running.
- Applies pending migrations.
- Opens titled windows for the API, Celery worker, Celery beat and frontend, then waits until they respond and opens the browser.

Ports are chosen as follows:

- The API uses port 8000, or the next free port if another program holds it.
- The frontend uses port 3000 and is pointed at that API port automatically.

Running it again is safe. Services that are already running are detected and left alone,
which matters for beat: two copies would start every scheduled scrape twice.
`dev-stop.cmd` only stops this project's processes. Other apps on the same ports are left alone.

Options:
- `scripts\dev.cmd -NoBrowser` does not open the browser.
- `scripts\dev.cmd -SkipMigrations` does not run `alembic upgrade head`.

To run the services by hand instead, use one terminal for each:

| Process | Command (from `backend/` or `frontend/`) |
|---|---|
| API | `./venv/Scripts/python -m uvicorn app.main:app --reload --port 8000` |
| Worker | `./venv/Scripts/celery -A workers.celery_app worker --pool=solo --loglevel=info` |
| Scheduler | `./venv/Scripts/celery -A workers.celery_app beat --loglevel=info` |
| Frontend | `npm run dev` |

`--pool=solo` is required on Windows. The Celery worker does not auto-reload: restart it
after changing backend code.

## Before you push

```bash
python scripts/check.py          # same checks as CI
python scripts/check.py --fast   # skips the frontend build and dependency audits
```

CI (`.github/workflows/ci.yml`) runs on every push to `main` and on every pull request:

- **Backend:** ruff, mypy, `alembic upgrade head` followed by `alembic check` (the models and migrations must agree), and pytest against real PostgreSQL and Redis.
- **Frontend:** ESLint, `tsc`, and `next build`.
- **Dependency audits:** pip-audit and `npm audit` (production dependencies, high severity and above).
- **Images:** both Docker images are built, smoke-tested, and scanned with Trivy (fails on fixable critical vulnerabilities).

## Dependencies

Python dependencies are declared with ranges in `backend/requirements*.txt` and pinned in
`backend/requirements*.lock`. The Docker image, CI, and local setup all install the lockfiles.

After changing a `requirements*.txt` file, regenerate both lockfiles from `backend/`:

```bash
./venv/Scripts/uv pip compile requirements.txt --universal --python-version 3.12 -o requirements.lock
./venv/Scripts/uv pip compile requirements-dev.txt --universal --python-version 3.12 -o requirements-dev.lock
./venv/Scripts/uv pip sync requirements-dev.lock --python venv/Scripts/python.exe
```

To upgrade everything within the declared ranges, add `--upgrade` to the compile commands.

Frontend dependencies are pinned by `frontend/package-lock.json`. Use `npm ci` to install
exactly what the lockfile says.

Dependabot (`.github/dependabot.yml`) opens weekly update PRs for pip, npm, GitHub Actions,
and Docker base images.

**Known exception:** a moderate `minimatch` advisory in the ESLint toolchain (dev-only, used
only at lint time). It clears once the toolchain moves to ESLint 9, which comes with the
Next.js 16 upgrade.

## Database changes

1. Change the models in `backend/app/models/`.
2. Create a migration: `./venv/Scripts/python -m alembic revision --autogenerate -m "describe change"`.
   Review the generated file. Autogenerate misses some changes, such as renames and data migrations.
3. `alembic upgrade head`, then run the tests. CI's `alembic check` fails if models and migrations disagree.

## Releases

Push a tag like `v1.2.0`. `.github/workflows/release.yml` builds both images and publishes them to
`ghcr.io/<owner>/<repo>-backend` and `ghcr.io/<owner>/<repo>-frontend`, tagged with the version.
