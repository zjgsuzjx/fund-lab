"""simulated purchase orders and position lots"""
from alembic import op
import sqlalchemy as sa

revision = '7328c9b86b16'
down_revision = 'fd20260913'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('buy_orders',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('account_id', sa.Uuid(), nullable=False),
    sa.Column('fund_code', sa.String(length=6), nullable=False),
    sa.Column('request_key', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('amount', sa.Numeric(precision=20, scale=2), nullable=False),
    sa.Column('fee', sa.Numeric(precision=20, scale=2), nullable=False),
    sa.Column('net_amount', sa.Numeric(precision=20, scale=2), nullable=False),
    sa.Column('trade_date', sa.Date(), nullable=False),
    sa.Column('confirmation_date', sa.Date(), nullable=False),
    sa.Column('cancel_until', sa.DateTime(timezone=True), nullable=False),
    sa.Column('rule_snapshot', sa.JSON(), nullable=False),
    sa.Column('confirmed_nav', sa.Numeric(precision=20, scale=8), nullable=True),
    sa.Column('shares', sa.Numeric(precision=20, scale=2), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("(status = 'confirmed' AND confirmed_nav IS NOT NULL AND shares IS NOT NULL AND confirmed_nav > 0 AND shares > 0 AND completed_at IS NOT NULL) OR (status != 'confirmed' AND confirmed_nav IS NULL AND shares IS NULL)", name=op.f('ck_buy_orders_confirmed_values')),
    sa.CheckConstraint("status IN ('pending', 'confirmed', 'cancelled')", name=op.f('ck_buy_orders_valid_status')),
    sa.CheckConstraint('amount > 0 AND fee >= 0 AND net_amount > 0 AND amount = fee + net_amount', name=op.f('ck_buy_orders_valid_amounts')),
    sa.ForeignKeyConstraint(['account_id'], ['simulation_accounts.id'], name=op.f('fk_buy_orders_account_id_simulation_accounts')),
    sa.ForeignKeyConstraint(['fund_code'], ['funds.code'], name=op.f('fk_buy_orders_fund_code_funds')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_buy_orders')),
    sa.UniqueConstraint('account_id', 'request_key', name=op.f('uq_buy_orders_account_id'))
    )
    op.create_index(op.f('ix_buy_orders_account_id'), 'buy_orders', ['account_id'], unique=False)
    op.create_index(op.f('ix_buy_orders_status'), 'buy_orders', ['status'], unique=False)
    op.create_table('position_lots',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('account_id', sa.Uuid(), nullable=False),
    sa.Column('order_id', sa.Uuid(), nullable=False),
    sa.Column('fund_code', sa.String(length=6), nullable=False),
    sa.Column('shares', sa.Numeric(precision=20, scale=2), nullable=False),
    sa.Column('cost', sa.Numeric(precision=20, scale=2), nullable=False),
    sa.Column('confirmation_date', sa.Date(), nullable=False),
    sa.CheckConstraint('shares > 0 AND cost > 0', name=op.f('ck_position_lots_positive_position')),
    sa.ForeignKeyConstraint(['account_id'], ['simulation_accounts.id'], name=op.f('fk_position_lots_account_id_simulation_accounts')),
    sa.ForeignKeyConstraint(['fund_code'], ['funds.code'], name=op.f('fk_position_lots_fund_code_funds')),
    sa.ForeignKeyConstraint(['order_id'], ['buy_orders.id'], name=op.f('fk_position_lots_order_id_buy_orders')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_position_lots')),
    sa.UniqueConstraint('order_id', name=op.f('uq_position_lots_order_id'))
    )
    op.create_index(op.f('ix_position_lots_account_id'), 'position_lots', ['account_id'], unique=False)
    op.add_column('cash_ledger', sa.Column('available_delta', sa.Numeric(precision=20, scale=2), server_default='0', nullable=False))
    op.add_column('cash_ledger', sa.Column('reserved_delta', sa.Numeric(precision=20, scale=2), server_default='0', nullable=False))
    op.add_column('cash_ledger', sa.Column('reserved_after', sa.Numeric(precision=20, scale=2), server_default='0', nullable=False))
    op.add_column('simulation_accounts', sa.Column('reserved_cash', sa.Numeric(precision=20, scale=2), server_default='0', nullable=False))
    op.create_check_constraint('nonnegative_reserved', 'simulation_accounts', 'reserved_cash >= 0')
    op.execute("UPDATE cash_ledger SET available_delta = amount WHERE kind = 'initial_capital'")


def downgrade():
    # Rolling back a used trading schema would destroy the audit trail.
    if op.get_bind().execute(sa.text('SELECT EXISTS (SELECT 1 FROM buy_orders)')).scalar():
        raise RuntimeError('Cannot downgrade with purchase orders; restore a pre-trading backup instead.')
    op.drop_constraint(op.f('ck_simulation_accounts_nonnegative_reserved'), 'simulation_accounts', type_='check')
    op.drop_column('simulation_accounts', 'reserved_cash')
    op.drop_column('cash_ledger', 'reserved_after')
    op.drop_column('cash_ledger', 'reserved_delta')
    op.drop_column('cash_ledger', 'available_delta')
    op.drop_index(op.f('ix_position_lots_account_id'), table_name='position_lots')
    op.drop_table('position_lots')
    op.drop_index(op.f('ix_buy_orders_status'), table_name='buy_orders')
    op.drop_index(op.f('ix_buy_orders_account_id'), table_name='buy_orders')
    op.drop_table('buy_orders')
