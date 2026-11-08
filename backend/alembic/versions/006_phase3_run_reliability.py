"""Run reliability: one active run per source, idempotent extracted_records

Revision ID: 006_run_reliability
Revises: 005_auth_hardening
Create Date: 2026-11-08
"""
from typing import Sequence, Union

from alembic import op

revision: str = "006_run_reliability"
down_revision: Union[str, None] = "005_auth_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. At most one QUEUED/RUNNING run per source. Fail all but the newest active run
    #    for any source that already violates this, then enforce it.
    op.execute("""
        UPDATE source_runs r
        SET status = 'FAILED',
            finished_at = now(),
            error_summary = 'Superseded: another run for this source was active (migration 006).'
        WHERE r.status IN ('QUEUED', 'RUNNING')
          AND EXISTS (
              SELECT 1 FROM source_runs newer
              WHERE newer.source_id = r.source_id
                AND newer.status IN ('QUEUED', 'RUNNING')
                AND (newer.created_at, newer.id) > (r.created_at, r.id)
          )
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_source_runs_one_active_per_source
        ON source_runs (source_id)
        WHERE status IN ('QUEUED', 'RUNNING')
    """)

    # 2. extracted_records: one row per (source, external_id) and per (source, content).
    #    Keep the earliest row of any duplicate group, preferring rows already linked to a
    #    canonical entity.
    for key in ("external_id", "content_hash"):
        extra = "AND external_id IS NOT NULL" if key == "external_id" else ""
        op.execute(f"""
            DELETE FROM extracted_records e
            USING (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY source_id, {key}
                    ORDER BY (canonical_entity_id IS NULL), created_at, id
                ) AS rn
                FROM extracted_records
                WHERE TRUE {extra}
            ) d
            WHERE e.id = d.id AND d.rn > 1
        """)
    op.execute("""
        CREATE UNIQUE INDEX uq_extracted_records_source_external_id
        ON extracted_records (source_id, external_id)
        WHERE external_id IS NOT NULL
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_extracted_records_source_content_hash
        ON extracted_records (source_id, content_hash)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_extracted_records_source_content_hash")
    op.execute("DROP INDEX IF EXISTS uq_extracted_records_source_external_id")
    op.execute("DROP INDEX IF EXISTS uq_source_runs_one_active_per_source")
