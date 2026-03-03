"""Add player identity and SMS consent foundation tables.

Revision ID: 014_add_player_sms_foundation
Revises: 013_add_sms_support
"""

from alembic import op
import sqlalchemy as sa


revision = "014_add_player_sms_foundation"
down_revision = "013_add_sms_support"
branch_labels = None
depends_on = None


def upgrade():
    # -----------------------------------------------------------------------
    # 1) player - tournament-scoped player identity + consent snapshot
    # -----------------------------------------------------------------------
    op.create_table(
        "player",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tournament_id",
            sa.Integer(),
            sa.ForeignKey("tournament.id"),
            nullable=False,
        ),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("phone_e164", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column(
            "sms_consent_status",
            sa.String(),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("sms_consent_source", sa.String(), nullable=True),
        sa.Column("sms_consent_updated_at", sa.DateTime(), nullable=True),
        sa.Column("sms_consented_at", sa.DateTime(), nullable=True),
        sa.Column("sms_opted_out_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_player_tournament_id", "player", ["tournament_id"])
    op.create_index("ix_player_phone_e164", "player", ["phone_e164"])
    op.create_index("ix_player_email", "player", ["email"])
    op.create_index(
        "ix_player_sms_consent_status",
        "player",
        ["sms_consent_status"],
    )
    op.create_index(
        "uq_player_tournament_phone",
        "player",
        ["tournament_id", "phone_e164"],
        unique=True,
    )

    # -----------------------------------------------------------------------
    # 2) team_player - roster mapping from team -> player
    # -----------------------------------------------------------------------
    op.create_table(
        "team_player",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "team_id",
            sa.Integer(),
            sa.ForeignKey("team.id"),
            nullable=False,
        ),
        sa.Column(
            "player_id",
            sa.Integer(),
            sa.ForeignKey("player.id"),
            nullable=False,
        ),
        sa.Column("lineup_slot", sa.Integer(), nullable=True),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column(
            "is_primary_contact",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_team_player_team_id", "team_player", ["team_id"])
    op.create_index("ix_team_player_player_id", "team_player", ["player_id"])
    op.create_index(
        "uq_team_player",
        "team_player",
        ["team_id", "player_id"],
        unique=True,
    )

    # -----------------------------------------------------------------------
    # 3) sms_consent_event - append-only audit log for consent transitions
    # -----------------------------------------------------------------------
    op.create_table(
        "sms_consent_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tournament_id",
            sa.Integer(),
            sa.ForeignKey("tournament.id"),
            nullable=False,
        ),
        sa.Column(
            "player_id",
            sa.Integer(),
            sa.ForeignKey("player.id"),
            nullable=True,
        ),
        sa.Column("phone_number", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column(
            "source",
            sa.String(),
            nullable=False,
            server_default="manual",
        ),
        sa.Column("message_text", sa.String(), nullable=True),
        sa.Column("provider_message_sid", sa.String(), nullable=True),
        sa.Column("dedupe_key", sa.String(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_sms_consent_event_tournament_id",
        "sms_consent_event",
        ["tournament_id"],
    )
    op.create_index(
        "ix_sms_consent_event_player_id",
        "sms_consent_event",
        ["player_id"],
    )
    op.create_index(
        "ix_sms_consent_event_phone_number",
        "sms_consent_event",
        ["phone_number"],
    )
    op.create_index(
        "ix_sms_consent_event_event_type",
        "sms_consent_event",
        ["event_type"],
    )
    op.create_index(
        "ix_sms_consent_event_provider_message_sid",
        "sms_consent_event",
        ["provider_message_sid"],
    )
    op.create_index(
        "ix_sms_consent_event_occurred_at",
        "sms_consent_event",
        ["occurred_at"],
    )
    op.create_index(
        "uq_sms_consent_dedupe",
        "sms_consent_event",
        ["tournament_id", "dedupe_key"],
        unique=True,
    )


def downgrade():
    op.drop_table("sms_consent_event")
    op.drop_table("team_player")
    op.drop_table("player")
