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
from app.models import BuyOrder, CashLedger, Fund, FundNav, FundSyncRun, PositionLot, SimulationAccount, User
from app.trade_rules import CN, RULE, fees, rounded, schedule, trading_day, utcnow
from app.trades import BuyInput, cancel_buy, clock_provider, create_buy, settle_buy
from test_auth import client, credentials
from test_api import db

NOW = datetime(2026, 9, 14, 14, 30, tzinfo=CN)


@pytest.fixture
def ready(client, db):
    fund = db.get(Fund, '000147')
    fund.trade_enabled, fund.is_sample, fund.last_sync_at = True, False, NOW
    # Tests own the outer rollback; no existing user data is touched.
    db.execute(delete(FundSyncRun).where(FundSyncRun.fund_code == fund.code))
    db.execute(delete(FundNav).where(FundNav.fund_code == fund.code, FundNav.nav_date >= NOW.date()))
    client.post('/api/auth/register', json=credentials()).raise_for_status()
    clock = [NOW]
    app.dependency_overrides[utcnow] = lambda: clock[0]
    app.dependency_overrides[clock_provider] = lambda: lambda: clock[0]
    return client, db, clock


def buy(client, amount='1000.00', **extra):
    return client.post('/api/orders', json={
        'fund_code': '000147', 'amount': amount, 'request_key': str(uuid4()),
        'rule_version': RULE['version'], 'trade_date': '2026-09-14', **extra})


@pytest.mark.parametrize('when,trade,confirm', [
    ('2026-09-14T14:59:59+08:00', '2026-09-14', '2026-09-15'),
    ('2026-09-14T15:00:00+08:00', '2026-09-15', '2026-09-16'),
    ('2026-09-19T10:00:00+08:00', '2026-09-21', '2026-09-22'),
    ('2026-09-24T15:00:00+08:00', '2026-09-28', '2026-09-29'),
    ('2026-09-30T15:00:00+08:00', '2026-10-08', '2026-10-09'),
    ('2026-10-10T10:00:00+08:00', '2026-10-12', '2026-10-13'),
])
def test_calendar_cutoff_weekends_and_holidays(when, trade, confirm):
    t, c, cutoff = schedule(datetime.fromisoformat(when))
    assert (str(t), str(c)) == (trade, confirm)
    assert cutoff.hour == 15 and cutoff.utcoffset() == timedelta(hours=8)
    assert not trading_day(date(2026, 2, 28))  # Workday makeup is still exchange weekend.


def test_calendar_fails_closed_without_next_year():
    with pytest.raises(HTTPException):
        schedule(datetime(2026, 12, 31, 14, tzinfo=CN))


def test_contract_fee_example_and_tier_boundaries():
    fee, net, _ = fees(Decimal('100000'))
    assert (fee, net, rounded(net / Decimal('1.0400'))) == (Decimal('793.65'), Decimal('99206.35'), Decimal('95390.72'))
    assert fees(Decimal('999999.99'))[2]['rate'] == '0.008'
    assert fees(Decimal('1000000'))[2]['rate'] == '0.005'
    assert fees(Decimal('2000000'))[2]['rate'] == '0.003'
    assert fees(Decimal('5000000'))[:2] == (Decimal('1000.00'), Decimal('4999000.00'))


@pytest.mark.integration
def test_quote_reserve_replay_and_cancel_are_single_atomic_events(ready):
    client, db, clock = ready
    quote = client.post('/api/trades/quote', json={'fund_code': '000147', 'amount': '1000.00'}).json()
    assert (quote['fee'], quote['net_amount'], quote['trade_date']) == ('7.94', '992.06', '2026-09-14')
    key = str(uuid4())
    first = buy(client, request_key=key)
    assert first.status_code == 201
    order = first.json()
    assert order['confirmed_nav'] is None and order['shares'] is None
    assert buy(client, request_key=key).json()['id'] == order['id']
    assert buy(client, '2000', request_key=key).status_code == 409
    account = client.get('/api/account').json()
    assert (account['available_cash'], account['reserved_cash'], account['total_assets']) == ('99000.00', '1000.00', '100000.00')
    assert client.post(f"/api/orders/{order['id']}/cancel").json()['status'] == 'cancelled'
    assert client.post(f"/api/orders/{order['id']}/cancel").status_code == 200
    assert buy(client, request_key=key).json()['status'] == 'cancelled'
    account = client.get('/api/account').json()
    assert (account['available_cash'], account['reserved_cash']) == ('100000.00', '0.00')
    ledger = client.get('/api/account/ledger').json()['items']
    assert len(ledger) == 3
    assert sum(Decimal(e['available_delta']) for e in ledger) == Decimal(account['available_cash'])
    assert sum(Decimal(e['reserved_delta']) for e in ledger) == Decimal(account['reserved_cash'])


@pytest.mark.parametrize('amount', ['0', '-1', '0.99', '1000.001', 'NaN', 'Infinity', '1e9999'])
@pytest.mark.integration
def test_invalid_money_never_reserves(ready, amount):
    client, db, _ = ready
    assert buy(client, amount).status_code == 422
    assert client.get('/api/account').json()['available_cash'] == '100000.00'
    assert client.get('/api/orders').json()['total'] == 0


@pytest.mark.integration
def test_settlement_failure_keeps_reserve_and_creates_no_partial_position(ready, monkeypatch):
    from app import trades
    client, db, clock = ready
    order = buy(client).json()
    account_id = UUID(client.get('/api/account').json()['id'])
    db.add(FundNav(fund_code='000147', nav_date=NOW.date(), unit_nav=Decimal('1.04')))
    db.commit()
    def fail(*args, **kwargs):
        raise RuntimeError('ledger unavailable')
    monkeypatch.setattr(trades, 'add_ledger', fail)
    with pytest.raises(RuntimeError), db.begin_nested():
        settle_buy(db, account_id, UUID(order['id']), lambda: NOW + timedelta(days=1))
    assert db.get(BuyOrder, UUID(order['id'])).status == 'pending'
    assert db.get(SimulationAccount, account_id).reserved_cash == 1000
    assert db.scalar(select(func.count()).select_from(PositionLot).where(PositionLot.order_id == UUID(order['id']))) == 0


@pytest.mark.integration
def test_reject_balance_unverified_rule_extra_owner_and_changed_date(ready):
    client, db, clock = ready
    assert buy(client, '100000.01').status_code == 409
    assert buy(client, fund_code='000148').status_code == 409
    assert buy(client, account_id=str(uuid4())).status_code == 422
    assert buy(client, rule_version='old').status_code == 409
    clock[0] = NOW.replace(hour=15, minute=0)
    assert buy(client).status_code == 409
    assert client.get('/api/orders').json()['total'] == 0


@pytest.mark.integration
def test_only_exact_nav_on_or_after_confirmation_day_settles_once(ready):
    client, db, clock = ready
    order = buy(client).json()
    url = f"/api/orders/{order['id']}/refresh"
    assert client.post(url).json()['status'] == 'pending'
    clock[0] = NOW + timedelta(days=1)
    assert client.post(url).json()['status'] == 'pending'  # Yesterday's cached NAV is not enough.
    db.add(FundNav(fund_code='000147', nav_date=date(2026, 9, 14), unit_nav=Decimal('1.04')))
    db.commit()
    clock[0] = NOW
    assert client.post(url).json()['status'] == 'pending'  # Even early publication cannot settle T day.
    clock[0] = NOW + timedelta(days=1)
    result = client.post(url).json()
    assert (result['status'], result['shares'], result['fee']) == ('confirmed', '953.90', '7.94')
    assert client.post(url).json()['shares'] == '953.90'
    assert client.post(f"/api/orders/{order['id']}/cancel").status_code == 409
    assert db.scalar(select(func.count()).select_from(PositionLot).where(PositionLot.order_id == UUID(order['id']))) == 1
    account = client.get('/api/account').json()
    assert (account['available_cash'], account['reserved_cash'], account['total_assets']) == ('99000.00', '0.00', '99992.06')
    ledger = client.get('/api/account/ledger').json()['items']
    assert len(ledger) == 3
    confirmed_entry = next(e for e in ledger if e['kind'] == 'buy_confirmed')
    assert confirmed_entry['available_delta'] == '0.00'
    assert Decimal(confirmed_entry['reserved_delta']) == -1000
    assert client.get('/api/holdings').json()['items'][0]['lots'][0]['confirmation_date'] == '2026-09-15'


@pytest.mark.integration
def test_cutoff_cancellation_and_pending_data_conflict(ready):
    client, db, clock = ready
    order = buy(client).json()
    clock[0] = NOW.replace(hour=15, minute=0)
    assert client.post(f"/api/orders/{order['id']}/cancel").status_code == 409
    db.add(FundNav(fund_code='000147', nav_date=date(2026, 9, 14), unit_nav=Decimal('1.04')))
    db.add(FundSyncRun(fund_code='000147', status='conflict'))
    db.commit()
    clock[0] = NOW + timedelta(days=1)
    assert client.post(f"/api/orders/{order['id']}/refresh").json()['status'] == 'pending'
    assert client.get('/api/account').json()['reserved_cash'] == '1000.00'


@pytest.mark.integration
def test_user_cannot_read_cancel_settle_or_list_other_users_orders(ready):
    client, db, _ = ready
    order = buy(client).json()
    client.post('/api/auth/register', json=credentials()).raise_for_status()
    assert client.get(f"/api/orders/{order['id']}").status_code == 404
    assert client.post(f"/api/orders/{order['id']}/cancel").status_code == 404
    assert client.post(f"/api/orders/{order['id']}/refresh").status_code == 404
    assert client.get('/api/orders').json()['total'] == 0
    assert client.get('/api/holdings').json()['items'] == []
    assert client.get('/api/account').json()['available_cash'] == '100000.00'
    assert client.get('/api/orders').headers['cache-control'] == 'no-store'


@pytest.mark.integration
def test_transaction_failure_rolls_back_money_order_and_lot(ready, monkeypatch):
    from app import trades
    client, db, _ = ready
    account_id = UUID(client.get('/api/account').json()['id'])
    original = trades.add_ledger
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('injected failure after money movement')
    monkeypatch.setattr(trades, 'add_ledger', fail)
    body = BuyInput(fund_code='000147', amount='1000', request_key=uuid4(), rule_version=RULE['version'], trade_date=NOW.date())
    with pytest.raises(RuntimeError), db.begin_nested():
        create_buy(db, account_id, body, lambda: NOW)
    assert db.get(SimulationAccount, account_id).available_cash == 100000
    assert client.get('/api/orders').json()['total'] == 0


@pytest.mark.parametrize('race', ['replay_settle', 'overspend_cancel_settle'])
@pytest.mark.integration
def test_real_connections_serialize_replays_overspending_and_duplicate_settlement(monkeypatch, race):
    # A separate temporary fund/account keeps concurrent commits out of all user data.
    code, username = '990149', 'race_' + uuid4().hex[:12]
    monkeypatch.setitem(RULE, 'fund_code', code)
    with Session(get_engine()) as db:
        user = User(username=username, password_hash='test-only')
        db.add(user); db.flush()
        account = SimulationAccount(user_id=user.id, available_cash=Decimal('100000'))
        fund = Fund(code=code, name='测试债券A', category='债券型', source_url='https://example.invalid',
                    source_observed_at=NOW, last_sync_at=NOW, is_sample=False, trade_enabled=True)
        db.add_all([account, fund]); db.flush()
        user_id, account_id = user.id, account.id
        db.add(CashLedger(account_id=account_id, event_key=f'initial:{account_id}', kind='initial_capital',
                          amount=100000, balance_after=100000, available_delta=100000))
        db.add(FundNav(fund_code=code, nav_date=NOW.date(), unit_nav=Decimal('1.04')))
        db.commit()
    def request(key):
        with Session(get_engine()) as db:
            try:
                order = create_buy(db, account_id, BuyInput(fund_code=code, amount='60000', request_key=key,
                                   rule_version=RULE['version'], trade_date=NOW.date()), lambda: NOW)
                db.commit()
                return order.id
            except HTTPException as exc:
                db.rollback()
                return exc.status_code
    try:
        key = uuid4()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(request, [key] * 4 if race == 'replay_settle' else [uuid4() for _ in range(4)]))
        if race == 'replay_settle':
            assert len(set(results)) == 1 and isinstance(results[0], UUID)
        else:
            assert sum(isinstance(r, UUID) for r in results) == 1
            assert results.count(409) == 3
        order_id = next(r for r in results if isinstance(r, UUID))
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(request, [uuid4(), uuid4()])) == [409, 409]
        def settle(i):
            with Session(get_engine()) as db:
                try:
                    result = cancel_buy(db, account_id, order_id, lambda: NOW) if race != 'replay_settle' and i % 2 else settle_buy(db, account_id, order_id, lambda: NOW + timedelta(days=1))
                    db.commit()
                    return result.status
                except HTTPException as exc:
                    db.rollback()
                    return exc.status_code
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(settle, range(4)))
        if race == 'replay_settle':
            assert outcomes == ['confirmed'] * 4
        with Session(get_engine()) as db:
            account = db.get(SimulationAccount, account_id)
            confirmed = db.get(BuyOrder, order_id).status == 'confirmed'
            assert (account.available_cash, account.reserved_cash) == (40000 if confirmed else 100000, 0)
            assert db.scalar(select(func.count()).select_from(PositionLot).where(PositionLot.account_id == account_id)) == int(confirmed)
            assert db.scalar(select(func.count()).select_from(CashLedger).where(CashLedger.account_id == account_id)) == 3
    finally:
        with Session(get_engine()) as db:
            for model in (PositionLot, CashLedger, BuyOrder):
                db.execute(delete(model).where(model.account_id == account_id))
            db.execute(delete(SimulationAccount).where(SimulationAccount.id == account_id))
            db.execute(delete(User).where(User.id == user_id))
            db.execute(delete(FundNav).where(FundNav.fund_code == code))
            db.execute(delete(Fund).where(Fund.code == code))
            db.commit()
