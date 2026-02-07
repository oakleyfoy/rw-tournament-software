"""add_locked_flag_to_match_assignment

Revision ID: 14c09bfe72f6
Revises: 011_finalization
Create Date: 2026-01-12 12:50:29.334707

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '14c09bfe72f6'
down_revision = '011_finalization'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add locked column to matchassignment table
    # Default False for existing assignments (auto-assigned, not locked)
    op.add_column('matchassignment', sa.Column('locked', sa.Boolean(), nullable=False, server_default='0'))


def downgrade() -> None:
    # Remove locked column
    op.drop_column('matchassignment', 'locked')

