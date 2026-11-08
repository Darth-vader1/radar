"""
Operational CLI for RADAR.

    python -m app.cli seed
    python -m app.cli create-admin --email admin@example.com [--name "Ada Admin"] [--reset-password]

The password is read from the RADAR_ADMIN_PASSWORD environment variable, or prompted
for interactively. It is never accepted as a command-line argument (it would leak into
shell history and process listings).
"""
import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.security import get_password_hash
from app.database.session import AsyncSessionLocal, async_engine
from app.models.auth import AuditLog, Role, User

SUPER_ADMIN = "super_admin"
MIN_PASSWORD_LENGTH = 12


def _read_password() -> str:
    password = os.environ.get("RADAR_ADMIN_PASSWORD")
    if password is None:
        if not sys.stdin.isatty():
            raise SystemExit("Set RADAR_ADMIN_PASSWORD or run interactively to enter a password.")
        password = getpass.getpass("Admin password: ")
        if getpass.getpass("Repeat password: ") != password:
            raise SystemExit("Passwords do not match.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(f"Admin password must be at least {MIN_PASSWORD_LENGTH} characters.")
    return password


async def create_admin(email: str, full_name: str | None, reset_password: bool) -> str:
    email = email.strip().lower()
    async with AsyncSessionLocal() as db:
        role = await db.scalar(select(Role).where(Role.name == SUPER_ADMIN))
        if role is None:
            role = Role(name=SUPER_ADMIN, description="Full platform administration")
            db.add(role)
            await db.flush()

        user = await db.scalar(select(User).where(User.email == email).options(selectinload(User.roles)))
        if user is None:
            user = User(
                email=email,
                password_hash=get_password_hash(_read_password()),
                full_name=full_name,
                is_active=True,
                is_verified=True,
                roles=[role],
            )
            db.add(user)
            outcome = "created"
        else:
            if all(r.name != SUPER_ADMIN for r in user.roles):
                user.roles.append(role)
            if reset_password:
                user.password_hash = get_password_hash(_read_password())
                user.token_version = (user.token_version or 0) + 1  # sign out existing sessions
            user.is_active = True
            outcome = "promoted" if not reset_password else "promoted and password reset"

        await db.flush()
        db.add(AuditLog(
            actor_user_id=None,
            action=f"admin:{outcome.split()[0]}",
            resource_type="user",
            resource_id=str(user.id),
            metadata_json={"email": email, "via": "cli"},
        ))
        await db.commit()
    await async_engine.dispose()
    return outcome


async def seed() -> dict[str, int]:
    from app.seed import seed_reference_data

    async with AsyncSessionLocal() as db:
        added = await seed_reference_data(db)
    await async_engine.dispose()
    return added


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="RADAR operational commands")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("seed", help="Create default roles, permissions and sources (idempotent; never touches users)")

    admin = sub.add_parser("create-admin", help="Create a super admin, or promote an existing user")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", default=None)
    admin.add_argument("--reset-password", action="store_true", help="Also set a new password for an existing user")

    args = parser.parse_args(argv)
    if args.command == "seed":
        added = asyncio.run(seed())
        print("Seed complete. Added: " + ", ".join(f"{k}={v}" for k, v in added.items()))
    elif args.command == "create-admin":
        outcome = asyncio.run(create_admin(args.email, args.name, args.reset_password))
        print(f"Super admin {args.email} {outcome}.")


if __name__ == "__main__":
    main()
