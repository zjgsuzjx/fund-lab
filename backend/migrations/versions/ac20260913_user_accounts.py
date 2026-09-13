"""Username authentication, revocable sessions, and initial cash ledger."""
from alembic import op
import sqlalchemy as sa

revision = 'ac20260913'
down_revision = '59d9da2013e7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('username', sa.String(64), nullable=True))
    # Preserve foundation-era rows without guessing usernames from email addresses.
    op.execute("UPDATE users SET username = 'legacy_' || replace(id::text, '-', '')")
    op.alter_column('users', 'username', nullable=False)
    op.create_unique_constraint('uq_users_username', 'users', ['username'])
    op.alter_column('users', 'email', nullable=True)
    op.create_table('auth_sessions',
        sa.Column('token_hash', sa.String(64), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index('ix_auth_sessions_user_id', 'auth_sessions', ['user_id'])
    op.create_table('cash_ledger',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('account_id', sa.Uuid(), sa.ForeignKey('simulation_accounts.id'), nullable=False),
        sa.Column('event_key', sa.String(100), unique=True, nullable=False),
        sa.Column('kind', sa.String(30), nullable=False),
        sa.Column('amount', sa.Numeric(20, 2), nullable=False),
        sa.Column('balance_after', sa.Numeric(20, 2), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('amount > 0', name='positive_amount'))
    op.create_index('ix_cash_ledger_account_id', 'cash_ledger', ['account_id'])


def downgrade():
    # New users have no email; refuse a lossy rollback when they exist.
    connection = op.get_bind()
    if connection.scalar(sa.text('SELECT count(*) FROM users WHERE email IS NULL')):
        raise RuntimeError('Cannot downgrade users without email addresses')
    op.drop_table('cash_ledger')
    op.drop_table('auth_sessions')
    op.alter_column('users', 'email', nullable=False)
    op.drop_constraint('uq_users_username', 'users', type_='unique')
    op.drop_column('users', 'username')
