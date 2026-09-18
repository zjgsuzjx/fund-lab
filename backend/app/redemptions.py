"""FIFO redemption reservations, exact-NAV confirmation and deferred cash arrival."""
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from .auth import DB, CurrentUser, owned_account, write_guard
from .models import BuyOrder, CashLedger, Fund, FundNav, FundSyncRun, PositionLot, SellAllocation, SellOrder
from .trade_rules import CN, SELL_RULE, redemption_rate, redemption_schedule, rounded, utcnow
from .trades import Clock, ClockFunction, lock_account, lock_fund

router = APIRouter(prefix='/api')


class SellQuoteInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    fund_code: str = Field(pattern=r'^[0-9]{6}$')
    shares: Decimal = Field(ge=Decimal('0.01'), le=100000000, decimal_places=2, allow_inf_nan=False)


class SellInput(SellQuoteInput):
    request_key: UUID
    quote_token: str = Field(pattern=r'^[a-f0-9]{64}$')


def active_lots(db, account_id, code):
    return db.scalars(select(PositionLot).join(BuyOrder, PositionLot.order_id == BuyOrder.id)
        .where(PositionLot.account_id == account_id, PositionLot.fund_code == code, PositionLot.remaining_shares > 0)
        .order_by(PositionLot.confirmation_date, BuyOrder.created_at, PositionLot.id)
        .execution_options(populate_existing=True)).all()


def event_between(db, code, after, through):
    return db.scalar(select(FundNav.nav_date).where(FundNav.fund_code == code, FundNav.nav_date > after,
        FundNav.nav_date <= through, FundNav.dividend_note.is_not(None), FundNav.dividend_note != '')
        .order_by(FundNav.nav_date).limit(1))


def lots_event(db, lots, through):
    for lot in lots:
        buy = db.get(BuyOrder, lot.order_id)
        if event := event_between(db, lot.fund_code, buy.trade_date, through):
            return f'{event} 存在未处理分红或份额事件，需核验权益后再赎回。'
    return ''


def source_problem(db, code):
    fund = db.get(Fund, code, populate_existing=True)
    if not fund or fund.is_sample:
        return '基金尚无已核验的正式净值。'
    run = db.scalar(select(FundSyncRun).where(FundSyncRun.fund_code == code).order_by(FundSyncRun.started_at.desc()).limit(1))
    if run and run.status != 'success':
        return '最近净值同步异常，等待核验后重试。'
    return ''


def sale_context(db, account_id, code, now):
    fund = db.get(Fund, code)
    if not fund:
        raise HTTPException(404, '未找到基金。')
    lots = active_lots(db, account_id, code)
    total = sum((l.remaining_shares for l in lots), Decimal('0.00'))
    frozen = sum((l.frozen_shares for l in lots), Decimal('0.00'))
    reason = ''
    trade = confirmation = cutoff = arrival = None
    try:
        trade, confirmation, cutoff, arrival = redemption_schedule(now)
    except HTTPException as exc:
        reason = exc.detail
    if code != SELL_RULE['fund_code']:
        reason = '该基金尚未核验赎回规则。'
    elif not SELL_RULE['simulation_from'] <= now.astimezone(CN).date().isoformat() <= SELL_RULE['simulation_through']:
        reason = '赎回模拟规则不覆盖当前日期。'
    else:
        reason = reason or source_problem(db, code)
        if not fund.last_sync_at or now - fund.last_sync_at > timedelta(days=7):
            reason = reason or '净值数据超过 7 天未同步，请先更新。'
        reason = reason or lots_event(db, lots, trade or now.astimezone(CN).date())
    available = sum((l.remaining_shares - l.frozen_shares for l in lots if trade and l.confirmation_date < trade), Decimal('0.00'))
    nav = db.scalar(select(FundNav).where(FundNav.fund_code == code, FundNav.nav_date <= now.astimezone(CN).date())
                    .order_by(FundNav.nav_date.desc()).limit(1))
    if not nav:
        reason = reason or '缺少参考正式净值，暂不能试算。'
    return {'fund_code': code, 'fund_name': fund.name, 'total_shares': str(total), 'frozen_shares': str(frozen),
        'available_shares': str(available), 'locked_shares': str(total - frozen - available),
        'reference_nav': str(nav.unit_nav) if nav else None, 'reference_date': nav.nav_date.isoformat() if nav else None,
        'trade_date': trade.isoformat() if trade else None, 'confirmation_date': confirmation.isoformat() if confirmation else None,
        'arrival_date': arrival.isoformat() if arrival else None, 'cancel_until': cutoff.isoformat() if cutoff else None,
        'disabled_reason': reason, 'rule': deepcopy(SELL_RULE)}, lots


def allocation_values(shares, nav, rate):
    gross = rounded(shares * nav)
    fee = rounded(gross * rate)
    return gross, fee, gross - fee


def sell_quote(db, account_id, body, now):
    context, lots = sale_context(db, account_id, body.fund_code, now)
    if context['disabled_reason']:
        raise HTTPException(409, context['disabled_reason'])
    if body.shares > Decimal(context['available_shares']):
        raise HTTPException(409, '可赎回份额不足，待确认、未到可赎回日及已冻结份额不能重复卖出。')
    remaining, allocations = body.shares, []
    nav = Decimal(context['reference_nav'])
    trade, confirmation = date.fromisoformat(context['trade_date']), date.fromisoformat(context['confirmation_date'])
    for lot in lots:
        if not remaining:
            break
        if lot.confirmation_date >= trade:
            continue  # T+2 or later, never sell on the buy's confirmation date.
        shares = min(remaining, lot.remaining_shares - lot.frozen_shares)
        if shares <= 0:
            continue
        days = (confirmation - lot.confirmation_date).days
        rate = redemption_rate(days)
        gross, fee, net = allocation_values(shares, nav, rate)
        allocations.append({'lot_id': str(lot.id), 'buy_order_id': str(lot.order_id), 'shares': str(rounded(shares)),
            'confirmation_date': lot.confirmation_date.isoformat(), 'holding_days': days, 'fee_rate': str(rate),
            'gross_amount': str(gross), 'fee': str(fee), 'net_amount': str(net)})
        remaining -= shares
    if remaining:
        raise HTTPException(409, '持仓状态已变化，请重新试算。')
    quote = {**context, 'shares': str(rounded(body.shares)), 'allocations': allocations,
        **{key: str(sum((Decimal(a[key]) for a in allocations), Decimal('0.00'))) for key in ('gross_amount', 'fee', 'net_amount')}}
    # Bind what the user reviewed: dates, NAV reference, FIFO selection and fee tiers.
    quote['quote_token'] = sha256(json.dumps(quote, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return quote


def create_sell(db, account_id, body, clock=utcnow):
    account = lock_account(db, account_id)
    existing = db.scalar(select(SellOrder).where(SellOrder.account_id == account.id, SellOrder.request_key == body.request_key))
    if existing:
        if existing.fund_code != body.fund_code or existing.shares != body.shares:
            raise HTTPException(409, '同一请求编号不能用于不同卖出，请先查看原订单。')
        return existing
    lock_fund(db, body.fund_code)
    now = clock()
    quote = sell_quote(db, account.id, body, now)
    if quote['quote_token'] != body.quote_token:
        raise HTTPException(409, '持仓、交易日期或试算信息已变化，请重新试算后确认。')
    from datetime import datetime
    order = SellOrder(account_id=account.id, fund_code=body.fund_code, request_key=body.request_key, shares=body.shares,
        trade_date=date.fromisoformat(quote['trade_date']), confirmation_date=date.fromisoformat(quote['confirmation_date']),
        arrival_date=date.fromisoformat(quote['arrival_date']), cancel_until=datetime.fromisoformat(quote['cancel_until']),
        rule_snapshot=deepcopy(SELL_RULE), quote_snapshot=quote, created_at=now)
    db.add(order); db.flush()
    for a in quote['allocations']:
        lot = db.get(PositionLot, UUID(a['lot_id']))
        lot.frozen_shares += Decimal(a['shares'])
        db.add(SellAllocation(order_id=order.id, lot_id=lot.id, shares=Decimal(a['shares']),
            holding_days=a['holding_days'], fee_rate=Decimal(a['fee_rate'])))
    db.flush()
    return order


def owned_sell(db, account_id, order_id):
    order = db.scalar(select(SellOrder).where(SellOrder.id == order_id, SellOrder.account_id == account_id)
                      .execution_options(populate_existing=True))
    if not order:
        raise HTTPException(404, '未找到这笔模拟订单。')
    return order


def allocations_for(db, order):
    return db.scalars(select(SellAllocation).where(SellAllocation.order_id == order.id).order_by(SellAllocation.lot_id)).all()


def cancel_sell(db, account_id, order_id, clock=utcnow):
    account = lock_account(db, account_id)
    order = owned_sell(db, account.id, order_id)
    if order.status == 'cancelled':
        return order
    now = clock()
    if order.status != 'pending' or now >= order.cancel_until:
        raise HTTPException(409, '订单已确认或已超过可撤单截止时间。')
    for allocation in allocations_for(db, order):
        db.get(PositionLot, allocation.lot_id).frozen_shares -= allocation.shares
    order.status, order.cancelled_at = 'cancelled', now
    db.flush()
    return order


def redemption_ledger(db, account, order, kind, available_delta, redemption_delta, now):
    account.available_cash += available_delta
    account.redemption_cash += redemption_delta
    db.add(CashLedger(account_id=account.id, event_key=f'{kind}:{order.id}', kind=kind,
        amount=order.net_amount, balance_after=account.available_cash, available_delta=available_delta,
        reserved_delta=Decimal('0'), reserved_after=account.reserved_cash,
        redemption_delta=redemption_delta, redemption_after=account.redemption_cash, created_at=now))


def settle_sell(db, account_id, order_id, clock=utcnow):
    account = lock_account(db, account_id)
    order = owned_sell(db, account.id, order_id)
    now = clock()
    today = now.astimezone(CN).date()
    if order.status in ('paid', 'cancelled') or today < order.confirmation_date:
        return order
    if order.status == 'pending':
        lock_fund(db, order.fund_code)
        allocations = allocations_for(db, order)
        lots = [db.get(PositionLot, a.lot_id) for a in allocations]
        nav = db.get(FundNav, (order.fund_code, order.trade_date), populate_existing=True)
        if not nav or source_problem(db, order.fund_code) or lots_event(db, lots, order.trade_date):
            return order
        order.gross_amount = order.fee = order.net_amount = Decimal('0.00')
        for allocation, lot in zip(allocations, lots):
            if allocation.shares > lot.frozen_shares or allocation.shares > lot.remaining_shares:
                raise HTTPException(409, '冻结份额账本异常，等待核验。')
            allocation.gross_amount, allocation.fee, allocation.net_amount = allocation_values(allocation.shares, nav.unit_nav, allocation.fee_rate)
            # The final redemption takes the exact residual cent; repeated partial sales cannot leak cost.
            allocation.cost = lot.remaining_cost if allocation.shares == lot.remaining_shares else rounded(lot.remaining_cost * allocation.shares / lot.remaining_shares)
            lot.remaining_shares -= allocation.shares
            lot.frozen_shares -= allocation.shares
            lot.remaining_cost -= allocation.cost
            order.gross_amount += allocation.gross_amount
            order.fee += allocation.fee
            order.net_amount += allocation.net_amount
        order.status, order.confirmed_nav, order.confirmed_at = 'confirmed', nav.unit_nav, now
        redemption_ledger(db, account, order, 'sell_confirmed', Decimal('0'), order.net_amount, now)
        db.flush()
    if order.status == 'confirmed' and today >= order.arrival_date:
        # Already confirmed money is independent of subsequent quote/source availability.
        redemption_ledger(db, account, order, 'sell_paid', order.net_amount, -order.net_amount, now)
        order.status, order.paid_at = 'paid', now
        db.flush()
    return order


def serialize_sell(db, order, now):
    allocations = allocations_for(db, order)
    actual = order.status in ('confirmed', 'paid')
    reason = ''
    if order.status == 'pending':
        reason = lots_event(db, [db.get(PositionLot, a.lot_id) for a in allocations], order.trade_date) or source_problem(db, order.fund_code) or '等待确认日及对应交易日正式净值。'
    return {'id': str(order.id), 'kind': 'sell', 'fund_code': order.fund_code,
        'fund_name': db.get(Fund, order.fund_code).name, 'status': order.status, 'shares': str(order.shares),
        'trade_date': order.trade_date, 'confirmation_date': order.confirmation_date, 'arrival_date': order.arrival_date,
        'cancel_until': order.cancel_until, 'can_cancel': order.status == 'pending' and now < order.cancel_until,
        'created_at': order.created_at, 'confirmed_at': order.confirmed_at, 'paid_at': order.paid_at,
        'completed_at': order.paid_at or order.cancelled_at, 'rule': order.rule_snapshot,
        'quote': order.quote_snapshot, 'wait_reason': reason,
        'confirmed_nav': str(order.confirmed_nav) if actual else None,
        'gross_amount': str(order.gross_amount) if actual else None,
        'fee': str(order.fee) if actual else None, 'net_amount': str(order.net_amount) if actual else None,
        'realized_profit': str(order.net_amount - sum((a.cost for a in allocations), Decimal(0))) if actual else None,
        'allocations': [{'lot_id': str(a.lot_id), 'shares': str(a.shares), 'holding_days': a.holding_days,
            'fee_rate': str(a.fee_rate), 'cost': str(a.cost) if a.cost is not None else None,
            'fee': str(a.fee) if a.fee is not None else None} for a in allocations]}


@router.get('/redemptions/context/{code}')
def context(code: str, user: CurrentUser, db: DB, now: Clock):
    account = lock_account(db, owned_account(db, user).id)
    return sale_context(db, account.id, code, now)[0]


@router.post('/redemptions/quote', dependencies=[Depends(write_guard)])
def quote(body: SellQuoteInput, user: CurrentUser, db: DB, now: Clock):
    account = lock_account(db, owned_account(db, user).id)
    return sell_quote(db, account.id, body, now)


@router.post('/redemptions', status_code=201, dependencies=[Depends(write_guard)])
def submit(body: SellInput, user: CurrentUser, db: DB, clock: ClockFunction):
    order = create_sell(db, owned_account(db, user).id, body, clock)
    db.commit()
    return serialize_sell(db, order, clock())


@router.get('/redemptions/{order_id}')
def detail(order_id: UUID, user: CurrentUser, db: DB, now: Clock):
    return serialize_sell(db, owned_sell(db, owned_account(db, user).id, order_id), now)


@router.post('/redemptions/{order_id}/cancel', dependencies=[Depends(write_guard)])
def cancel(order_id: UUID, user: CurrentUser, db: DB, clock: ClockFunction):
    order = cancel_sell(db, owned_account(db, user).id, order_id, clock)
    db.commit()
    return serialize_sell(db, order, clock())


@router.post('/redemptions/{order_id}/refresh', dependencies=[Depends(write_guard)])
def refresh(order_id: UUID, user: CurrentUser, db: DB, clock: ClockFunction):
    order = settle_sell(db, owned_account(db, user).id, order_id, clock)
    db.commit()
    return serialize_sell(db, order, clock())
