"""Add placement_type to match

Revision ID: 007_placement_type
Revises: 006_consolation_tier
Create Date: 2024-01-07 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "007_placement_type"
down_revision: Union[str, None] = "006_consolation_tier"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Check if placement_type column already exists
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col["name"] for col in inspector.get_columns("match")]

    # Add placement_type column to match table if it doesn't exist
    if "placement_type" not in columns:
        op.add_column("match", sa.Column("placement_type", sa.String(), nullable=True))

    # Set placement_type = NULL for non-placement matches (already null by default)
    # No backfill needed since it's nullable and defaults to None


def downgrade() -> None:
    # Remove placement_type column
    op.drop_column("match", "placement_type")
