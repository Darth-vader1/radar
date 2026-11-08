"""002_phase3_business_radar

Revision ID: 002_phase3_biz
Revises: 001_phase1_init
Create Date: 2026-11-08 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '002_phase3_biz'
down_revision: Union[str, None] = '001_phase1_init'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. businesses table
    op.create_table(
        'businesses',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('normalized_name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(length=120), nullable=True),
        sa.Column('subcategory', sa.String(length=120), nullable=True),
        sa.Column('category_origin', sa.String(length=40), server_default='UNVERIFIED', nullable=False),
        sa.Column('phone_number', sa.String(length=60), nullable=True),
        sa.Column('normalized_phone_e164', sa.String(length=30), nullable=True),
        sa.Column('phone_verification_status', sa.String(length=40), server_default='MISSING', nullable=False),
        sa.Column('public_email', sa.String(length=255), nullable=True),
        sa.Column('email_domain', sa.String(length=255), nullable=True),
        sa.Column('email_verification_status', sa.String(length=40), server_default='MISSING', nullable=False),
        sa.Column('website_url', sa.Text(), nullable=True),
        sa.Column('website_domain', sa.String(length=255), nullable=True),
        sa.Column('website_status', sa.String(length=60), server_default='NOT_CHECKED', nullable=False),
        sa.Column('has_online_ordering', sa.Boolean(), nullable=True),
        sa.Column('online_presence', sa.String(length=40), server_default='UNKNOWN', nullable=False),
        sa.Column('physical_address', sa.Text(), nullable=True),
        sa.Column('city', sa.String(length=120), nullable=True),
        sa.Column('state', sa.String(length=120), nullable=True),
        sa.Column('country', sa.String(length=120), nullable=False),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.Column('primary_source_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('original_source_url', sa.Text(), nullable=False),
        sa.Column('lead_score', sa.SmallInteger(), server_default='0', nullable=False),
        sa.Column('lead_score_explanation', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('discovered_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['primary_source_id'], ['sources.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_businesses_category'), 'businesses', ['category'], unique=False)
    op.create_index(op.f('ix_businesses_city'), 'businesses', ['city'], unique=False)
    op.create_index(op.f('ix_businesses_country'), 'businesses', ['country'], unique=False)
    op.create_index(op.f('ix_businesses_email_domain'), 'businesses', ['email_domain'], unique=False)
    op.create_index(op.f('ix_businesses_lead_score'), 'businesses', ['lead_score'], unique=False)
    op.create_index(op.f('ix_businesses_name'), 'businesses', ['name'], unique=False)
    op.create_index(op.f('ix_businesses_normalized_name'), 'businesses', ['normalized_name'], unique=False)
    op.create_index(op.f('ix_businesses_normalized_phone_e164'), 'businesses', ['normalized_phone_e164'], unique=False)
    op.create_index(op.f('ix_businesses_public_email'), 'businesses', ['public_email'], unique=False)
    op.create_index(op.f('ix_businesses_state'), 'businesses', ['state'], unique=False)
    op.create_index(op.f('ix_businesses_website_domain'), 'businesses', ['website_domain'], unique=False)
    op.create_index(op.f('ix_businesses_website_status'), 'businesses', ['website_status'], unique=False)

    # 2. business_contacts table
    op.create_table(
        'business_contacts',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('business_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('contact_type', sa.String(length=40), nullable=False),
        sa.Column('value', sa.String(length=320), nullable=False),
        sa.Column('normalized_value', sa.String(length=320), nullable=False),
        sa.Column('discovery_source', sa.String(length=120), nullable=False),
        sa.Column('source_url', sa.Text(), nullable=True),
        sa.Column('data_origin', sa.String(length=40), server_default='UNVERIFIED', nullable=False),
        sa.Column('verification_status', sa.String(length=40), server_default='UNVERIFIED', nullable=False),
        sa.Column('confidence_score', sa.Float(), server_default='0.5', nullable=False),
        sa.Column('is_primary', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_business_contacts_business_id'), 'business_contacts', ['business_id'], unique=False)
    op.create_index(op.f('ix_business_contacts_normalized_value'), 'business_contacts', ['normalized_value'], unique=False)

    # 3. business_social_profiles table
    op.create_table(
        'business_social_profiles',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('business_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('platform', sa.String(length=40), nullable=False),
        sa.Column('profile_url', sa.Text(), nullable=False),
        sa.Column('handle', sa.String(length=160), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('discovery_source', sa.String(length=120), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_business_social_profiles_business_id'), 'business_social_profiles', ['business_id'], unique=False)

    # 4. email_verifications table
    op.create_table(
        'email_verifications',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('business_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('email_address', sa.String(length=255), nullable=False),
        sa.Column('syntax_valid', sa.Boolean(), nullable=False),
        sa.Column('domain', sa.String(length=255), nullable=False),
        sa.Column('mx_records_found', sa.Boolean(), nullable=True),
        sa.Column('mx_hosts', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=True),
        sa.Column('disposable_domain', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('role_based_prefix', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('status', sa.String(length=40), server_default='UNKNOWN', nullable=False),
        sa.Column('confidence_score', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('checked_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_email_verifications_business_id'), 'email_verifications', ['business_id'], unique=False)
    op.create_index(op.f('ix_email_verifications_domain'), 'email_verifications', ['domain'], unique=False)
    op.create_index(op.f('ix_email_verifications_email_address'), 'email_verifications', ['email_address'], unique=False)

    # 5. lead_scoring_rules table
    op.create_table(
        'lead_scoring_rules',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('rule_key', sa.String(length=80), nullable=False),
        sa.Column('label', sa.String(length=160), nullable=False),
        sa.Column('points', sa.SmallInteger(), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('conditions_json', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_lead_scoring_rules_rule_key'), 'lead_scoring_rules', ['rule_key'], unique=True)

    # 6. lead_scores table
    op.create_table(
        'lead_scores',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('business_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('score', sa.SmallInteger(), nullable=False),
        sa.Column('breakdown', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('scoring_version', sa.String(length=40), server_default='1.0', nullable=False),
        sa.Column('calculated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_lead_scores_business_id'), 'lead_scores', ['business_id'], unique=False)

    # 7. Seed default lead scoring rules
    op.execute("""
        INSERT INTO lead_scoring_rules (id, rule_key, label, points, is_enabled, conditions_json, created_at, updated_at)
        VALUES
          (gen_random_uuid(), 'no_website_found', 'No website found', 30, true, '{"field": "website_status", "equals": "NO_WEBSITE_FOUND"}', now(), now()),
          (gen_random_uuid(), 'website_broken', 'Website unreachable or broken', 25, true, '{"field": "website_status", "in": ["WEBSITE_BROKEN", "WEBSITE_UNREACHABLE"]}', now(), now()),
          (gen_random_uuid(), 'no_online_ordering', 'No online ordering system detected', 20, true, '{"field": "has_online_ordering", "equals": false}', now(), now()),
          (gen_random_uuid(), 'active_social_media', 'Active social media profile observed', 15, true, '{"min_social_profiles": 1}', now(), now()),
          (gen_random_uuid(), 'public_business_email', 'Public corporate email available', 15, true, '{"has_email": true}', now(), now()),
          (gen_random_uuid(), 'high_value_category', 'High commercial intent category', 10, true, '{"categories": ["restaurant", "pharmacy", "hospital", "hotel", "retail"]}', now(), now()),
          (gen_random_uuid(), 'recently_discovered', 'Discovered within last 14 days', 5, true, '{"max_days_ago": 14}', now(), now())
        ON CONFLICT (rule_key) DO NOTHING;
    """)


def downgrade() -> None:
    op.drop_table('lead_scores')
    op.drop_table('lead_scoring_rules')
    op.drop_table('email_verifications')
    op.drop_table('business_social_profiles')
    op.drop_table('business_contacts')
    op.drop_table('businesses')
