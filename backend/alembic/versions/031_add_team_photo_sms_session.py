"""Photo-session id for a text after an explicit photo delete.

Revision ID: 031_add_team_photo_sms_session
Revises: 030_add_tournament_group_photo

Additive only. Existing share links, notice status, provider ids, and
delivery timestamps are left as they are. Missing columns default to
session 1, the session those rows already belong to.
"""

import sqlalchemy as sa

from alembic import op

revision = "031_add_team_photo_sms_session"
down_revision = "030_add_tournament_group_photo"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str] | None:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return None
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    share = _columns("team_photo_share")
    if share is not None and "generation" not in share:
        op.add_column(
            "team_photo_share",
            sa.Column("generation", sa.Integer(), nullable=False, server_default="1"),
        )
    notice = _columns("team_photo_sms_notice")
    if notice is not None and "photo_session_id" not in notice:
        op.add_column(
            "team_photo_sms_notice",
            sa.Column("photo_session_id", sa.Integer(), nullable=False, server_default="1"),
        )
        op.create_index(
            "ix_team_photo_sms_notice_photo_session_id",
            "team_photo_sms_notice",
            ["photo_session_id"],
        )


def downgrade() -> None:
    notice = _columns("team_photo_sms_notice")
    if notice is not None and "photo_session_id" in notice:
        op.drop_index("ix_team_photo_sms_notice_photo_session_id", table_name="team_photo_sms_notice")
        op.drop_column("team_photo_sms_notice", "photo_session_id")
    share = _columns("team_photo_share")
    if share is not None and "generation" in share:
        op.drop_column("team_photo_share", "generation")
