"""Add SMS support: phone/email fields on team + sms_log, sms_template, tournament_sms_settings tables.

Revision ID: 013_add_sms_support
Revises: 012_public_version
"""

from alembic import op
import sqlalchemy as sa


revision = "013_add_sms_support"
down_revision = "012_public_version"
branch_labels = None
depends_on = None


def upgrade():
    # -----------------------------------------------------------------------
    # 1. Add phone/email columns to existing 'team' table
    #    These match the WAR Tournaments fields: P1 Cell, P1 Email, P2 Cell, P2 Email
    # -----------------------------------------------------------------------
    op.add_column("team", sa.Column("p1_cell", sa.String(), nullable=True))
    op.add_column("team", sa.Column("p1_email", sa.String(), nullable=True))
    op.add_column("team", sa.Column("p2_cell", sa.String(), nullable=True))
    op.add_column("team", sa.Column("p2_email", sa.String(), nullable=True))

    # -----------------------------------------------------------------------
    # 2. sms_log - record of every SMS sent
    # -----------------------------------------------------------------------
    op.create_table(
        "sms_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tournament_id",
            sa.Integer(),
            sa.ForeignKey("tournament.id"),
            nullable=False,
        ),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("team.id"), nullable=True),
        sa.Column("phone_number", sa.String(), nullable=False),
        sa.Column("message_body", sa.String(), nullable=False),
        sa.Column("message_type", sa.String(), nullable=False),
        sa.Column("twilio_sid", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("trigger", sa.String(), nullable=False, server_default="manual"),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sms_log_tournament_id", "sms_log", ["tournament_id"])

    # -----------------------------------------------------------------------
    # 3. sms_template - customizable message templates per tournament
    # -----------------------------------------------------------------------
    op.create_table(
        "sms_template",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tournament_id",
            sa.Integer(),
            sa.ForeignKey("tournament.id"),
            nullable=False,
        ),
        sa.Column("message_type", sa.String(), nullable=False),
        sa.Column("template_body", sa.String(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sms_template_tournament_id", "sms_template", ["tournament_id"])
    op.create_index(
        "uq_tournament_message_type",
        "sms_template",
        ["tournament_id", "message_type"],
        unique=True,
    )

    # -----------------------------------------------------------------------
    # 4. tournament_sms_settings - per-tournament auto-text toggles
    # -----------------------------------------------------------------------
    op.create_table(
        "tournament_sms_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tournament_id",
            sa.Integer(),
            sa.ForeignKey("tournament.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "auto_first_match",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "auto_post_match_next",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "auto_on_deck",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "auto_up_next",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "auto_court_change",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_tournament_sms_settings_tournament_id",
        "tournament_sms_settings",
        ["tournament_id"],
    )


def downgrade():
    op.drop_table("tournament_sms_settings")
    op.drop_table("sms_template")
    op.drop_table("sms_log")

    # Remove phone/email columns from team
    op.drop_column("team", "p2_email")
    op.drop_column("team", "p2_cell")
    op.drop_column("team", "p1_email")
    op.drop_column("team", "p1_cell")
