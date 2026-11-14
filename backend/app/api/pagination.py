"""Offset pagination for list endpoints: one page of rows plus the total in X-Total-Count."""
from typing import Any, List

from fastapi import Response
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

TOTAL_HEADER = "X-Total-Count"


async def paginate(db: AsyncSession, stmt: Select, limit: int, offset: int, response: Response) -> List[Any]:
    """Runs `stmt` for one page and sets the matching total (same filters, no ordering) as a header."""
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    response.headers[TOTAL_HEADER] = str(total)
    return list((await db.scalars(stmt.limit(limit).offset(offset))).all())
