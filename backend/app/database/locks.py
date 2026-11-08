from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def advisory_xact_lock(db: AsyncSession, *keys: str) -> None:
    """
    Takes PostgreSQL transaction-scoped advisory locks on the given string keys; they are
    released automatically at commit/rollback.

    Ingestion services dedupe with "SELECT existing, else INSERT". Without a lock, two runs
    ingesting the same entity concurrently both see nothing and both insert. Locking on the
    entity's dedup key makes the second wait and then find the first one's row.

    Keys are sorted so that callers locking several keys always acquire them in the same
    order (no deadlocks).
    """
    for key in sorted(set(k for k in keys if k)):
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": key})
