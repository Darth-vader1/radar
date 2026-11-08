"""
Deprecated entry point kept so old instructions still work. Seeding now lives in the
backend package (it ships inside the Docker image):

    cd backend && python -m app.cli seed

The previous version of this script reset every user's password to a hard-coded value,
granted every user super_admin, created a default admin with a known password, and
inserted made-up "verified" sample events. None of that happens any more: the seed only
creates missing roles, permissions and sources. Create administrators with
`python -m app.cli create-admin --email you@example.com`.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend")))

from app.cli import main  # noqa: E402

if __name__ == "__main__":
    main(["seed"])
