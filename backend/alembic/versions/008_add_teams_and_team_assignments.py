"""Add teams table and team assignments to match

Revision ID: 008_teams
Revises: 007_placement_type
Create Date: 2026-01-07 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "008_teams"
down_revision: Union[str, None] = "007_placement_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # Check if team table already exists
    tables = inspector.get_table_names()

    if "team" not in tables:
        # Create team table
        op.create_table(
            "team",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("event_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("seed", sa.Integer(), nullable=True),
            sa.Column("rating", sa.Float(), nullable=True),
            sa.Column("registration_timestamp", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["event_id"],
                ["event.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("event_id", "seed", name="uq_event_seed"),
            sa.UniqueConstraint("event_id", "name", name="uq_event_team_name"),
        )
        op.create_index(op.f("ix_team_event_id"), "team", ["event_id"], unique=False)

    # Check if team_a_id and team_b_id columns exist in match table
    match_columns = [col["name"] for col in inspector.get_columns("match")]

    if "team_a_id" not in match_columns:
        # Add team_a_id column to match table (with FK inline)
        # SQLite doesn't support adding FK constraints separately, so we just add the column
        # The FK will be enforced by SQLModel at the ORM level
        op.add_column("match", sa.Column("team_a_id", sa.Integer(), nullable=True))

    if "team_b_id" not in match_columns:
        # Add team_b_id column to match table (with FK inline)
        op.add_column("match", sa.Column("team_b_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    # Remove columns from match table
    # Note: SQLite doesn't maintain explicit FK constraints in migrations,
    # they're handled by the ORM
    op.drop_column("match", "team_b_id")
    op.drop_column("match", "team_a_id")

    # Drop team table
    op.drop_index(op.f("ix_team_event_id"), table_name="team")
    op.drop_table("team")
