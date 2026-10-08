"""Add openingslotrelease for durable opening WF release authorization.

Revision ID: 024_add_opening_slot_release
Revises: 023_add_sms_delivery_mode_and_redirect
"""

import sqlalchemy as sa

from alembic import op

revision = "024_add_opening_slot_release"
down_revision = "023_add_sms_delivery_mode_and_redirect"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "openingslotrelease",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tournament_id", sa.Integer(), sa.ForeignKey("tournament.id"), nullable=False),
        sa.Column("schedule_version_id", sa.Integer(), sa.ForeignKey("scheduleversion.id"), nullable=False),
        sa.Column("day_date", sa.Date(), nullable=False),
        sa.Column("slot_key", sa.String(length=32), nullable=False),
        sa.Column("released_at", sa.DateTime(), nullable=False),
        sa.Column("released_by", sa.String(length=64), nullable=True),
        sa.UniqueConstraint(
            "schedule_version_id",
            "day_date",
            "slot_key",
            name="uq_opening_slot_release_version_day_slot",
        ),
    )
    op.create_index("ix_openingslotrelease_tournament_id", "openingslotrelease", ["tournament_id"])
    op.create_index(
        "ix_openingslotrelease_schedule_version_id",
        "openingslotrelease",
        ["schedule_version_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_openingslotrelease_schedule_version_id", table_name="openingslotrelease")
    op.drop_index("ix_openingslotrelease_tournament_id", table_name="openingslotrelease")
    op.drop_table("openingslotrelease")
