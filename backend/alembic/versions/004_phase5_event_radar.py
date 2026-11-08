"""004_phase5_event_radar

Revision ID: 004_phase5_event
Revises: 003_phase4_job
Create Date: 2026-11-08 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '004_phase5_event'
down_revision: Union[str, None] = '003_phase4_job'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. events table
    op.create_table(
        'events',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('normalized_name', sa.String(length=255), nullable=False),
        sa.Column('organizer', sa.String(length=200), nullable=True),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('event_type', sa.String(length=40), server_default='HACKATHON', nullable=False),
        sa.Column('delivery_mode', sa.String(length=40), server_default='VIRTUAL', nullable=False),
        sa.Column('location_text', sa.String(length=200), nullable=True),
        sa.Column('city', sa.String(length=120), nullable=True),
        sa.Column('country', sa.String(length=120), nullable=True),
        sa.Column('registration_url', sa.Text(), nullable=False),
        sa.Column('event_website', sa.Text(), nullable=True),
        sa.Column('registration_opens_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('registration_deadline', sa.DateTime(timezone=True), nullable=True),
        sa.Column('start_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('prize_summary', sa.Text(), nullable=True),
        sa.Column('has_cash_prizes', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('prize_amount_usd_est', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('is_free_participation', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('eligibility_text', sa.Text(), nullable=True),
        sa.Column('participation_requirements', sa.Text(), nullable=True),
        sa.Column('student_eligible', sa.Boolean(), nullable=True),
        sa.Column('international_eligible', sa.Boolean(), nullable=True),
        sa.Column('status', sa.String(length=40), server_default='OPEN_REGISTRATION', nullable=False),
        sa.Column('primary_source_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('source_platform', sa.String(length=100), server_default='devpost', nullable=False),
        sa.Column('source_url', sa.Text(), nullable=False),
        sa.Column('discovered_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['primary_source_id'], ['sources.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_events_name', 'events', ['name'])
    op.create_index('ix_events_normalized_name', 'events', ['normalized_name'])
    op.create_index('ix_events_organizer', 'events', ['organizer'])
    op.create_index('ix_events_event_type', 'events', ['event_type'])
    op.create_index('ix_events_delivery_mode', 'events', ['delivery_mode'])
    op.create_index('ix_events_status', 'events', ['status'])
    op.create_index('ix_events_registration_deadline', 'events', ['registration_deadline'])
    op.create_index('ix_events_has_cash_prizes', 'events', ['has_cash_prizes'])
    op.create_index('ix_events_city', 'events', ['city'])
    op.create_index('ix_events_country', 'events', ['country'])
    op.create_index('ix_events_status_type_delivery', 'events', ['status', 'event_type', 'delivery_mode'])
    op.create_index('ix_events_deadline_status', 'events', ['registration_deadline', 'status'])
    op.create_index('ix_events_norm_name_organizer', 'events', ['normalized_name', 'organizer'])

    # 2. event_categories table
    op.create_table(
        'event_categories',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('slug', sa.String(length=80), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug')
    )
    op.create_index('ix_event_categories_slug', 'event_categories', ['slug'])

    # 3. event_category_links table
    op.create_table(
        'event_category_links',
        sa.Column('event_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('category_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('origin', sa.String(length=20), server_default='INFERRED', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['category_id'], ['event_categories.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('event_id', 'category_id')
    )

    # 4. Seed default categories
    default_categories = [
        ('ai', 'Artificial Intelligence', 'Machine learning, LLMs, neural networks, computer vision'),
        ('machine-learning', 'Machine Learning', 'Data modeling, predictive analytics, deep learning'),
        ('web-dev', 'Web Development', 'Full-stack, frontend, backend web systems, APIs'),
        ('mobile-dev', 'Mobile Development', 'iOS, Android, React Native, Flutter applications'),
        ('cloud', 'Cloud & DevOps', 'Serverless, Kubernetes, cloud architectures, infrastructure'),
        ('blockchain', 'Web3 & Blockchain', 'Smart contracts, DeFi, crypto, decentralized protocols'),
        ('cybersecurity', 'Cybersecurity', 'InfoSec, ethical hacking, CTF competitions, cryptography'),
        ('data-science', 'Data Science', 'Data mining, statistics, visualization, business intelligence'),
        ('robotics', 'Robotics & Hardware', 'IoT, embedded systems, robotics, firmware'),
        ('entrepreneurship', 'Startup & Innovation', 'Venture grants, pitch competitions, accelerators'),
        ('other', 'General Tech', 'Broad technology innovation and open hackathons'),
    ]

    for slug, name, desc in default_categories:
        op.execute(
            sa.text(
                "INSERT INTO event_categories (slug, name, description) "
                "VALUES (:slug, :name, :desc) ON CONFLICT (slug) DO NOTHING;"
            ).bindparams(slug=slug, name=name, desc=desc)
        )


def downgrade() -> None:
    op.drop_table('event_category_links')
    op.drop_table('event_categories')
    op.drop_table('events')
