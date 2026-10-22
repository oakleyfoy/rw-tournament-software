"""Print watermark tables.

Revision ID: 028_add_team_photo_print
Revises: 027_add_match_checkin_reset_pending

Idempotent: startup also creates these tables. Existing official photographs
are not copied or rewritten.
"""

import sqlalchemy as sa

from alembic import op

revision = "028_add_team_photo_print"
down_revision = "027_add_match_checkin_reset_pending"
branch_labels = None
depends_on = None


def _create_if_missing(name: str, create) -> None:
    inspector = sa.inspect(op.get_bind())
    if name in inspector.get_table_names():
        return
    create()


def upgrade() -> None:
    def watermark_default() -> None:
        op.create_table(
            "tournament_photo_watermark",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tournament_id", sa.Integer(), sa.ForeignKey("tournament.id"), nullable=False),
            sa.Column("settings_json", sa.Text(), nullable=False),
            sa.Column("custom_logo_key", sa.String(length=300), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("tournament_id", name="uq_tournament_photo_watermark"),
        )
        op.create_index("ix_tournament_photo_watermark_tournament_id", "tournament_photo_watermark", ["tournament_id"])

    def watermark_photo() -> None:
        op.create_table(
            "team_photo_watermark",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tournament_id", sa.Integer(), sa.ForeignKey("tournament.id"), nullable=False),
            sa.Column("team_id", sa.Integer(), sa.ForeignKey("team.id"), nullable=False),
            sa.Column("settings_json", sa.Text(), nullable=True),
            sa.Column("reviewed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("tournament_id", "team_id", name="uq_team_photo_watermark"),
        )
        op.create_index("ix_team_photo_watermark_tournament_id", "team_photo_watermark", ["tournament_id"])
        op.create_index("ix_team_photo_watermark_team_id", "team_photo_watermark", ["team_id"])

    def print_file() -> None:
        op.create_table(
            "team_photo_print",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tournament_id", sa.Integer(), sa.ForeignKey("tournament.id"), nullable=False),
            sa.Column("team_id", sa.Integer(), sa.ForeignKey("team.id"), nullable=False),
            sa.Column("print_size", sa.String(length=8), nullable=False),
            sa.Column("storage_key", sa.String(length=300), nullable=False),
            sa.Column("filename", sa.String(length=180), nullable=False),
            sa.Column("byte_size", sa.Integer(), nullable=False),
            sa.Column("width", sa.Integer(), nullable=False),
            sa.Column("height", sa.Integer(), nullable=False),
            sa.Column("source_width", sa.Integer(), nullable=False),
            sa.Column("source_height", sa.Integer(), nullable=False),
            sa.Column("low_resolution", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("settings_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("tournament_id", "team_id", "print_size", name="uq_team_photo_print"),
        )
        op.create_index("ix_team_photo_print_tournament_id", "team_photo_print", ["tournament_id"])
        op.create_index("ix_team_photo_print_team_id", "team_photo_print", ["team_id"])

    _create_if_missing("tournament_photo_watermark", watermark_default)
    _create_if_missing("team_photo_watermark", watermark_photo)
    _create_if_missing("team_photo_print", print_file)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    names = set(inspector.get_table_names())
    if "team_photo_print" in names:
        op.drop_index("ix_team_photo_print_team_id", table_name="team_photo_print")
        op.drop_index("ix_team_photo_print_tournament_id", table_name="team_photo_print")
        op.drop_table("team_photo_print")
    if "team_photo_watermark" in names:
        op.drop_index("ix_team_photo_watermark_team_id", table_name="team_photo_watermark")
        op.drop_index("ix_team_photo_watermark_tournament_id", table_name="team_photo_watermark")
        op.drop_table("team_photo_watermark")
    if "tournament_photo_watermark" in names:
        op.drop_index("ix_tournament_photo_watermark_tournament_id", table_name="tournament_photo_watermark")
        op.drop_table("tournament_photo_watermark")
