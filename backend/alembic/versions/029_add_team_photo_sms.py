"""Photo share links and first-photo SMS notices.

Revision ID: 029_add_team_photo_sms
Revises: 028_add_team_photo_print

Idempotent: startup also creates these tables. Existing official photographs
are not copied, and no historical photo is queued for SMS.
"""

import sqlalchemy as sa

from alembic import op

revision = "029_add_team_photo_sms"
down_revision = "028_add_team_photo_print"
branch_labels = None
depends_on = None


def _create_if_missing(name: str, create) -> None:
    inspector = sa.inspect(op.get_bind())
    if name in inspector.get_table_names():
        return
    create()


def upgrade() -> None:
    def share() -> None:
        op.create_table(
            "team_photo_share",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tournament_id", sa.Integer(), sa.ForeignKey("tournament.id"), nullable=False),
            sa.Column("team_id", sa.Integer(), sa.ForeignKey("team.id"), nullable=False),
            sa.Column("photo_id", sa.Integer(), nullable=False),
            sa.Column("token", sa.String(length=128), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("team_id", name="uq_team_photo_share_team"),
            sa.UniqueConstraint("token", name="uq_team_photo_share_token"),
        )
        op.create_index("ix_team_photo_share_tournament_id", "team_photo_share", ["tournament_id"])
        op.create_index("ix_team_photo_share_team_id", "team_photo_share", ["team_id"])
        op.create_index("ix_team_photo_share_photo_id", "team_photo_share", ["photo_id"])
        op.create_index("ix_team_photo_share_token", "team_photo_share", ["token"])

    def notice() -> None:
        op.create_table(
            "team_photo_sms_notice",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tournament_id", sa.Integer(), sa.ForeignKey("tournament.id"), nullable=False),
            sa.Column("team_id", sa.Integer(), sa.ForeignKey("team.id"), nullable=False),
            sa.Column("photo_id", sa.Integer(), nullable=False),
            sa.Column("player_id", sa.Integer(), sa.ForeignKey("player.id"), nullable=True),
            sa.Column("phone_e164", sa.String(), nullable=True),
            sa.Column("notice_type", sa.String(length=64), nullable=False),
            sa.Column("idempotency_key", sa.String(length=200), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("provider_sid", sa.String(), nullable=True),
            sa.Column("consent_status", sa.String(length=40), nullable=True),
            sa.Column("consent_source", sa.String(length=80), nullable=True),
            sa.Column("failure_code", sa.String(length=80), nullable=True),
            sa.Column("failure_reason", sa.String(length=300), nullable=True),
            sa.Column("retry_count", sa.Integer(), nullable=False),
            sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
            sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("delivered_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("idempotency_key", name="uq_team_photo_sms_idempotency"),
        )
        op.create_index("ix_team_photo_sms_notice_tournament_id", "team_photo_sms_notice", ["tournament_id"])
        op.create_index("ix_team_photo_sms_notice_team_id", "team_photo_sms_notice", ["team_id"])
        op.create_index("ix_team_photo_sms_notice_photo_id", "team_photo_sms_notice", ["photo_id"])
        op.create_index("ix_team_photo_sms_notice_player_id", "team_photo_sms_notice", ["player_id"])
        op.create_index("ix_team_photo_sms_notice_phone_e164", "team_photo_sms_notice", ["phone_e164"])
        op.create_index("ix_team_photo_sms_notice_notice_type", "team_photo_sms_notice", ["notice_type"])
        op.create_index("ix_team_photo_sms_notice_status", "team_photo_sms_notice", ["status"])
        op.create_index("ix_team_photo_sms_notice_provider_sid", "team_photo_sms_notice", ["provider_sid"])
        op.create_index("ix_team_photo_sms_notice_next_attempt_at", "team_photo_sms_notice", ["next_attempt_at"])

    _create_if_missing("team_photo_share", share)
    _create_if_missing("team_photo_sms_notice", notice)


def downgrade() -> None:
    op.drop_table("team_photo_sms_notice")
    op.drop_table("team_photo_share")
