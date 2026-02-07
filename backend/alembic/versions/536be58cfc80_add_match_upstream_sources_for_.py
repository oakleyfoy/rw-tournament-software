"""add match upstream sources for advancement

Revision ID: 536be58cfc80
Revises: 22c54af8c6cd
Create Date: 2026-01-30 20:14:14.094295

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '536be58cfc80'
down_revision = '22c54af8c6cd'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('match', sa.Column('source_match_a_id', sa.Integer(), nullable=True))
    op.add_column('match', sa.Column('source_match_b_id', sa.Integer(), nullable=True))
    op.add_column('match', sa.Column('source_a_role', sa.String(), nullable=True))
    op.add_column('match', sa.Column('source_b_role', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('match', 'source_b_role')
    op.drop_column('match', 'source_a_role')
    op.drop_column('match', 'source_match_b_id')
    op.drop_column('match', 'source_match_a_id')

