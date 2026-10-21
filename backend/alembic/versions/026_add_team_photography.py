"""Add official team photographs and photographer tournament access.

Revision ID: 026_add_team_photography
Revises: 025_add_court_dispatch_lock
"""

import sqlalchemy as sa

from alembic import op

revision = "026_add_team_photography"
down_revision = "025_add_court_dispatch_lock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "team_official_photo",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("team.id"), nullable=False),
        sa.Column("tournament_id", sa.Integer(), sa.ForeignKey("tournament.id"), nullable=False),
        sa.Column("storage_key", sa.String(length=300), nullable=False),
        sa.Column("content_type", sa.String(length=40), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("photographer_user_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("last_client_upload_id", sa.String(length=80), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("team_id", name="uq_team_official_photo_team"),
    )
    op.create_index("ix_team_official_photo_team_id", "team_official_photo", ["team_id"])
    op.create_index("ix_team_official_photo_tournament_id", "team_official_photo", ["tournament_id"])
    op.create_index("ix_team_official_photo_last_client_upload_id", "team_official_photo", ["last_client_upload_id"])

    op.create_table(
        "team_photo_capture",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("team.id"), nullable=False),
        sa.Column("tournament_id", sa.Integer(), sa.ForeignKey("tournament.id"), nullable=False),
        sa.Column("session_id", sa.String(length=80), nullable=False),
        sa.Column("client_upload_id", sa.String(length=80), nullable=False),
        sa.Column("storage_key", sa.String(length=300), nullable=False),
        sa.Column("content_type", sa.String(length=40), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("photographer_user_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("client_upload_id", name="uq_team_photo_capture_client_upload"),
    )
    op.create_index("ix_team_photo_capture_team_id", "team_photo_capture", ["team_id"])
    op.create_index("ix_team_photo_capture_tournament_id", "team_photo_capture", ["tournament_id"])
    op.create_index("ix_team_photo_capture_session_id", "team_photo_capture", ["session_id"])

    op.create_table(
        "photographer_tournament_access",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=False),
        sa.Column("tournament_id", sa.Integer(), sa.ForeignKey("tournament.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "tournament_id", name="uq_photographer_tournament_access"),
    )
    op.create_index("ix_photographer_tournament_access_user_id", "photographer_tournament_access", ["user_id"])
    op.create_index(
        "ix_photographer_tournament_access_tournament_id",
        "photographer_tournament_access",
        ["tournament_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_photographer_tournament_access_tournament_id", table_name="photographer_tournament_access")
    op.drop_index("ix_photographer_tournament_access_user_id", table_name="photographer_tournament_access")
    op.drop_table("photographer_tournament_access")
    op.drop_index("ix_team_photo_capture_session_id", table_name="team_photo_capture")
    op.drop_index("ix_team_photo_capture_tournament_id", table_name="team_photo_capture")
    op.drop_index("ix_team_photo_capture_team_id", table_name="team_photo_capture")
    op.drop_table("team_photo_capture")
    op.drop_index("ix_team_official_photo_last_client_upload_id", table_name="team_official_photo")
    op.drop_index("ix_team_official_photo_tournament_id", table_name="team_official_photo")
    op.drop_index("ix_team_official_photo_team_id", table_name="team_official_photo")
    op.drop_table("team_official_photo")
