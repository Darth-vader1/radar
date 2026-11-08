"""003_phase4_job_radar

Revision ID: 003_phase4_job
Revises: 002_phase3_biz
Create Date: 2026-11-08 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '003_phase4_job'
down_revision: Union[str, None] = '002_phase3_biz'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. jobs table
    op.create_table(
        'jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('normalized_title', sa.String(length=255), nullable=False),
        sa.Column('company_name', sa.String(length=200), nullable=False),
        sa.Column('normalized_company', sa.String(length=200), nullable=False),
        sa.Column('company_website', sa.Text(), nullable=True),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('requirements_text', sa.Text(), nullable=True),
        sa.Column('education_requirements', sa.Text(), nullable=True),
        sa.Column('category', sa.String(length=60), server_default='OTHER_TECH', nullable=False),
        sa.Column('employment_type', sa.String(length=40), server_default='FULL_TIME', nullable=False),
        sa.Column('remote_status', sa.String(length=40), server_default='UNSPECIFIED', nullable=False),
        sa.Column('experience_level', sa.String(length=40), server_default='UNSPECIFIED', nullable=False),
        sa.Column('salary_min', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('salary_max', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('salary_currency', sa.String(length=10), nullable=True),
        sa.Column('salary_period', sa.String(length=20), nullable=True),
        sa.Column('salary_is_inferred', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('location_text', sa.String(length=200), nullable=True),
        sa.Column('city', sa.String(length=120), nullable=True),
        sa.Column('country', sa.String(length=120), nullable=True),
        sa.Column('application_deadline', sa.DateTime(timezone=True), nullable=True),
        sa.Column('application_url', sa.Text(), nullable=False),
        sa.Column('canonical_apply_domain', sa.String(length=255), nullable=True),
        sa.Column('primary_source_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('source_platform', sa.String(length=100), nullable=False),
        sa.Column('original_source_url', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=40), server_default='ACTIVE', nullable=False),
        sa.Column('duplicate_cluster_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('other_sources_count', sa.SmallInteger(), server_default='0', nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('discovered_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['primary_source_id'], ['sources.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_jobs_canonical_apply_domain'), 'jobs', ['canonical_apply_domain'], unique=False)
    op.create_index(op.f('ix_jobs_category'), 'jobs', ['category'], unique=False)
    op.create_index(op.f('ix_jobs_city'), 'jobs', ['city'], unique=False)
    op.create_index(op.f('ix_jobs_company_name'), 'jobs', ['company_name'], unique=False)
    op.create_index(op.f('ix_jobs_country'), 'jobs', ['country'], unique=False)
    op.create_index(op.f('ix_jobs_duplicate_cluster_id'), 'jobs', ['duplicate_cluster_id'], unique=False)
    op.create_index(op.f('ix_jobs_employment_type'), 'jobs', ['employment_type'], unique=False)
    op.create_index(op.f('ix_jobs_experience_level'), 'jobs', ['experience_level'], unique=False)
    op.create_index(op.f('ix_jobs_normalized_company'), 'jobs', ['normalized_company'], unique=False)
    op.create_index(op.f('ix_jobs_normalized_title'), 'jobs', ['normalized_title'], unique=False)
    op.create_index(op.f('ix_jobs_remote_status'), 'jobs', ['remote_status'], unique=False)
    op.create_index(op.f('ix_jobs_status'), 'jobs', ['status'], unique=False)
    op.create_index(op.f('ix_jobs_title'), 'jobs', ['title'], unique=False)

    # 2. job_skills table
    op.create_table(
        'job_skills',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('job_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('skill_name', sa.String(length=100), nullable=False),
        sa.Column('normalized_skill', sa.String(length=100), nullable=False),
        sa.Column('is_required', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('extraction_origin', sa.String(length=40), server_default='INFERRED', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_job_skills_job_id'), 'job_skills', ['job_id'], unique=False)
    op.create_index(op.f('ix_job_skills_normalized_skill'), 'job_skills', ['normalized_skill'], unique=False)


def downgrade() -> None:
    op.drop_table('job_skills')
    op.drop_table('jobs')
