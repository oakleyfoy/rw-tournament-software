"""Add dedupe_key column to sms_log for idempotent sends.

Revision ID: 015_add_sms_log_dedupe_key
Revises: 014_add_player_sms_foundation
"""

from alembic import op
import sqlalchemy as sa


revision = "015_add_sms_log_dedupe_key"
down_revision = "014_add_player_sms_foundation"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sms_log", sa.Column("dedupe_key", sa.String(), nullable=True))
    op.create_index("ix_sms_log_dedupe_key", "sms_log", ["dedupe_key"])


def downgrade():
    op.drop_index("ix_sms_log_dedupe_key", table_name="sms_log")
    op.drop_column("sms_log", "dedupe_key")
