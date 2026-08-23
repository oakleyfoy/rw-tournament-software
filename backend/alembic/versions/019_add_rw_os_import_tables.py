"""Add RW-OS import snapshot and approved draw plan tables.

Revision ID: 019_add_rw_os_import_tables
Revises: 018_add_tournament_archive_flag
Create Date: 2026-08-23
"""

import sqlalchemy as sa

from alembic import op

revision = "019_add_rw_os_import_tables"
down_revision = "018_add_tournament_archive_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tournament", sa.Column("source_rw_os_tournament_id", sa.Integer(), nullable=True))
    op.add_column("tournament", sa.Column("source_rw_os_organization_slug", sa.String(), nullable=True))
    op.create_index(
        "ix_tournament_source_rw_os_tournament_id",
        "tournament",
        ["source_rw_os_tournament_id"],
    )

    op.create_table(
        "tournament_import",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tournament_id", sa.Integer(), sa.ForeignKey("tournament.id"), nullable=False),
        sa.Column("organization_slug", sa.String(), nullable=False),
        sa.Column("source_tournament_id", sa.Integer(), nullable=False),
        sa.Column("event_name", sa.String(), nullable=False),
        sa.Column("event_date", sa.String(), nullable=False),
        sa.Column("imported_at", sa.DateTime(), nullable=False),
        sa.Column("source_updated_at", sa.String(), nullable=True),
        sa.Column("source_version", sa.String(), nullable=True),
        sa.Column("source_team_count", sa.Integer(), nullable=False),
        sa.Column("source_hash", sa.String(), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("waitlist_json", sa.Text(), nullable=False),
        sa.Column("validation_status", sa.String(), nullable=False),
        sa.Column("validation_issues_json", sa.Text(), nullable=False),
        sa.Column("refresh_diff_json", sa.Text(), nullable=True),
        sa.Column("plan_status", sa.String(), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_tournament_import_tournament_id", "tournament_import", ["tournament_id"])
    op.create_index("ix_tournament_import_source_tournament_id", "tournament_import", ["source_tournament_id"])

    op.create_table(
        "tournament_draw_plan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("tournament_import.id"), nullable=False),
        sa.Column("tournament_id", sa.Integer(), sa.ForeignKey("tournament.id"), nullable=False),
        sa.Column("draw_kind", sa.String(), nullable=False),
        sa.Column("draw_label", sa.String(), nullable=False),
        sa.Column("team_count", sa.Integer(), nullable=False),
        sa.Column("option_key", sa.String(), nullable=False),
        sa.Column("is_recommended", sa.Boolean(), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("option_json", sa.Text(), nullable=False),
        sa.Column("brackets_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_tournament_draw_plan_import_id", "tournament_draw_plan", ["import_id"])
    op.create_index("ix_tournament_draw_plan_tournament_id", "tournament_draw_plan", ["tournament_id"])


def downgrade() -> None:
    op.drop_index("ix_tournament_draw_plan_tournament_id", table_name="tournament_draw_plan")
    op.drop_index("ix_tournament_draw_plan_import_id", table_name="tournament_draw_plan")
    op.drop_table("tournament_draw_plan")
    op.drop_index("ix_tournament_import_source_tournament_id", table_name="tournament_import")
    op.drop_index("ix_tournament_import_tournament_id", table_name="tournament_import")
    op.drop_table("tournament_import")
    op.drop_index("ix_tournament_source_rw_os_tournament_id", table_name="tournament")
    op.drop_column("tournament", "source_rw_os_organization_slug")
    op.drop_column("tournament", "source_rw_os_tournament_id")
