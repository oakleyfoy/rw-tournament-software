"""Add RW-OS source identity for Team and TemporaryPlayerLookup.

Revision ID: 021_add_roster_source_identity
Revises: 020_add_import_forecast_json
Create Date: 2026-08-29
"""

import sqlalchemy as sa

from alembic import op

revision = "021_add_roster_source_identity"
down_revision = "020_add_import_forecast_json"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("team", sa.Column("source_team_key", sa.Text(), nullable=True))
    op.create_index(
        "uq_event_source_team_key",
        "team",
        ["event_id", "source_team_key"],
        unique=True,
    )

    op.add_column("temporary_player_lookup", sa.Column("source", sa.Text(), nullable=True))
    op.add_column("temporary_player_lookup", sa.Column("source_team_key", sa.Text(), nullable=True))
    op.add_column("temporary_player_lookup", sa.Column("lineup_slot", sa.Integer(), nullable=True))
    op.create_index(
        "uq_rwos_lookup_source_identity",
        "temporary_player_lookup",
        ["tournament_id", "source", "source_team_key", "lineup_slot"],
        unique=True,
        postgresql_where=sa.text("source IS NOT NULL"),
        sqlite_where=sa.text("source IS NOT NULL"),
    )

    op.add_column("tournament_import", sa.Column("approved_source_hash", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tournament_import", "approved_source_hash")
    op.drop_index("uq_rwos_lookup_source_identity", table_name="temporary_player_lookup")
    op.drop_column("temporary_player_lookup", "lineup_slot")
    op.drop_column("temporary_player_lookup", "source_team_key")
    op.drop_column("temporary_player_lookup", "source")
    op.drop_index("uq_event_source_team_key", table_name="team")
    op.drop_column("team", "source_team_key")
