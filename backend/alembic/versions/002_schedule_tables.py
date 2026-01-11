"""Add schedule tables: schedule_versions, schedule_slots, matches, match_assignments

Revision ID: 002_schedule
Revises: 001_initial
Create Date: 2024-01-02 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "002_schedule"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create schedule_versions table
    op.create_table(
        "scheduleversion",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.id"]),
    )

    # Create schedule_slots table
    op.create_table(
        "scheduleslot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("schedule_version_id", sa.Integer(), nullable=False),
        sa.Column("day_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("court_number", sa.Integer(), nullable=False),
        sa.Column("block_minutes", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.id"]),
        sa.ForeignKeyConstraint(["schedule_version_id"], ["scheduleversion.id"]),
        sa.UniqueConstraint(
            "schedule_version_id", "day_date", "start_time", "court_number", name="uq_slot_version_day_time_court"
        ),
    )

    # Create indexes for schedule_slots
    op.create_index("ix_scheduleslot_tournament_version", "scheduleslot", ["tournament_id", "schedule_version_id"])
    op.create_index("ix_scheduleslot_day_time", "scheduleslot", ["day_date", "start_time"])

    # Create matches table
    op.create_table(
        "match",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("schedule_version_id", sa.Integer(), nullable=False),
        sa.Column("match_code", sa.String(), nullable=False),
        sa.Column("match_type", sa.String(), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("sequence_in_round", sa.Integer(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("placeholder_side_a", sa.String(), nullable=False),
        sa.Column("placeholder_side_b", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="unscheduled"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.id"]),
        sa.ForeignKeyConstraint(["event_id"], ["event.id"]),
        sa.ForeignKeyConstraint(["schedule_version_id"], ["scheduleversion.id"]),
        sa.UniqueConstraint("schedule_version_id", "match_code", name="uq_match_version_code"),
    )

    # Create indexes for matches
    op.create_index("ix_match_event_version", "match", ["event_id", "schedule_version_id"])
    op.create_index("ix_match_status", "match", ["status"])

    # Create match_assignments table
    op.create_table(
        "matchassignment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("schedule_version_id", sa.Integer(), nullable=False),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("slot_id", sa.Integer(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(), nullable=False),
        sa.Column("assigned_by", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["schedule_version_id"], ["scheduleversion.id"]),
        sa.ForeignKeyConstraint(["match_id"], ["match.id"]),
        sa.ForeignKeyConstraint(["slot_id"], ["scheduleslot.id"]),
        sa.UniqueConstraint("schedule_version_id", "slot_id", name="uq_assignment_version_slot"),
        sa.UniqueConstraint("schedule_version_id", "match_id", name="uq_assignment_version_match"),
    )


def downgrade() -> None:
    op.drop_table("matchassignment")
    op.drop_index("ix_match_status", table_name="match")
    op.drop_index("ix_match_event_version", table_name="match")
    op.drop_table("match")
    op.drop_index("ix_scheduleslot_day_time", table_name="scheduleslot")
    op.drop_index("ix_scheduleslot_tournament_version", table_name="scheduleslot")
    op.drop_table("scheduleslot")
    op.drop_table("scheduleversion")
