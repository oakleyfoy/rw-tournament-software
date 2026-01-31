"""add match runtime status and scoring

Revision ID: 22c54af8c6cd
Revises: 14c09bfe72f6
Create Date: 2026-01-30 20:05:22.888033

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '22c54af8c6cd'
down_revision = '14c09bfe72f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('match', sa.Column('runtime_status', sa.String(), nullable=False, server_default='SCHEDULED'))
    op.add_column('match', sa.Column('score_json', sa.JSON(), nullable=True))
    op.add_column('match', sa.Column('winner_team_id', sa.Integer(), nullable=True))
    op.add_column('match', sa.Column('started_at', sa.DateTime(), nullable=True))
    op.add_column('match', sa.Column('completed_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('match', 'completed_at')
    op.drop_column('match', 'started_at')
    op.drop_column('match', 'winner_team_id')
    op.drop_column('match', 'score_json')
    op.drop_column('match', 'runtime_status')

