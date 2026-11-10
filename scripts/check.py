#!/usr/bin/env python3
"""
Run the same checks as CI, locally, before you push.

    python scripts/check.py           # everything
    python scripts/check.py --fast    # skip the frontend production build and dependency audits

Needs: backend/venv with requirements-dev.lock installed, frontend/node_modules, and the
dev PostgreSQL + Redis running (integration tests create a throwaway "<db>_test" database).
Exits non-zero if any check fails; every check runs so you see all failures at once.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"


def venv_tool(name: str) -> str:
    for candidate in (BACKEND / "venv" / "Scripts" / f"{name}.exe", BACKEND / "venv" / "bin" / name):
        if candidate.exists():
            return str(candidate)
    sys.exit(f"Could not find '{name}' in backend/venv. Run: pip install -r backend/requirements-dev.lock")


def npm() -> str:
    path = shutil.which("npm")
    if not path:
        sys.exit("npm not found on PATH.")
    return path


def test_db_sync_url() -> str:
    """The integration tests migrate '<dev db>_test'; alembic check runs against it."""
    sys.path.insert(0, str(BACKEND))
    from sqlalchemy.engine import make_url

    from app.core.config import settings

    url = make_url(settings.DATABASE_SYNC_URL)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


def run(label: str, cmd: list[str], cwd: Path, env: dict | None = None) -> bool:
    print(f"\n=== {label}\n$ {' '.join(Path(c).name if i == 0 else c for i, c in enumerate(cmd))}", flush=True)
    start = time.time()
    ok = subprocess.run(cmd, cwd=cwd, env={**os.environ, **(env or {})}).returncode == 0
    print(f"--- {'PASS' if ok else 'FAIL'}: {label} ({time.time() - start:.0f}s)", flush=True)
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fast", action="store_true", help="skip frontend build and dependency audits")
    args = parser.parse_args()

    python = venv_tool("python")
    checks: list[tuple[str, list[str], Path, dict | None]] = [
        ("Backend lint (ruff)", [venv_tool("ruff"), "check", "."], BACKEND, None),
        ("Backend types (mypy)", [venv_tool("mypy")], BACKEND, None),
        ("Backend tests (pytest)", [python, "-m", "pytest", "-q", "-p", "no:cacheprovider"], BACKEND, None),
        # Runs after pytest, which (re)creates and migrates the test database.
        ("Migrations match models (alembic check)", [python, "-m", "alembic", "check"], BACKEND,
         {"DATABASE_SYNC_URL": test_db_sync_url()}),
        ("Frontend lint (eslint)", [npm(), "run", "lint"], FRONTEND, None),
        ("Frontend types (tsc)", [npm(), "run", "typecheck"], FRONTEND, None),
    ]
    if not args.fast:
        checks += [
            ("Frontend production build", [npm(), "run", "build"], FRONTEND, {"NEXT_TELEMETRY_DISABLED": "1"}),
            ("Python dependency audit", [venv_tool("pip-audit"), "-r", "requirements.lock", "--progress-spinner", "off"],
             BACKEND, None),
            ("Node dependency audit (production)", [npm(), "audit", "--omit=dev", "--audit-level=high"], FRONTEND, None),
        ]

    results = [(label, run(label, cmd, cwd, env)) for label, cmd, cwd, env in checks]

    print("\n=== Summary")
    for label, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    failed = [label for label, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
