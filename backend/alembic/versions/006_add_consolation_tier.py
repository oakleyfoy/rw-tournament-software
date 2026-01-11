"""Add consolation_tier to match

Revision ID: 006_consolation_tier
Revises: 005_slot_court_label
Create Date: 2024-01-07 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006_consolation_tier"
down_revision: Union[str, None] = "005_slot_court_label"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Check if consolation_tier column already exists
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col["name"] for col in inspector.get_columns("match")]

    # Add consolation_tier column to match table if it doesn't exist
    if "consolation_tier" not in columns:
        op.add_column("match", sa.Column("consolation_tier", sa.Integer(), nullable=True))

    # Set consolation_tier = NULL for non-consolation matches (already null by default)
    # No backfill needed since it's nullable and defaults to None


def downgrade() -> None:
    # Remove consolation_tier column
    op.drop_column("match", "consolation_tier")
