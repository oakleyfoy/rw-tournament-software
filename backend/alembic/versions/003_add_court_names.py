"""add court names to tournament

Revision ID: 003
Revises: 002
Create Date: 2024-01-01 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003_court_names"
down_revision: Union[str, None] = "002_schedule"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add court_names column to tournament table
    op.add_column("tournament", sa.Column("court_names", sa.JSON(), nullable=True))


def downgrade() -> None:
    # Remove court_names column from tournament table
    op.drop_column("tournament", "court_names")
