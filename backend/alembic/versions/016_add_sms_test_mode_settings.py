"""Add SMS test mode fields to tournament_sms_settings.

Revision ID: 016_add_sms_test_mode_settings
Revises: 015_add_sms_log_dedupe_key
"""

from alembic import op
import sqlalchemy as sa


revision = "016_add_sms_test_mode_settings"
down_revision = "015_add_sms_log_dedupe_key"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "tournament_sms_settings",
        sa.Column(
            "test_mode",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "tournament_sms_settings",
        sa.Column("test_allowlist", sa.String(), nullable=True),
    )


def downgrade():
    op.drop_column("tournament_sms_settings", "test_allowlist")
    op.drop_column("tournament_sms_settings", "test_mode")
