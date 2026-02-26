"""add public_schedule_version_id to tournament

Revision ID: 012_public_version
Revises: 536be58cfc80
Create Date: 2026-02-24 12:00:00

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "012_public_version"
down_revision = "536be58cfc80"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("tournament", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("public_schedule_version_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_tournament_public_version",
            "scheduleversion",
            ["public_schedule_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_tournament_public_schedule_version_id",
            ["public_schedule_version_id"],
        )


def downgrade():
    with op.batch_alter_table("tournament", schema=None) as batch_op:
        batch_op.drop_index("ix_tournament_public_schedule_version_id")
        batch_op.drop_constraint("fk_tournament_public_version", type_="foreignkey")
        batch_op.drop_column("public_schedule_version_id")
