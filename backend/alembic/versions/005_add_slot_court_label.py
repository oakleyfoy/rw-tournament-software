"""Add court_label to schedule_slots

Revision ID: 005_slot_court_label
Revises: 004_match_metadata
Create Date: 2024-01-04 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005_slot_court_label"
down_revision: Union[str, None] = "004_match_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Check if court_label column already exists
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col["name"] for col in inspector.get_columns("scheduleslot")]

    # Add court_label column to schedule_slots table if it doesn't exist
    if "court_label" not in columns:
        op.add_column("scheduleslot", sa.Column("court_label", sa.String(), nullable=True))

    # Backfill existing rows: set court_label = court_number as string
    op.execute("""
        UPDATE scheduleslot
        SET court_label = CAST(court_number AS TEXT)
        WHERE court_label IS NULL
    """)

    # SQLite doesn't support ALTER COLUMN to change NOT NULL constraints
    # Since we're using SQLite and have backfilled all values, we'll leave it nullable
    # The application layer will handle the constraint
    if bind.dialect.name != "sqlite":
        op.alter_column("scheduleslot", "court_label", existing_type=sa.String(), nullable=False)

    # Create index for efficient queries
    op.create_index("idx_schedule_slots_version_court_label", "scheduleslot", ["schedule_version_id", "court_label"])


def downgrade() -> None:
    # Drop index
    op.drop_index("idx_schedule_slots_version_court_label", table_name="scheduleslot")

    # Remove court_label column
    op.drop_column("scheduleslot", "court_label")
