"""add_finalization_fields_to_schedule_version

Revision ID: 011_finalization
Revises: 010_wf_grouping
Create Date: 2026-01-10 22:45:00

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "011_finalization"
down_revision = "010_wf_grouping"
branch_labels = None
depends_on = None


def upgrade():
    # Add finalization fields to scheduleversion table
    with op.batch_alter_table("scheduleversion", schema=None) as batch_op:
        batch_op.add_column(sa.Column("finalized_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("finalized_checksum", sa.String(length=64), nullable=True))


def downgrade():
    # Remove finalization fields
    with op.batch_alter_table("scheduleversion", schema=None) as batch_op:
        batch_op.drop_column("finalized_checksum")
        batch_op.drop_column("finalized_at")
