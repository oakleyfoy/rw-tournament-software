"""Add is_archived flag to tournament.

Revision ID: 018_add_tournament_archive_flag
Revises: 017_add_player_contacts_only_setting
Create Date: 2026-03-18
"""

from alembic import op
import sqlalchemy as sa


revision = "018_add_tournament_archive_flag"
down_revision = "017_add_player_contacts_only_setting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tournament",
        sa.Column(
            "is_archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("tournament", "is_archived")
