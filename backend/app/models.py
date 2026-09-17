from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, MetaData, Numeric, String, Integer, JSON, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention={
        'ix': 'ix_%(column_0_label)s', 'uq': 'uq_%(table_name)s_%(column_0_name)s',
        'ck': 'ck_%(table_name)s_%(constraint_name)s',
        'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s', 'pk': 'pk_%(table_name)s'})


class User(Base):
    __tablename__ = 'users'
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SimulationAccount(Base):
    __tablename__ = 'simulation_accounts'
    __table_args__ = (CheckConstraint('available_cash >= 0', name='nonnegative_cash'),
                      CheckConstraint('reserved_cash >= 0', name='nonnegative_reserved'))
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id'), unique=True)
    available_cash: Mapped[Decimal] = mapped_column(Numeric(20, 2), server_default='0')
    reserved_cash: Mapped[Decimal] = mapped_column(Numeric(20, 2), server_default='0')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Fund(Base):
    __tablename__ = 'funds'
    __table_args__ = (CheckConstraint("code ~ '^[0-9]{6}$'", name='six_digit_code'),)
    code: Mapped[str] = mapped_column(String(6), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    category: Mapped[str] = mapped_column(String(60))
    source_url: Mapped[str] = mapped_column(String(500))
    source_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_sample: Mapped[bool] = mapped_column(Boolean, server_default='true')
    trade_enabled: Mapped[bool] = mapped_column(Boolean, server_default='false')
    history_complete: Mapped[bool] = mapped_column(Boolean, server_default='false')
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FundNav(Base):
    __tablename__ = 'fund_navs'
    __table_args__ = (CheckConstraint('unit_nav > 0', name='positive_nav'),
                      CheckConstraint('cumulative_nav IS NULL OR cumulative_nav > 0', name='positive_cumulative_nav'))
    fund_code: Mapped[str] = mapped_column(ForeignKey('funds.code'), primary_key=True)
    nav_date: Mapped[date] = mapped_column(primary_key=True)
    unit_nav: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    cumulative_nav: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    dividend_note: Mapped[str | None] = mapped_column(String(500))


class Watchlist(Base):
    __tablename__ = 'watchlists'
    user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id'), primary_key=True)
    fund_code: Mapped[str] = mapped_column(ForeignKey('funds.code'), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthSession(Base):
    __tablename__ = 'auth_sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id'), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CashLedger(Base):
    __tablename__ = 'cash_ledger'
    __table_args__ = (CheckConstraint('amount > 0', name='positive_amount'),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(ForeignKey('simulation_accounts.id'), index=True)
    event_key: Mapped[str] = mapped_column(String(100), unique=True)
    kind: Mapped[str] = mapped_column(String(30))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    balance_after: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    available_delta: Mapped[Decimal] = mapped_column(Numeric(20, 2), server_default='0')
    reserved_delta: Mapped[Decimal] = mapped_column(Numeric(20, 2), server_default='0')
    reserved_after: Mapped[Decimal] = mapped_column(Numeric(20, 2), server_default='0')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FundRuleEvidence(Base):
    __tablename__ = 'fund_rule_evidence'
    fund_code: Mapped[str] = mapped_column(ForeignKey('funds.code'), primary_key=True)
    source_url: Mapped[str] = mapped_column(String(500))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    subscription_fees: Mapped[list] = mapped_column(JSON)
    redemption_fees: Mapped[list] = mapped_column(JSON)
    ongoing_fees: Mapped[list] = mapped_column(JSON)
    # Observation is not an effective-dated, verified trading contract.
    is_snapshot: Mapped[bool] = mapped_column(Boolean, server_default='true')


class FundSyncRun(Base):
    __tablename__ = 'fund_sync_runs'
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    fund_code: Mapped[str] = mapped_column(ForeignKey('funds.code'), index=True)
    status: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    inserted: Mapped[int] = mapped_column(Integer, default=0)
    unchanged: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(String(500), default='')
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    conflicts: Mapped[list] = mapped_column(JSON, default=list)


class BuyOrder(Base):
    __tablename__ = 'buy_orders'
    __table_args__ = (UniqueConstraint('account_id', 'request_key'),
                      CheckConstraint("status IN ('pending', 'confirmed', 'cancelled')", name='valid_status'),
                      CheckConstraint('amount > 0 AND fee >= 0 AND net_amount > 0 AND amount = fee + net_amount', name='valid_amounts'),
                      CheckConstraint("(status = 'confirmed' AND confirmed_nav IS NOT NULL AND shares IS NOT NULL AND confirmed_nav > 0 AND shares > 0 AND completed_at IS NOT NULL) OR (status != 'confirmed' AND confirmed_nav IS NULL AND shares IS NULL)", name='confirmed_values'))
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(ForeignKey('simulation_accounts.id'), index=True)
    fund_code: Mapped[str] = mapped_column(ForeignKey('funds.code'))
    request_key: Mapped[UUID] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), index=True, default='pending')
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    fee: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    net_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    trade_date: Mapped[date] = mapped_column()
    confirmation_date: Mapped[date] = mapped_column()
    cancel_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rule_snapshot: Mapped[dict] = mapped_column(JSON)
    confirmed_nav: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    shares: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PositionLot(Base):
    __tablename__ = 'position_lots'
    __table_args__ = (CheckConstraint('shares > 0 AND cost > 0', name='positive_position'),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(ForeignKey('simulation_accounts.id'), index=True)
    order_id: Mapped[UUID] = mapped_column(ForeignKey('buy_orders.id'), unique=True)
    fund_code: Mapped[str] = mapped_column(ForeignKey('funds.code'))
    shares: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    cost: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    confirmation_date: Mapped[date] = mapped_column()
