from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, MetaData, Numeric, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention={
        'ix': 'ix_%(column_0_label)s', 'uq': 'uq_%(table_name)s_%(column_0_name)s',
        'ck': 'ck_%(table_name)s_%(constraint_name)s',
        'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s', 'pk': 'pk_%(table_name)s'})


class User(Base):
    __tablename__ = 'users'
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SimulationAccount(Base):
    __tablename__ = 'simulation_accounts'
    __table_args__ = (CheckConstraint('available_cash >= 0', name='nonnegative_cash'),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id'), unique=True)
    available_cash: Mapped[Decimal] = mapped_column(Numeric(20, 2), server_default='0')
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


class FundNav(Base):
    __tablename__ = 'fund_navs'
    __table_args__ = (CheckConstraint('unit_nav > 0', name='positive_nav'),
                      CheckConstraint('cumulative_nav IS NULL OR cumulative_nav > 0', name='positive_cumulative_nav'))
    fund_code: Mapped[str] = mapped_column(ForeignKey('funds.code'), primary_key=True)
    nav_date: Mapped[date] = mapped_column(primary_key=True)
    unit_nav: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    cumulative_nav: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))


class Watchlist(Base):
    __tablename__ = 'watchlists'
    user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id'), primary_key=True)
    fund_code: Mapped[str] = mapped_column(ForeignKey('funds.code'), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
