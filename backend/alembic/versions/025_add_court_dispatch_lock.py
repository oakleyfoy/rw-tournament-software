"""Add courtdispatchlock for serialized PREASSIGNED court starts.

Revision ID: 025_add_court_dispatch_lock
Revises: 024_add_opening_slot_release
"""

import sqlalchemy as sa

from alembic import op

revision = "025_add_court_dispatch_lock"
down_revision = "024_add_opening_slot_release"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "courtdispatchlock",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("schedule_version_id", sa.Integer(), sa.ForeignKey("scheduleversion.id"), nullable=False),
        sa.Column("day_date", sa.Date(), nullable=False),
        sa.Column("court_number", sa.Integer(), nullable=False),
        sa.Column("holder", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "schedule_version_id",
            "day_date",
            "court_number",
            name="uq_court_dispatch_lock_version_day_court",
        ),
    )
    op.create_index(
        "ix_courtdispatchlock_schedule_version_id",
        "courtdispatchlock",
        ["schedule_version_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_courtdispatchlock_schedule_version_id", table_name="courtdispatchlock")
    op.drop_table("courtdispatchlock")
