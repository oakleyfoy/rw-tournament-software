"""Add SMS delivery_mode, redirect_phone, and intended_phone_number.

Revision ID: 023_add_sms_delivery_mode_and_redirect
Revises: 022_add_court_assignment_by_date

Migrates legacy test_mode=True rows to delivery_mode=allowlist.
"""

import sqlalchemy as sa

from alembic import op

revision = "023_add_sms_delivery_mode_and_redirect"
down_revision = "022_add_court_assignment_by_date"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tournament_sms_settings",
        sa.Column(
            "delivery_mode",
            sa.String(),
            nullable=False,
            server_default="live",
        ),
    )
    op.add_column(
        "tournament_sms_settings",
        sa.Column("redirect_phone", sa.String(), nullable=True),
    )
    op.add_column(
        "sms_log",
        sa.Column("intended_phone_number", sa.String(), nullable=True),
    )

    # Backfill: legacy test_mode True → allowlist (SQLite stores bool as 0/1).
    op.execute("UPDATE tournament_sms_settings SET delivery_mode = 'allowlist' WHERE test_mode != 0")


def downgrade() -> None:
    op.drop_column("sms_log", "intended_phone_number")
    op.drop_column("tournament_sms_settings", "redirect_phone")
    op.drop_column("tournament_sms_settings", "delivery_mode")
