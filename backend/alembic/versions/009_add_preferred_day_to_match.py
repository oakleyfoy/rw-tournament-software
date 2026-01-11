"""Add preferred_day to match table

Revision ID: 009_preferred_day
Revises: 008_teams
Create Date: 2026-01-07 18:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009_preferred_day"
down_revision: Union[str, None] = "008_teams"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # Check if preferred_day column exists in match table
    match_columns = [col["name"] for col in inspector.get_columns("match")]

    if "preferred_day" not in match_columns:
        # Add preferred_day column to match table (nullable integer 0-6)
        op.add_column("match", sa.Column("preferred_day", sa.Integer(), nullable=True))


def downgrade() -> None:
    # Remove preferred_day column from match table
    op.drop_column("match", "preferred_day")
