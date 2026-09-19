from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.dividends import ReviewedDividend, eligible_shares, observe_events, review_event, settle_dividends
from app.models import BuyOrder, CashLedger, DividendEvent, DividendPayment, Fund, FundNav, SellOrder
from app.redemptions import settle_sell
from test_api import db
from test_auth import client, credentials
from test_redemptions import NOW, add_lot, ready_sell, request_body


def event_fixture(db, record=NOW.date(), ex=None, pay=None, amount='0.1', verified=True):
    event = DividendEvent(fund_code='000147', record_date=record, ex_date=ex or record,
        pay_date=pay or record + timedelta(days=2), cash_per_share=Decimal(amount),
        status='observed', source_url='https://www.efunds.com.cn/fund/000147.shtml',
        evidence={'observation': {'fixture': True}}, observed_at=NOW)
    db.add(event); db.flush()
    if verified:
        review_event(db, ReviewedDividend(fund_code='000147', record_date=event.record_date,
            ex_date=event.ex_date, pay_date=event.pay_date, cash_per_share=amount,
            source_url='https://www.efunds.com.cn/test-dividend-announcement',
            source_excerpt='仅测试夹具：登记日申购不参与，登记日赎回参与现金分红。', policy='cash-simulation-v1'))
    return event


def ex_nav(db, event):
    db.add(FundNav(fund_code='000147', nav_date=event.ex_date, unit_nav=Decimal('1.0'),
        dividend_note=f'每份派现金{event.cash_per_share}元'))
    db.flush()


def test_cash_receivable_preserves_assets_and_pays_exactly_once(ready_sell):
    client, db, clock, account, _ = ready_sell
    before = client.get('/api/holdings').json()['total_assets']
    event = event_fixture(db); ex_nav(db, event)
    assert settle_dividends(db, account.id, lambda: NOW) == 0
    db.commit()
    portfolio = client.get('/api/holdings').json()
    assert portfolio['dividend_cash'] == '20.00'
    assert portfolio['total_assets'] == before
    assert portfolio['total_profit'] is not None
    assert portfolio['realized_profit'] == '20.00'
    assert portfolio['holding_profit'] == '-1.60'
    assert portfolio['total_profit'] == '18.40'
    assert client.get('/api/account/dividends').json()['items'][0]['status'] == 'pending'
    later = NOW + timedelta(days=2)
    assert settle_dividends(db, account.id, lambda: later) == 1
    assert settle_dividends(db, account.id, lambda: later) == 0
    db.commit()
    portfolio = client.get('/api/holdings').json()
    assert portfolio['dividend_cash'] == '0.00'
    assert portfolio['total_assets'] == before
    assert db.scalar(select(func.count()).select_from(CashLedger).where(
        CashLedger.account_id == account.id, CashLedger.kind == 'dividend_paid')) == 1
    assert sum(Decimal(e['available_delta']) for e in client.get('/api/account/ledger').json()['items']) == account.available_cash


def test_same_day_purchase_excluded_and_redemption_included_after_exit(ready_sell):
    client, db, clock, account, lots = ready_sell
    body, _ = request_body(client, '200')
    order = client.post('/api/redemptions', json=body).json()
    db.add(FundNav(fund_code='000147', nav_date=NOW.date(), unit_nav=Decimal('1.0')))
    db.commit()
    settle_sell(db, account.id, UUID(order['id']), lambda: NOW + timedelta(days=1))
    assert all(l.remaining_shares == 0 for l in lots)
    add_lot(db, account, '000147', NOW.date() + timedelta(days=1))  # trade on record date
    event = event_fixture(db)
    assert eligible_shares(db, account.id, event)[0] == Decimal('200')
    settle_dividends(db, account.id, lambda: NOW + timedelta(days=3)); db.commit()
    assert client.get('/api/account/dividends').json()['items'][0]['amount'] == '20.00'


def test_prior_redemption_excluded_even_if_confirmed_late(ready_sell):
    client, db, clock, account, _ = ready_sell
    body, _ = request_body(client, '150')
    order = client.post('/api/redemptions', json=body).json()
    event = event_fixture(db, record=NOW.date() + timedelta(days=1))
    ex_nav(db, event)
    assert eligible_shares(db, account.id, event) is None
    assert settle_dividends(db, account.id, lambda: NOW + timedelta(days=3)) == 0
    db.add(FundNav(fund_code='000147', nav_date=NOW.date(), unit_nav=Decimal('1.1'))); db.flush()
    settle_sell(db, account.id, UUID(order['id']), lambda: NOW + timedelta(days=3))
    settle_dividends(db, account.id, lambda: NOW + timedelta(days=3))
    payment = db.scalar(select(DividendPayment).where(DividendPayment.account_id == account.id))
    assert payment.shares == 50 and payment.amount == 5


def test_observed_event_and_missing_ex_nav_never_pay(ready_sell):
    client, db, clock, account, _ = ready_sell
    event = event_fixture(db, verified=False)
    settle_dividends(db, account.id, lambda: NOW + timedelta(days=3))
    assert not db.scalar(select(DividendPayment.id).where(DividendPayment.account_id == account.id))
    assert client.get('/api/holdings').json()['total_profit'] is None
    event.status = 'verified'
    settle_dividends(db, account.id, lambda: NOW + timedelta(days=3))
    assert not db.scalar(select(DividendPayment.id).where(DividendPayment.account_id == account.id))


def test_conflicting_official_distribution_keeps_snapshot_and_stops_payment(ready_sell):
    client, db, clock, account, _ = ready_sell
    event = event_fixture(db); ex_nav(db, event)
    settle_dividends(db, account.id, lambda: NOW)
    observe_events(db, db.get(Fund, '000147'), {'dividend_rows': [[str(event.record_date), str(event.record_date), '0.2', str(event.pay_date)]]}, NOW, event.source_url)
    assert event.status == 'conflict' and event.cash_per_share == Decimal('0.1')
    assert settle_dividends(db, account.id, lambda: NOW + timedelta(days=3)) == 0
    db.commit()
    assert client.get('/api/holdings').json()['total_profit'] is None
    assert client.get('/api/account/dividends').json()['items'][0]['warning']


def test_payment_failure_rolls_back_and_other_user_cannot_read(ready_sell, monkeypatch):
    client, db, clock, account, _ = ready_sell
    event = event_fixture(db); ex_nav(db, event)
    settle_dividends(db, account.id, lambda: NOW); db.commit()
    before = account.available_cash
    original = db.flush
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        if account.available_cash != before:
            raise RuntimeError('injected failure')
    with pytest.raises(RuntimeError), db.begin_nested():
        monkeypatch.setattr(db, 'flush', fail)
        settle_dividends(db, account.id, lambda: NOW + timedelta(days=3))
    monkeypatch.setattr(db, 'flush', original)
    db.expire_all()
    assert account.available_cash == before
    assert db.scalar(select(DividendPayment.status).where(DividendPayment.account_id == account.id)) == 'pending'
    client.post('/api/auth/logout')
    client.post('/api/auth/register', json=credentials()).raise_for_status()
    assert client.get('/api/account/dividends').json()['items'] == []


def test_rounding_is_at_account_level_and_review_is_immutable(ready_sell):
    client, db, clock, account, _ = ready_sell
    event = event_fixture(db, amount='0.00005'); ex_nav(db, event)
    settle_dividends(db, account.id, lambda: NOW + timedelta(days=3))
    payment = db.scalar(select(DividendPayment).where(DividendPayment.account_id == account.id))
    assert payment.amount == Decimal('0.01')  # not .01 per lot
    original = ReviewedDividend.model_validate(event.evidence['review'])
    assert review_event(db, original).id == event.id
    with pytest.raises(ValueError):
        review_event(db, original.model_copy(update={'pay_date': original.pay_date + timedelta(days=1)}))


def test_split_annotation_cannot_be_cleared_by_cash_event(ready_sell):
    client, db, clock, account, _ = ready_sell
    event = event_fixture(db); ex_nav(db, event)
    db.get(FundNav, ('000147', event.ex_date)).dividend_note = '份额折算 1:2'
    settle_dividends(db, account.id, lambda: NOW + timedelta(days=3))
    assert not db.scalar(select(DividendPayment.id).where(DividendPayment.account_id == account.id))
    assert client.get('/api/holdings').json()['total_profit'] is None


def test_historical_event_before_first_purchase_creates_no_zero_payment(ready_sell):
    client, db, clock, account, _ = ready_sell
    event = event_fixture(db, record=date(2026, 8, 1)); ex_nav(db, event)
    settle_dividends(db, account.id, lambda: NOW)
    assert not db.scalar(select(DividendPayment.id).where(DividendPayment.account_id == account.id))


def test_parallel_restart_workers_only_pay_once(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from uuid import uuid4
    from sqlalchemy import delete
    from sqlalchemy.orm import Session
    from app import settle_orders
    from app.db import get_engine
    from app.models import PositionLot, SimulationAccount, User
    code = '990161'
    with Session(get_engine()) as session:
        user = User(username='dividendrace_' + uuid4().hex[:10], password_hash='test-only')
        session.add(user); session.flush()
        account = SimulationAccount(user_id=user.id, available_cash=Decimal('100000'))
        session.add(Fund(code=code, name='隔离分红测试', category='债券型', is_sample=False,
            source_url='https://example.invalid', source_observed_at=NOW, last_sync_at=NOW))
        session.add(account); session.flush()
        aid, uid = account.id, user.id
        add_lot(session, account, code, date(2026, 9, 15))
        session.add(FundNav(fund_code=code, nav_date=NOW.date(), unit_nav=Decimal('1')))
        event = DividendEvent(fund_code=code, record_date=NOW.date(), ex_date=NOW.date(),
            pay_date=NOW.date() + timedelta(days=1), cash_per_share=Decimal('.1'), status='verified',
            source_url='https://example.invalid', evidence={'fixture': True}, observed_at=NOW)
        session.add(event); session.commit()
        eid = event.id
    try:
        monkeypatch.setattr(settle_orders, 'utcnow', lambda: NOW + timedelta(days=3))
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: settle_orders.settle_pending(account_id=aid), range(3)))
        assert all(r['errors'] == 0 for r in results)
        with Session(get_engine()) as session:
            assert session.get(SimulationAccount, aid).available_cash == Decimal('99909.20')
            assert session.scalar(select(func.count()).select_from(CashLedger).where(
                CashLedger.account_id == aid, CashLedger.kind == 'dividend_paid')) == 1
            assert session.scalar(select(func.count()).select_from(DividendPayment).where(DividendPayment.account_id == aid)) == 1
    finally:
        with Session(get_engine()) as session:
            for model in (DividendPayment, PositionLot, CashLedger, BuyOrder):
                session.execute(delete(model).where(model.account_id == aid))
            session.execute(delete(DividendEvent).where(DividendEvent.id == eid))
            session.execute(delete(SimulationAccount).where(SimulationAccount.id == aid))
            session.execute(delete(User).where(User.id == uid))
            session.execute(delete(FundNav).where(FundNav.fund_code == code))
            session.execute(delete(Fund).where(Fund.code == code))
            session.commit()
