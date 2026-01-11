"""Add match metadata: round_index and indexes

Revision ID: 004_match_metadata
Revises: 003_court_names
Create Date: 2024-01-03 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004_match_metadata"
down_revision: Union[str, None] = "003_court_names"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Check if round_index column already exists
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col["name"] for col in inspector.get_columns("match")]

    # Add round_index column to matches table if it doesn't exist
    if "round_index" not in columns:
        op.add_column("match", sa.Column("round_index", sa.Integer(), nullable=True))

    # Backfill existing rows: set round_index = round_number if null
    op.execute("""
        UPDATE match
        SET round_index = round_number
        WHERE round_index IS NULL
    """)

    # SQLite doesn't support ALTER COLUMN to change NOT NULL constraints
    # Since we're using SQLite and have backfilled all values, we'll leave it nullable
    # The application layer will handle the constraint
    if bind.dialect.name != "sqlite":
        op.alter_column("match", "round_index", existing_type=sa.Integer(), nullable=False, server_default="1")

    # Create indexes for efficient queries
    op.create_index("idx_matches_version_type_round", "match", ["schedule_version_id", "match_type", "round_index"])

    op.create_index("idx_matches_event_type_round", "match", ["event_id", "match_type", "round_index"])


def downgrade() -> None:
    # Drop indexes
    op.drop_index("idx_matches_event_type_round", table_name="match")
    op.drop_index("idx_matches_version_type_round", table_name="match")

    # Remove round_index column
    op.drop_column("match", "round_index")
