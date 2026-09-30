"""Add per-event court assignment mode by date.

Revision ID: 022_add_court_assignment_by_date
Revises: 021_add_roster_source_identity
Create Date: 2026-09-30

Existing rows stay NULL, which resolves to DYNAMIC_CHECKIN.
"""

import sqlalchemy as sa

from alembic import op

revision = "022_add_court_assignment_by_date"
down_revision = "021_add_roster_source_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("event", sa.Column("court_assignment_by_date_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("event", "court_assignment_by_date_json")
