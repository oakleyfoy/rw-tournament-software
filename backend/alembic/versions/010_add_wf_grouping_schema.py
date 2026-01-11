"""Add WF Grouping schema: team_avoid_edge table and wf_group_index

Revision ID: 010_wf_grouping
Revises: 009_preferred_day
Create Date: 2026-01-07 23:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "010_wf_grouping"
down_revision: Union[str, None] = "009_preferred_day"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # Check if team_avoid_edge table exists
    tables = inspector.get_table_names()

    if "team_avoid_edge" not in tables:
        # Create team_avoid_edge table
        op.create_table(
            "team_avoid_edge",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("event_id", sa.Integer(), nullable=False),
            sa.Column("team_id_a", sa.Integer(), nullable=False),
            sa.Column("team_id_b", sa.Integer(), nullable=False),
            sa.Column("reason", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint("team_id_a < team_id_b", name="ck_team_order"),
            sa.ForeignKeyConstraint(
                ["event_id"],
                ["event.id"],
            ),
            sa.ForeignKeyConstraint(
                ["team_id_a"],
                ["team.id"],
            ),
            sa.ForeignKeyConstraint(
                ["team_id_b"],
                ["team.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("event_id", "team_id_a", "team_id_b", name="uq_event_avoid_edge"),
        )
        op.create_index(op.f("ix_team_avoid_edge_event_id"), "team_avoid_edge", ["event_id"], unique=False)
        op.create_index(op.f("ix_team_avoid_edge_team_id_a"), "team_avoid_edge", ["team_id_a"], unique=False)
        op.create_index(op.f("ix_team_avoid_edge_team_id_b"), "team_avoid_edge", ["team_id_b"], unique=False)

    # Check if wf_group_index column exists in team table
    team_columns = [col["name"] for col in inspector.get_columns("team")]

    if "wf_group_index" not in team_columns:
        # Add wf_group_index column to team table
        op.add_column("team", sa.Column("wf_group_index", sa.Integer(), nullable=True))
        op.create_index(op.f("ix_team_wf_group_index"), "team", ["wf_group_index"], unique=False)


def downgrade() -> None:
    # Drop wf_group_index from team table
    op.drop_index(op.f("ix_team_wf_group_index"), table_name="team")
    op.drop_column("team", "wf_group_index")

    # Drop team_avoid_edge table
    op.drop_index(op.f("ix_team_avoid_edge_team_id_b"), table_name="team_avoid_edge")
    op.drop_index(op.f("ix_team_avoid_edge_team_id_a"), table_name="team_avoid_edge")
    op.drop_index(op.f("ix_team_avoid_edge_event_id"), table_name="team_avoid_edge")
    op.drop_table("team_avoid_edge")
