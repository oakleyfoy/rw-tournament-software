"""Add the match-specific check-in reset hold.

Revision ID: 027_add_match_checkin_reset_pending
Revises: 026_add_team_photography

Idempotent: production startup also adds this column, and a database that
already has it must not be rewritten.
"""

import sqlalchemy as sa

from alembic import op

revision = "027_add_match_checkin_reset_pending"
down_revision = "026_add_team_photography"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "match" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("match")}
    if "checkin_reset_pending" in columns:
        return
    op.add_column(
        "match",
        sa.Column(
            "checkin_reset_pending",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "match" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("match")}
    if "checkin_reset_pending" not in columns:
        return
    op.drop_column("match", "checkin_reset_pending")
