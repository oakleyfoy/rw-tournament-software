"""Group photographs for the print center.

Revision ID: 030_add_tournament_group_photo
Revises: 029_add_team_photo_sms

Idempotent: startup also creates these tables. Existing team photographs,
players, and SMS rows are not changed.
"""

import sqlalchemy as sa

from alembic import op

revision = "030_add_tournament_group_photo"
down_revision = "029_add_team_photo_sms"
branch_labels = None
depends_on = None


def _create_if_missing(name: str, create) -> None:
    inspector = sa.inspect(op.get_bind())
    if name in inspector.get_table_names():
        return
    create()


def upgrade() -> None:
    def photo() -> None:
        op.create_table(
            "tournament_group_photo",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tournament_id", sa.Integer(), sa.ForeignKey("tournament.id"), nullable=False),
            sa.Column("storage_key", sa.String(length=300), nullable=False),
            sa.Column("content_type", sa.String(length=40), nullable=False),
            sa.Column("byte_size", sa.Integer(), nullable=False),
            sa.Column("photographer_user_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
            sa.Column("client_upload_id", sa.String(length=80), nullable=False),
            sa.Column("captured_at", sa.DateTime(), nullable=False),
            sa.Column("settings_json", sa.Text(), nullable=True),
            sa.Column("reviewed", sa.Boolean(), nullable=False),
            sa.UniqueConstraint("client_upload_id", name="uq_tournament_group_photo_upload"),
        )
        op.create_index("ix_tournament_group_photo_tournament_id", "tournament_group_photo", ["tournament_id"])
        op.create_index("ix_tournament_group_photo_client_upload_id", "tournament_group_photo", ["client_upload_id"])

    def printed() -> None:
        op.create_table(
            "tournament_group_photo_print",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tournament_id", sa.Integer(), sa.ForeignKey("tournament.id"), nullable=False),
            sa.Column("group_photo_id", sa.Integer(), sa.ForeignKey("tournament_group_photo.id"), nullable=False),
            sa.Column("print_size", sa.String(length=8), nullable=False),
            sa.Column("storage_key", sa.String(length=300), nullable=False),
            sa.Column("filename", sa.String(length=180), nullable=False),
            sa.Column("byte_size", sa.Integer(), nullable=False),
            sa.Column("width", sa.Integer(), nullable=False),
            sa.Column("height", sa.Integer(), nullable=False),
            sa.Column("source_width", sa.Integer(), nullable=False),
            sa.Column("source_height", sa.Integer(), nullable=False),
            sa.Column("low_resolution", sa.Boolean(), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False),
            sa.Column("settings_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("group_photo_id", "print_size", name="uq_tournament_group_photo_print"),
        )
        op.create_index(
            "ix_tournament_group_photo_print_tournament_id",
            "tournament_group_photo_print",
            ["tournament_id"],
        )
        op.create_index(
            "ix_tournament_group_photo_print_group_photo_id",
            "tournament_group_photo_print",
            ["group_photo_id"],
        )

    _create_if_missing("tournament_group_photo", photo)
    _create_if_missing("tournament_group_photo_print", printed)


def downgrade() -> None:
    op.drop_table("tournament_group_photo_print")
    op.drop_table("tournament_group_photo")
