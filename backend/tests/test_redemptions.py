from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.main import app
from app.models import BuyOrder, CashLedger, Fund, FundNav, FundSyncRun, PositionLot, SellAllocation, SellOrder, SimulationAccount, User
from app.redemptions import SellInput, SellQuoteInput, cancel_sell, create_sell, sell_quote, settle_sell
from app.trade_rules import CN, SELL_RULE, redemption_rate, redemption_schedule, utcnow
from app.trades import clock_provider, lock_account
from test_api import db
from test_auth import client, credentials

NOW = datetime(2026, 9, 17, 14, 30, tzinfo=CN)


def add_lot(db, account, code, confirmed, shares='100.00', cost='100.80'):
    shares, cost = Decimal(shares), Decimal(cost)
    order = BuyOrder(account_id=account.id, fund_code=code, request_key=uuid4(), status='confirmed',
        amount=cost, fee=cost - shares, net_amount=shares, trade_date=confirmed - timedelta(days=1),
        confirmation_date=confirmed, cancel_until=datetime.combine(confirmed, datetime.min.time(), CN),
        rule_snapshot={'fixture': True}, confirmed_nav=Decimal('1'), shares=shares,
        created_at=datetime.combine(confirmed, datetime.min.time(), CN) - timedelta(days=1), completed_at=NOW)
    db.add(order); db.flush()
    lot = PositionLot(account_id=account.id, order_id=order.id, fund_code=code, shares=shares, cost=cost,
        remaining_shares=shares, remaining_cost=cost, frozen_shares=Decimal(0), confirmation_date=confirmed)
    db.add(lot)
    account.available_cash -= cost
    db.add(CashLedger(account_id=account.id, kind='buy_reserved', event_key=f'buy_reserved:{order.id}',
        amount=cost, available_delta=-cost, reserved_delta=cost, balance_after=account.available_cash,
        reserved_after=cost, redemption_after=0))
    db.add(CashLedger(account_id=account.id, kind='buy_confirmed', event_key=f'buy_confirmed:{order.id}',
        amount=cost, available_delta=0, reserved_delta=-cost, balance_after=account.available_cash,
        reserved_after=0, redemption_after=0))
    db.flush()
    return lot


@pytest.fixture
def ready_sell(client, db):
    fund = db.get(Fund, '000147')
    fund.is_sample, fund.trade_enabled, fund.last_sync_at = False, True, NOW
    db.execute(delete(FundSyncRun).where(FundSyncRun.fund_code == fund.code))
    db.execute(delete(FundNav).where(FundNav.fund_code == fund.code))
    client.post('/api/auth/register', json=credentials()).raise_for_status()
    account = db.get(SimulationAccount, UUID(client.get('/api/account').json()['id']))
    lots = [add_lot(db, account, fund.code, date(2026, 8, 14)), add_lot(db, account, fund.code, date(2026, 9, 16))]
    db.add(FundNav(fund_code=fund.code, nav_date=date(2026, 9, 16), unit_nav=Decimal('1.10')))
    db.commit()
    clock = [NOW]
    app.dependency_overrides[utcnow] = lambda: clock[0]
    app.dependency_overrides[clock_provider] = lambda: lambda: clock[0]
    return client, db, clock, account, lots


def request_body(client, shares='150.00'):
    response = client.post('/api/redemptions/quote', json={'fund_code': '000147', 'shares': shares})
    assert response.status_code == 200, response.text
    quote = response.json()
    return {'fund_code': '000147', 'shares': shares, 'quote_token': quote['quote_token'], 'request_key': str(uuid4())}, quote


@pytest.mark.parametrize('days,rate', [(0, '.015'), (6, '.015'), (7, '.0075'), (29, '.0075'), (30, '.001'),
    (364, '.001'), (365, '.0005'), (729, '.0005'), (730, '0')])
def test_redemption_fee_boundaries(days, rate):
    assert redemption_rate(days) == Decimal(rate)


def test_redemption_dates_exclude_holidays_and_fail_closed_across_year():
    trade, confirm, _, arrival = redemption_schedule(NOW)
    assert (trade, confirm, arrival) == (date(2026, 9, 17), date(2026, 9, 18), date(2026, 9, 29))
    assert redemption_schedule(NOW.replace(hour=15))[0] == date(2026, 9, 18)
    with pytest.raises(HTTPException):
        redemption_schedule(datetime(2026, 12, 25, 14, tzinfo=CN))


@pytest.mark.integration
def test_fifo_mixed_fees_freeze_exact_nav_confirmation_and_payment(ready_sell):
    client, db, clock, account, lots = ready_sell
    body, quote = request_body(client)
    assert [a['lot_id'] for a in quote['allocations']] == [str(l.id) for l in lots]
    assert [a['shares'] for a in quote['allocations']] == ['100.00', '50.00']
    assert [a['fee_rate'] for a in quote['allocations']] == ['0.001', '0.015']
    assert (quote['gross_amount'], quote['fee'], quote['net_amount']) == ('165.00', '0.94', '164.06')
    created = client.post('/api/redemptions', json=body)
    assert created.status_code == 201, created.text
    order = created.json(); url = f"/api/redemptions/{order['id']}"
    assert client.post('/api/redemptions', json=body).json()['id'] == order['id']
    context = client.get('/api/redemptions/context/000147').json()
    assert (context['frozen_shares'], context['available_shares']) == ('150.00', '50.00')
    assert client.get('/api/account').json()['available_cash'] == '99798.40'
    assert client.post(url + '/refresh').json()['status'] == 'pending'
    clock[0] = NOW + timedelta(days=1)
    assert client.post(url + '/refresh').json()['status'] == 'pending'
    db.add(FundNav(fund_code='000147', nav_date=NOW.date(), unit_nav=Decimal('1.20'))); db.commit()
    clock[0] = NOW
    assert client.post(url + '/refresh').json()['status'] == 'pending'
    clock[0] = NOW + timedelta(days=1)
    result = client.post(url + '/refresh').json()
    assert (result['status'], result['gross_amount'], result['fee'], result['net_amount']) == ('confirmed', '180.00', '1.02', '178.98')
    assert result['realized_profit'] == '27.78'
    assert client.post(url + '/cancel').status_code == 409
    assert client.post(url + '/refresh').json()['status'] == 'confirmed'
    portfolio = client.get('/api/holdings').json()
    assert (portfolio['available_cash'], portfolio['redemption_cash'], portfolio['total_assets']) == ('99798.40', '178.98', '100037.38')
    assert (portfolio['items'][0]['shares'], portfolio['items'][0]['cost']) == ('50.00', '50.40')
    clock[0] = datetime(2026, 9, 29, tzinfo=CN)
    assert client.post(url + '/refresh').json()['status'] == 'paid'
    assert client.post(url + '/refresh').json()['status'] == 'paid'
    data = client.get('/api/account').json()
    assert (data['available_cash'], data['redemption_cash'], data['total_assets']) == ('99977.38', '0.00', '100037.38')
    ledger = client.get('/api/account/ledger').json()['items']
    for field, delta in [('available_cash', 'available_delta'), ('reserved_cash', 'reserved_delta'), ('redemption_cash', 'redemption_delta')]:
        assert Decimal(data[field]) == sum(Decimal(e[delta]) for e in ledger)
    assert len([e for e in ledger if e['kind'] == 'sell_paid']) == 1
    assert client.get('/api/orders?kind=sell&status=paid').json()['total'] == 1
    assert client.get('/api/orders?kind=buy').json()['total'] == 2


@pytest.mark.integration
def test_cancel_release_and_idempotent_replay_with_changed_body(ready_sell):
    client, db, clock, account, lots = ready_sell
    body, _ = request_body(client, '200')
    order = client.post('/api/redemptions', json=body).json()
    assert client.post('/api/redemptions', json={**body, 'shares': '1'}).status_code == 409
    assert client.post(f"/api/redemptions/{order['id']}/cancel").json()['status'] == 'cancelled'
    assert client.post(f"/api/redemptions/{order['id']}/cancel").status_code == 200
    assert client.post('/api/redemptions', json=body).json()['status'] == 'cancelled'
    assert client.get('/api/redemptions/context/000147').json()['available_shares'] == '200.00'
    assert client.get('/api/account').json()['available_cash'] == '99798.40'


@pytest.mark.integration
@pytest.mark.parametrize('shares', ['0', '-1', '0.001', 'NaN', 'Infinity', '1e9999', '200.01'])
def test_invalid_or_excess_shares_cannot_freeze(ready_sell, shares):
    client, db, clock, account, lots = ready_sell
    assert client.post('/api/redemptions/quote', json={'fund_code': '000147', 'shares': shares}).status_code in (409, 422)
    assert sum(l.frozen_shares for l in lots) == 0


@pytest.mark.integration
def test_changed_quote_cutoff_and_ownership(ready_sell):
    client, db, clock, account, lots = ready_sell
    body, _ = request_body(client)
    clock[0] = NOW.replace(hour=15, minute=0)
    assert client.post('/api/redemptions', json=body).status_code == 409
    clock[0] = NOW
    order = client.post('/api/redemptions', json=body).json()
    clock[0] = NOW.replace(hour=15, minute=0)
    assert client.post(f"/api/redemptions/{order['id']}/cancel").status_code == 409
    client.post('/api/auth/register', json=credentials()).raise_for_status()
    assert client.get(f"/api/redemptions/{order['id']}").status_code == 404
    for operation in ('cancel', 'refresh'):
        assert client.post(f"/api/redemptions/{order['id']}/{operation}").status_code == 404
    assert client.get('/api/orders').json()['total'] == 0
    assert client.get('/api/redemptions/context/000147').json()['available_shares'] == '0.00'
    assert client.post('/api/redemptions', json={**body, 'account_id': str(account.id)}).status_code == 422


@pytest.mark.integration
def test_cannot_redeem_on_buy_confirmation_day(ready_sell):
    client, db, clock, account, lots = ready_sell
    lots[0].confirmation_date = lots[1].confirmation_date = NOW.date()
    db.commit()
    assert client.get('/api/redemptions/context/000147').json()['available_shares'] == '0.00'
    assert client.post('/api/redemptions/quote', json={'fund_code': '000147', 'shares': '1'}).status_code == 409
    clock[0] = NOW.replace(hour=15)
    assert client.get('/api/redemptions/context/000147').json()['available_shares'] == '200.00'  # Queued for T+2.


@pytest.mark.integration
def test_source_event_blocks_confirmation_until_resolved_but_paid_receivable_is_independent(ready_sell):
    client, db, clock, account, lots = ready_sell
    body, _ = request_body(client)
    order = client.post('/api/redemptions', json=body).json()
    nav = FundNav(fund_code='000147', nav_date=NOW.date(), unit_nav=Decimal('1.2'), dividend_note='分红事件')
    db.add(nav); db.commit(); clock[0] = NOW + timedelta(days=1)
    assert client.post(f"/api/redemptions/{order['id']}/refresh").json()['status'] == 'pending'
    assert '分红' in client.get('/api/redemptions/context/000147').json()['disabled_reason']
    nav.dividend_note = None
    run = FundSyncRun(fund_code='000147', status='conflict')
    db.add(run); db.commit()
    assert client.post(f"/api/redemptions/{order['id']}/refresh").json()['status'] == 'pending'
    run.status = 'success'; db.commit()
    assert client.post(f"/api/redemptions/{order['id']}/refresh").json()['status'] == 'confirmed'
    run.status = 'failed'; db.commit(); clock[0] = datetime(2026, 9, 29, tzinfo=CN)
    assert client.post(f"/api/redemptions/{order['id']}/refresh").json()['status'] == 'paid'


@pytest.mark.integration
def test_settlement_rollback_and_full_redemption_cost_residual(ready_sell, monkeypatch):
    from app import redemptions
    client, db, clock, account, lots = ready_sell
    body, _ = request_body(client, '199.99')
    order = client.post('/api/redemptions', json=body).json()
    db.add(FundNav(fund_code='000147', nav_date=NOW.date(), unit_nav=Decimal('1.2'))); db.commit()
    original = redemptions.redemption_ledger
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('injected transaction failure')
    monkeypatch.setattr(redemptions, 'redemption_ledger', fail)
    with pytest.raises(RuntimeError), db.begin_nested():
        settle_sell(db, account.id, UUID(order['id']), lambda: NOW + timedelta(days=1))
    assert db.get(SellOrder, UUID(order['id'])).status == 'pending'
    assert sum(l.remaining_shares for l in lots) == 200
    assert sum(l.frozen_shares for l in lots) == Decimal('199.99')
    monkeypatch.setattr(redemptions, 'redemption_ledger', original)
    clock[0] = NOW + timedelta(days=1)
    assert client.post(f"/api/redemptions/{order['id']}/refresh").json()['status'] == 'confirmed'
    body2, _ = request_body(client, '0.01')
    second = client.post('/api/redemptions', json=body2).json()
    db.add(FundNav(fund_code='000147', nav_date=date(2026, 9, 18), unit_nav=Decimal('1.2'))); db.commit()
    clock[0] = datetime(2026, 9, 21, tzinfo=CN)
    assert client.post(f"/api/redemptions/{second['id']}/refresh").json()['status'] == 'confirmed'
    assert client.get('/api/holdings').json()['items'] == []
    db.expire_all()
    assert all(l.remaining_shares == l.frozen_shares == l.remaining_cost == 0 for l in lots)
    assert db.scalar(select(func.sum(SellAllocation.cost)).join(SellOrder).where(SellOrder.account_id == account.id)) == Decimal('201.60')


@pytest.mark.integration
def test_buy_while_redemption_pending_preserves_receivable_ledger(ready_sell):
    client, db, clock, account, _ = ready_sell
    body, _ = request_body(client)
    order = client.post('/api/redemptions', json=body).json()
    db.add(FundNav(fund_code='000147', nav_date=NOW.date(), unit_nav=Decimal('1.2'))); db.commit()
    clock[0] = NOW + timedelta(days=1)
    client.post(f"/api/redemptions/{order['id']}/refresh").raise_for_status()
    quote = client.post('/api/trades/quote', json={'fund_code': '000147', 'amount': '10'}).json()
    buy = client.post('/api/orders', json={'fund_code': '000147', 'amount': '10',
        'request_key': str(uuid4()), 'rule_version': quote['rule_version'], 'trade_date': quote['trade_date']})
    buy.raise_for_status()
    client.post(f"/api/orders/{buy.json()['id']}/cancel").raise_for_status()
    ledger = client.get('/api/account/ledger').json()['items']
    assert all(Decimal(e['redemption_after']) == Decimal('178.98') for e in ledger if e['kind'] == 'buy_cancelled')
    assert client.get('/api/account').json()['redemption_cash'] == '178.98'


@pytest.mark.integration
def test_payment_failure_rolls_back_cash_and_receivable(ready_sell, monkeypatch):
    from app import redemptions
    client, db, clock, account, _ = ready_sell
    body, _ = request_body(client)
    order = client.post('/api/redemptions', json=body).json()
    db.add(FundNav(fund_code='000147', nav_date=NOW.date(), unit_nav=Decimal('1.2'))); db.commit()
    clock[0] = NOW + timedelta(days=1)
    client.post(f"/api/redemptions/{order['id']}/refresh").raise_for_status()
    original = redemptions.redemption_ledger
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('injected payment failure')
    monkeypatch.setattr(redemptions, 'redemption_ledger', fail)
    arrival = datetime(2026, 9, 29, tzinfo=CN)
    with pytest.raises(RuntimeError), db.begin_nested():
        settle_sell(db, account.id, UUID(order['id']), lambda: arrival)
    db.expire_all()
    assert db.get(SellOrder, UUID(order['id'])).status == 'confirmed'
    assert account.available_cash == Decimal('99798.40')
    assert account.redemption_cash == Decimal('178.98')
    assert db.scalar(select(func.count()).select_from(CashLedger).where(CashLedger.event_key == f"sell_paid:{order['id']}")) == 0
    monkeypatch.setattr(redemptions, 'redemption_ledger', original)
    clock[0] = arrival
    assert client.post(f"/api/redemptions/{order['id']}/refresh").json()['status'] == 'paid'


@pytest.mark.integration
def test_parallel_oversell_cancel_confirm_payment_and_restart_worker(monkeypatch):
    from app import settle_orders
    code = '990159'
    monkeypatch.setitem(SELL_RULE, 'fund_code', code)
    with Session(get_engine()) as db:
        user = User(username='sellrace_' + uuid4().hex[:10], password_hash='test-only')
        db.add(user); db.flush()
        account = SimulationAccount(user_id=user.id, available_cash=Decimal('100000'))
        db.add(Fund(code=code, name='隔离赎回测试A', category='债券型', source_url='https://example.invalid',
            source_observed_at=NOW, last_sync_at=NOW, is_sample=False, trade_enabled=True))
        db.add(account); db.flush()
        user_id, account_id = user.id, account.id
        db.add(CashLedger(account_id=account.id, kind='initial_capital', event_key=f'initial:{account.id}',
            amount=100000, available_delta=100000, balance_after=100000))
        add_lot(db, account, code, date(2026, 9, 15))
        db.add(FundNav(fund_code=code, nav_date=date(2026, 9, 16), unit_nav=Decimal('1.1')))
        db.add(FundNav(fund_code=code, nav_date=NOW.date(), unit_nav=Decimal('1.2')))
        db.commit()
        quote = sell_quote(db, account_id, SellQuoteInput(fund_code=code, shares='60'), NOW)
    def submit(key):
        with Session(get_engine()) as db:
            try:
                order = create_sell(db, account_id, SellInput(fund_code=code, shares='60', request_key=key, quote_token=quote['quote_token']), lambda: NOW)
                db.commit(); return order.id
            except HTTPException as exc:
                db.rollback(); return exc.status_code
    try:
        key = uuid4()
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(submit, [key, key, uuid4(), uuid4()]))
        ids = {i for i in outcomes if isinstance(i, UUID)}
        assert len(ids) == 1 and 409 in outcomes
        order_id = ids.pop()
        def finish(i):
            with Session(get_engine()) as db:
                try:
                    order = settle_sell(db, account_id, order_id, lambda: NOW + timedelta(days=1)) if i % 2 else cancel_sell(db, account_id, order_id, lambda: NOW)
                    db.commit(); return order.status
                except HTTPException:
                    db.rollback(); return 'rejected'
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(finish, range(4)))
        with Session(get_engine()) as db:
            assert db.get(SellOrder, order_id).status in ('confirmed', 'cancelled')
            assert db.scalar(select(PositionLot.frozen_shares).where(PositionLot.account_id == account_id)) == 0
            # Create another valid order, then simulate a restarted worker well after both due dates.
            a = lock_account(db, account_id)
            q = sell_quote(db, account_id, SellQuoteInput(fund_code=code, shares='1'), NOW)
            late = create_sell(db, account_id, SellInput(fund_code=code, shares='1', request_key=uuid4(), quote_token=q['quote_token']), lambda: NOW)
            late_id = late.id
            db.commit()
        late_clock = lambda: datetime(2026, 9, 29, tzinfo=CN)
        monkeypatch.setattr(settle_orders, 'utcnow', late_clock)
        monkeypatch.setattr(settle_orders, 'settle_sell', lambda db, aid, oid: settle_sell(db, aid, oid, late_clock))
        # Scope the worker explicitly: other local accounts must never be processed by this test.
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: settle_orders.settle_pending(account_id=account_id), range(2)))
        with Session(get_engine()) as db:
            assert db.get(SellOrder, late_id).status == 'paid'
            assert db.scalar(select(func.count()).select_from(CashLedger).where(CashLedger.event_key == f'sell_paid:{late_id}')) == 1
            a = db.get(SimulationAccount, account_id)
            assert a.redemption_cash == 0
            assert db.scalar(select(func.sum(CashLedger.available_delta)).where(CashLedger.account_id == account_id)) == a.available_cash
    finally:
        with Session(get_engine()) as db:
            sell_ids = select(SellOrder.id).where(SellOrder.account_id == account_id)
            db.execute(delete(SellAllocation).where(SellAllocation.order_id.in_(sell_ids)))
            for model in (SellOrder, PositionLot, CashLedger, BuyOrder):
                db.execute(delete(model).where(model.account_id == account_id))
            db.execute(delete(SimulationAccount).where(SimulationAccount.id == account_id))
            db.execute(delete(User).where(User.id == user_id))
            db.execute(delete(FundNav).where(FundNav.fund_code == code))
            db.execute(delete(Fund).where(Fund.code == code))
            db.commit()
