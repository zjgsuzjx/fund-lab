"""Durable catalog and calendar sync status."""
from alembic import op
import sqlalchemy as sa

revision = 'mf20260920'
down_revision = 'bac0bcf6b651'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('market_sync_states',
        sa.Column('key', sa.String(30), primary_key=True),
        sa.Column('attempted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('succeeded_at', sa.DateTime(timezone=True)),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('message', sa.String(500), nullable=False))


def downgrade():
    op.drop_table('market_sync_states')
