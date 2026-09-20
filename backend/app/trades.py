"""Session-owned simulated purchases. Account lock is always acquired first."""
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, Callable
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text, literal, union_all
from sqlalchemy.orm import Session

from .auth import CurrentUser, DB, owned_account, write_guard
from .models import BuyOrder, CashLedger, Fund, FundNav, FundSyncRun, PositionLot, SimulationAccount, SellOrder, SellAllocation
from .trade_rules import CN, RULE, disabled_reason, fees, rounded, rule_snapshot, schedule, utcnow

router = APIRouter(prefix='/api')
Clock = Annotated[datetime, Depends(utcnow)]


def clock_provider():
    return utcnow


ClockFunction = Annotated[Callable[[], datetime], Depends(clock_provider)]


class QuoteInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    fund_code: str = Field(pattern=r'^[0-9]{6}$')
    amount: Decimal = Field(gt=0, le=100000000, decimal_places=2, allow_inf_nan=False)


class BuyInput(QuoteInput):
    request_key: UUID
    rule_version: str = Field(max_length=100)
    trade_date: date


def lock_account(db, account_id):
    # Refresh even if auth/another read put this row in this Session's identity map.
    return db.scalar(select(SimulationAccount).where(SimulationAccount.id == account_id)
                     .with_for_update().execution_options(populate_existing=True))


def lock_fund(db, code):
    # Same advisory key as the synchronizer: no settlement against a half-applied sync.
    db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': 81000000 + int(code)})


def ensure_tradable(db, code, now):
    fund = db.get(Fund, code, populate_existing=True)
    reason = disabled_reason(fund, now)
    if reason:
        raise HTTPException(409, reason)
    latest = db.scalar(select(FundSyncRun).where(FundSyncRun.fund_code == code).order_by(FundSyncRun.started_at.desc()).limit(1))
    if latest and latest.status in ('conflict', 'failed'):
        raise HTTPException(409, '最近数据同步异常，请核验并重新同步后再买入。')
    return fund


def quote_values(db, body, account, now):
    fund = ensure_tradable(db, body.fund_code, now)
    if body.amount < Decimal(RULE['minimum']):
        raise HTTPException(422, f"本模拟方案 {RULE['minimum']} 元起购。")
    if body.amount > account.available_cash:
        raise HTTPException(409, '可用模拟余额不足，请调整买入金额。')
    trade_date, confirmation_date, cancel_until = schedule(now)
    fee, net, tier = fees(body.amount)
    return {'fund_code': fund.code, 'fund_name': fund.name, 'amount': str(rounded(body.amount)),
            'fee': str(fee), 'net_amount': str(net), 'fee_label': f"{Decimal(tier['rate']) * 100:.2f}%" if 'rate' in tier else f"{tier['fixed']} 元/笔",
            'trade_date': trade_date, 'confirmation_date': confirmation_date, 'cancel_until': cancel_until,
            'available_cash': str(account.available_cash), 'rule_version': RULE['version'], 'rule': rule_snapshot()}


def add_ledger(db, account, order, kind, available_delta, reserved_delta, now):
    account.available_cash += available_delta
    account.reserved_cash += reserved_delta
    db.add(CashLedger(account_id=account.id, event_key=f'{kind}:{order.id}', kind=kind,
                      amount=order.amount, balance_after=account.available_cash,
                      available_delta=available_delta, reserved_delta=reserved_delta,
                      reserved_after=account.reserved_cash, redemption_after=account.redemption_cash,
                      created_at=now))


def create_buy(db, account_id, body, clock=utcnow):
    account = lock_account(db, account_id)
    existing = db.scalar(select(BuyOrder).where(BuyOrder.account_id == account.id, BuyOrder.request_key == body.request_key))
    if existing:
        # Replays remain readable after cutoff/rule updates/insufficient remaining cash.
        if existing.fund_code != body.fund_code or existing.amount != body.amount:
            raise HTTPException(409, '同一请求编号不能用于不同买入，请先查看原交易记录。')
        return existing
    lock_fund(db, body.fund_code)
    now = clock()  # After locks, so waiting across 15:00 cannot get the earlier date.
    values = quote_values(db, body, account, now)
    if body.rule_version != RULE['version'] or body.trade_date != values['trade_date']:
        raise HTTPException(409, '交易日期或规则已变化，请重新试算后确认。')
    order = BuyOrder(account_id=account.id, fund_code=body.fund_code, request_key=body.request_key,
                     amount=body.amount, fee=Decimal(values['fee']), net_amount=Decimal(values['net_amount']),
                     trade_date=values['trade_date'], confirmation_date=values['confirmation_date'],
                     cancel_until=values['cancel_until'], rule_snapshot=values['rule'], created_at=now)
    db.add(order)
    db.flush()
    add_ledger(db, account, order, 'buy_reserved', -order.amount, order.amount, now)
    db.flush()
    return order


def owned_order(db, account_id, order_id):
    order = db.scalar(select(BuyOrder).where(BuyOrder.id == order_id, BuyOrder.account_id == account_id)
                       .execution_options(populate_existing=True))
    if not order:
        raise HTTPException(404, '未找到这笔模拟订单。')
    return order


def cancel_buy(db, account_id, order_id, clock=utcnow):
    account = lock_account(db, account_id)
    order = owned_order(db, account.id, order_id)
    if order.status == 'cancelled':
        return order
    now = clock()
    if order.status != 'pending' or now >= order.cancel_until:
        raise HTTPException(409, '订单已完成或已超过可撤单截止时间。')
    order.status, order.completed_at = 'cancelled', now
    add_ledger(db, account, order, 'buy_cancelled', order.amount, -order.amount, now)
    db.flush()
    return order


def settle_buy(db, account_id, order_id, clock=utcnow):
    account = lock_account(db, account_id)
    order = owned_order(db, account.id, order_id)
    now = clock()
    if order.status != 'pending' or now.astimezone(CN).date() < order.confirmation_date:
        return order
    lock_fund(db, order.fund_code)
    fund = db.get(Fund, order.fund_code, populate_existing=True)
    latest_run = db.scalar(select(FundSyncRun).where(FundSyncRun.fund_code == order.fund_code)
                           .order_by(FundSyncRun.started_at.desc()).limit(1))
    nav = db.get(FundNav, (order.fund_code, order.trade_date), populate_existing=True)
    # Missing/revised data never falls back to yesterday or the latest arbitrary NAV.
    if not nav or fund.is_sample or (latest_run and latest_run.status in ('conflict', 'failed')):
        return order
    order.confirmed_nav = nav.unit_nav
    order.shares = rounded(order.net_amount / nav.unit_nav)
    if order.shares <= 0:
        raise HTTPException(409, '份额精度异常，保留在途资金，等待核验。')
    order.status, order.completed_at = 'confirmed', now
    db.add(PositionLot(account_id=account.id, order_id=order.id, fund_code=order.fund_code,
                       shares=order.shares, cost=order.amount, remaining_shares=order.shares,
                       remaining_cost=order.amount, confirmation_date=order.confirmation_date))
    add_ledger(db, account, order, 'buy_confirmed', Decimal('0'), -order.amount, now)
    db.flush()
    return order


def serialize_order(db, order, now):
    return {'id': str(order.id), 'kind': 'buy', 'fund_code': order.fund_code, 'fund_name': db.get(Fund, order.fund_code).name,
            'status': order.status, 'amount': str(order.amount), 'fee': str(order.fee), 'net_amount': str(order.net_amount),
            'trade_date': order.trade_date, 'confirmation_date': order.confirmation_date,
            'cancel_until': order.cancel_until, 'can_cancel': order.status == 'pending' and now < order.cancel_until,
            'confirmed_nav': str(order.confirmed_nav) if order.confirmed_nav is not None else None,
            'shares': str(order.shares) if order.shares is not None else None,
            'created_at': order.created_at, 'completed_at': order.completed_at, 'rule': order.rule_snapshot,
            'wait_reason': '等待确认日及对应正式净值；数据缺失或同步异常时继续等待。' if order.status == 'pending' else ''}


def portfolio(db, account, now=None):
    from .earnings import earnings
    from .redemptions import lots_event, sale_context
    from .dividends import dividend_totals
    now = now or utcnow()
    lots = db.scalars(select(PositionLot).where(PositionLot.account_id == account.id, PositionLot.remaining_shares > 0)).all()
    grouped = {}
    for lot in lots:
        row = grouped.setdefault(lot.fund_code, {'shares': Decimal(0), 'cost': Decimal(0), 'frozen': Decimal(0), 'lots': []})
        row['shares'] += lot.remaining_shares
        row['cost'] += lot.remaining_cost
        row['frozen'] += lot.frozen_shares
        row['lots'].append({'order_id': str(lot.order_id), 'shares': str(lot.remaining_shares),
                            'frozen_shares': str(lot.frozen_shares), 'cost': str(lot.remaining_cost),
                            'confirmation_date': lot.confirmation_date})
    items, total, remaining_cost = [], Decimal('0.00'), Decimal('0.00')
    history_lots = db.scalars(select(PositionLot).where(PositionLot.account_id == account.id)).all()
    event_warning = lots_event(db, history_lots, now.astimezone(CN).date())
    returns = earnings(db, account.id, now.astimezone(CN).date(), event_warning)
    for code, row in grouped.items():
        nav = db.scalar(select(FundNav).where(FundNav.fund_code == code, FundNav.nav_date <= now.astimezone(CN).date())
                        .order_by(FundNav.nav_date.desc()).limit(1))
        value = rounded(row['shares'] * nav.unit_nav) if nav else None
        if value is not None:
            total += value
        remaining_cost += row['cost']
        context, _ = sale_context(db, account.id, code, now)
        items.append({'fund_code': code, 'fund_name': db.get(Fund, code).name, 'shares': str(row['shares']),
                      'frozen_shares': str(row['frozen']), 'available_shares': context['available_shares'],
                      'sell_disabled_reason': context['disabled_reason'],
                      'cost': str(row['cost']), 'market_value': str(value) if value is not None else None,
                      'holding_profit': str(value - row['cost']) if value is not None and not event_warning else None,
                      'holding_return': str(rounded((value - row['cost']) / row['cost'] * 100)) if value is not None and row['cost'] and not event_warning else None,
                      'latest_profit': returns['fund_latest_profit'].get(code),
                      'nav_date': nav.nav_date if nav else None, 'unit_nav': str(nav.unit_nav) if nav else None,
                      'lots': row['lots']})
    complete = all(i['market_value'] is not None for i in items)
    dividend_cash, dividend_income = dividend_totals(db, account.id)
    assets = account.available_cash + account.reserved_cash + account.redemption_cash + dividend_cash + total
    initial = db.scalar(select(func.coalesce(func.sum(CashLedger.amount), 0)).where(
        CashLedger.account_id == account.id, CashLedger.kind == 'initial_capital'))
    realized = db.scalar(select(func.coalesce(func.sum(SellAllocation.net_amount - SellAllocation.cost), 0))
        .join(SellOrder, SellAllocation.order_id == SellOrder.id).where(SellOrder.account_id == account.id,
        SellOrder.status.in_(['confirmed', 'paid'])))
    return {**returns, 'items': items, 'available_cash': str(account.available_cash), 'reserved_cash': str(account.reserved_cash),
            'holding_return': str(rounded((total - remaining_cost) / remaining_cost * 100)) if complete and remaining_cost and not event_warning else None,
            'redemption_cash': str(account.redemption_cash), 'market_value': str(total) if complete else None,
            'total_assets': str(assets) if complete else None,
            'total_profit': str(assets - initial) if complete and not event_warning else None,
            'holding_profit': str(total - remaining_cost) if complete and not event_warning else None,
            'dividend_cash': str(dividend_cash), 'dividend_income': str(dividend_income),
            'realized_profit': str(realized + dividend_income) if not event_warning else None,
            'valuation_note': event_warning or '市值按最新已保存正式净值估算；累计及已实现收益含交易费和已登记现金分红，持仓收益为剩余份额市值减剩余成本。'}


@router.post('/trades/quote', dependencies=[Depends(write_guard)])
def quote(body: QuoteInput, user: CurrentUser, db: DB, now: Clock):
    return quote_values(db, body, owned_account(db, user), now)


@router.post('/orders', status_code=201, dependencies=[Depends(write_guard)])
def submit(body: BuyInput, user: CurrentUser, db: DB, clock: ClockFunction):
    order = create_buy(db, owned_account(db, user).id, body, clock)
    db.commit()
    return serialize_order(db, order, clock())


@router.get('/orders')
def orders(user: CurrentUser, db: DB, now: Clock,
           status: Literal['all', 'pending', 'confirmed', 'paid', 'cancelled'] = 'all',
           kind: Literal['all', 'buy', 'sell'] = 'all',
           page: Annotated[int, Query(ge=1)] = 1):
    from .redemptions import serialize_sell
    account = owned_account(db, user)
    queries = []
    for model, label in ((BuyOrder, 'buy'), (SellOrder, 'sell')):
        if kind != 'all' and kind != label:
            continue
        q = select(model.id, model.created_at, literal(label).label('kind')).where(model.account_id == account.id)
        if status != 'all':
            q = q.where(model.status == status)
        queries.append(q)
    combined = union_all(*queries).subquery()
    total = db.scalar(select(func.count()).select_from(combined))
    rows = db.execute(select(combined).order_by(combined.c.created_at.desc(), combined.c.id).offset((page - 1) * 20).limit(20)).all()
    items = [serialize_order(db, db.get(BuyOrder, r.id), now) if r.kind == 'buy'
             else serialize_sell(db, db.get(SellOrder, r.id), now) for r in rows]
    return {'items': items, 'total': total, 'page': page, 'page_size': 20}


@router.get('/orders/{order_id}')
def order_detail(order_id: UUID, user: CurrentUser, db: DB, now: Clock):
    return serialize_order(db, owned_order(db, owned_account(db, user).id, order_id), now)


@router.post('/orders/{order_id}/cancel', dependencies=[Depends(write_guard)])
def cancel(order_id: UUID, user: CurrentUser, db: DB, clock: ClockFunction):
    order = cancel_buy(db, owned_account(db, user).id, order_id, clock)
    db.commit()
    return serialize_order(db, order, clock())


@router.post('/orders/{order_id}/refresh', dependencies=[Depends(write_guard)])
def refresh(order_id: UUID, user: CurrentUser, db: DB, clock: ClockFunction):
    order = settle_buy(db, owned_account(db, user).id, order_id, clock)
    db.commit()
    return serialize_order(db, order, clock())


@router.get('/holdings')
def holdings(user: CurrentUser, db: DB, now: Clock):
    account = owned_account(db, user)
    # Consistent cash/position snapshot while the settlement worker changes both.
    account = lock_account(db, account.id)
    return portfolio(db, account, now)
