"""Add player_contacts_only to tournament_sms_settings.

Revision ID: 017_add_player_contacts_only_setting
Revises: 016_add_sms_test_mode_settings
Create Date: 2026-03-03
"""

from alembic import op
import sqlalchemy as sa


revision = "017_add_player_contacts_only_setting"
down_revision = "016_add_sms_test_mode_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tournament_sms_settings",
        sa.Column(
            "player_contacts_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("tournament_sms_settings", "player_contacts_only")
