"""Store expected final field forecasts on RW-OS imports.

Revision ID: 020_add_import_forecast_json
Revises: 019_add_rw_os_import_tables
Create Date: 2026-08-23
"""

import sqlalchemy as sa

from alembic import op

revision = "020_add_import_forecast_json"
down_revision = "019_add_rw_os_import_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tournament_import", sa.Column("forecast_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tournament_import", "forecast_json")
