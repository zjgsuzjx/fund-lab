"""redemption orders frozen lots and receivables"""
from alembic import op
import sqlalchemy as sa

revision = 'd8be352ddbad'
down_revision = '7328c9b86b16'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('sell_orders',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('account_id', sa.Uuid(), nullable=False),
    sa.Column('fund_code', sa.String(length=6), nullable=False),
    sa.Column('request_key', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('shares', sa.Numeric(precision=20, scale=2), nullable=False),
    sa.Column('trade_date', sa.Date(), nullable=False),
    sa.Column('confirmation_date', sa.Date(), nullable=False),
    sa.Column('arrival_date', sa.Date(), nullable=False),
    sa.Column('cancel_until', sa.DateTime(timezone=True), nullable=False),
    sa.Column('rule_snapshot', sa.JSON(), nullable=False),
    sa.Column('quote_snapshot', sa.JSON(), nullable=False),
    sa.Column('confirmed_nav', sa.Numeric(precision=20, scale=8), nullable=True),
    sa.Column('gross_amount', sa.Numeric(precision=20, scale=2), nullable=True),
    sa.Column('fee', sa.Numeric(precision=20, scale=2), nullable=True),
    sa.Column('net_amount', sa.Numeric(precision=20, scale=2), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("(status = 'paid' AND paid_at IS NOT NULL) OR (status != 'paid' AND paid_at IS NULL)", name=op.f('ck_sell_orders_valid_payment')),
    sa.CheckConstraint("(status IN ('confirmed', 'paid') AND confirmed_nav IS NOT NULL AND confirmed_nav > 0 AND gross_amount IS NOT NULL AND fee IS NOT NULL AND net_amount IS NOT NULL AND gross_amount >= 0 AND fee >= 0 AND net_amount >= 0 AND gross_amount = fee + net_amount AND confirmed_at IS NOT NULL) OR (status IN ('pending', 'cancelled') AND confirmed_nav IS NULL AND gross_amount IS NULL AND fee IS NULL AND net_amount IS NULL AND confirmed_at IS NULL)", name=op.f('ck_sell_orders_valid_confirmation')),
    sa.CheckConstraint("status IN ('pending', 'confirmed', 'paid', 'cancelled')", name=op.f('ck_sell_orders_valid_status')),
    sa.CheckConstraint('shares > 0', name=op.f('ck_sell_orders_positive_shares')),
    sa.ForeignKeyConstraint(['account_id'], ['simulation_accounts.id'], name=op.f('fk_sell_orders_account_id_simulation_accounts')),
    sa.ForeignKeyConstraint(['fund_code'], ['funds.code'], name=op.f('fk_sell_orders_fund_code_funds')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sell_orders')),
    sa.UniqueConstraint('account_id', 'request_key', name=op.f('uq_sell_orders_account_id'))
    )
    op.create_index(op.f('ix_sell_orders_account_id'), 'sell_orders', ['account_id'], unique=False)
    op.create_index(op.f('ix_sell_orders_status'), 'sell_orders', ['status'], unique=False)
    op.create_table('sell_allocations',
    sa.Column('order_id', sa.Uuid(), nullable=False),
    sa.Column('lot_id', sa.Uuid(), nullable=False),
    sa.Column('shares', sa.Numeric(precision=20, scale=2), nullable=False),
    sa.Column('holding_days', sa.Integer(), nullable=False),
    sa.Column('fee_rate', sa.Numeric(precision=10, scale=6), nullable=False),
    sa.Column('cost', sa.Numeric(precision=20, scale=2), nullable=True),
    sa.Column('gross_amount', sa.Numeric(precision=20, scale=2), nullable=True),
    sa.Column('fee', sa.Numeric(precision=20, scale=2), nullable=True),
    sa.Column('net_amount', sa.Numeric(precision=20, scale=2), nullable=True),
    sa.CheckConstraint('shares > 0 AND holding_days >= 0 AND fee_rate >= 0', name=op.f('ck_sell_allocations_valid_allocation')),
    sa.ForeignKeyConstraint(['lot_id'], ['position_lots.id'], name=op.f('fk_sell_allocations_lot_id_position_lots')),
    sa.ForeignKeyConstraint(['order_id'], ['sell_orders.id'], name=op.f('fk_sell_allocations_order_id_sell_orders')),
    sa.PrimaryKeyConstraint('order_id', 'lot_id', name=op.f('pk_sell_allocations'))
    )
    op.add_column('cash_ledger', sa.Column('redemption_delta', sa.Numeric(precision=20, scale=2), server_default='0', nullable=False))
    op.add_column('cash_ledger', sa.Column('redemption_after', sa.Numeric(precision=20, scale=2), server_default='0', nullable=False))
    op.add_column('position_lots', sa.Column('remaining_shares', sa.Numeric(precision=20, scale=2), nullable=True))
    op.add_column('position_lots', sa.Column('remaining_cost', sa.Numeric(precision=20, scale=2), nullable=True))
    op.execute('UPDATE position_lots SET remaining_shares = shares, remaining_cost = cost')
    op.alter_column('position_lots', 'remaining_shares', nullable=False)
    op.alter_column('position_lots', 'remaining_cost', nullable=False)
    op.add_column('position_lots', sa.Column('frozen_shares', sa.Numeric(precision=20, scale=2), server_default='0', nullable=False))
    op.add_column('simulation_accounts', sa.Column('redemption_cash', sa.Numeric(precision=20, scale=2), server_default='0', nullable=False))
    op.create_check_constraint('nonnegative_redemption', 'simulation_accounts', 'redemption_cash >= 0')
    op.create_check_constraint('valid_remaining_shares', 'position_lots', 'remaining_shares >= 0 AND remaining_shares <= shares AND frozen_shares >= 0 AND frozen_shares <= remaining_shares')
    op.create_check_constraint('valid_remaining_cost', 'position_lots', 'remaining_cost >= 0 AND remaining_cost <= cost AND (remaining_shares > 0 OR remaining_cost = 0)')
    op.drop_constraint(op.f('ck_cash_ledger_positive_amount'), 'cash_ledger', type_='check')
    op.create_check_constraint('nonnegative_amount', 'cash_ledger', 'amount >= 0')


def downgrade():
    if op.get_bind().execute(sa.text('SELECT EXISTS (SELECT 1 FROM sell_orders)')).scalar():
        raise RuntimeError('Cannot downgrade with redemption orders; preserve the audit trail.')
    op.drop_constraint(op.f('ck_cash_ledger_nonnegative_amount'), 'cash_ledger', type_='check')
    op.create_check_constraint('positive_amount', 'cash_ledger', 'amount > 0')
    op.drop_constraint(op.f('ck_simulation_accounts_nonnegative_redemption'), 'simulation_accounts', type_='check')
    op.drop_constraint(op.f('ck_position_lots_valid_remaining_shares'), 'position_lots', type_='check')
    op.drop_constraint(op.f('ck_position_lots_valid_remaining_cost'), 'position_lots', type_='check')
    op.drop_column('simulation_accounts', 'redemption_cash')
    op.drop_column('position_lots', 'frozen_shares')
    op.drop_column('position_lots', 'remaining_cost')
    op.drop_column('position_lots', 'remaining_shares')
    op.drop_column('cash_ledger', 'redemption_after')
    op.drop_column('cash_ledger', 'redemption_delta')
    op.drop_table('sell_allocations')
    op.drop_index(op.f('ix_sell_orders_status'), table_name='sell_orders')
    op.drop_index(op.f('ix_sell_orders_account_id'), table_name='sell_orders')
    op.drop_table('sell_orders')
