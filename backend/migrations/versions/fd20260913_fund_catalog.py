"""Fund history provenance, rule evidence and synchronization audit."""
from alembic import op
import sqlalchemy as sa

revision = 'fd20260913'
down_revision = 'ac20260913'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('funds', sa.Column('history_complete', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('funds', sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('fund_navs', sa.Column('dividend_note', sa.String(500), nullable=True))
    op.create_table('fund_rule_evidence',
        sa.Column('fund_code', sa.String(6), sa.ForeignKey('funds.code'), primary_key=True),
        sa.Column('source_url', sa.String(500), nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('subscription_fees', sa.JSON(), nullable=False),
        sa.Column('redemption_fees', sa.JSON(), nullable=False),
        sa.Column('ongoing_fees', sa.JSON(), nullable=False),
        sa.Column('is_snapshot', sa.Boolean(), nullable=False, server_default='true'))
    op.create_table('fund_sync_runs',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('fund_code', sa.String(6), sa.ForeignKey('funds.code'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('inserted', sa.Integer(), nullable=False),
        sa.Column('unchanged', sa.Integer(), nullable=False),
        sa.Column('message', sa.String(500), nullable=False),
        sa.Column('evidence', sa.JSON(), nullable=False),
        sa.Column('conflicts', sa.JSON(), nullable=False))
    op.create_index('ix_fund_sync_runs_fund_code', 'fund_sync_runs', ['fund_code'])


def downgrade():
    op.drop_table('fund_sync_runs')
    op.drop_table('fund_rule_evidence')
    op.drop_column('fund_navs', 'dividend_note')
    op.drop_column('funds', 'last_sync_at')
    op.drop_column('funds', 'history_complete')
